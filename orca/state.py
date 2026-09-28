from __future__ import annotations

from dataclasses import asdict
from hmac import compare_digest
import json
import sqlite3
import threading

from .domain import Action, Job, JobStatus, PermissionLevel
from .schema import control_state_digest


MAX_CONTROL_STATE_BYTES = 16_000_000


class StateStore:
    """Transactional snapshots for mutable control-plane state."""

    def __init__(self, db: sqlite3.Connection, *, connection_lock=None) -> None:
        self.db = db
        self._lock = connection_lock if connection_lock is not None else threading.RLock()
        with self._lock:
            self.db.execute(
                """CREATE TABLE IF NOT EXISTS control_state (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    revision INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    state_hash TEXT NOT NULL,
                    evidence_head TEXT NOT NULL
                )"""
            )
            self.db.commit()

    def _row(self):
        return self.db.execute(
            "SELECT revision, payload, state_hash, evidence_head "
            "FROM control_state WHERE singleton=1"
        ).fetchone()

    def _evidence_head(self) -> str:
        exists = self.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'"
        ).fetchone()
        if exists is None:
            return "GENESIS"
        row = self.db.execute(
            "SELECT event_hash FROM events ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        return str(row[0]) if row else "GENESIS"

    def _verify_row(self, row, *, require_current_head: bool = True) -> None:
        try:
            revision = int(row[0])
            payload = str(row[1])
            if len(payload.encode("utf-8")) > MAX_CONTROL_STATE_BYTES:
                raise RuntimeError("control state exceeds the size limit")
            state_hash = row[2]
            evidence_head = str(row[3])
            expected = control_state_digest(revision, payload, evidence_head)
            if not isinstance(state_hash, str) or not compare_digest(state_hash, expected):
                raise RuntimeError("control state integrity check failed")
            if evidence_head != "GENESIS":
                referenced = self.db.execute(
                    "SELECT 1 FROM events WHERE event_hash=?", (evidence_head,)
                ).fetchone()
                if referenced is None:
                    raise RuntimeError("control state evidence reference is missing")
            if require_current_head:
                current_head = self._evidence_head()
                if not compare_digest(evidence_head, current_head):
                    raise RuntimeError(
                        "control state evidence head does not match current evidence chain head"
                    )
        except (IndexError, TypeError, ValueError, sqlite3.DatabaseError) as exc:
            raise RuntimeError("control state integrity check failed") from exc

    def load(self) -> tuple[int, dict | None]:
        with self._lock:
            row = self._row()
            if row is None:
                if self._evidence_head() != "GENESIS":
                    raise RuntimeError(
                        "control state is missing for the current evidence chain head")
                return 0, None
            self._verify_row(row)
            try:
                payload = json.loads(
                    row[1], parse_constant=lambda value: (_ for _ in ()).throw(
                        ValueError(f"invalid JSON constant: {value}")))
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise RuntimeError("control state integrity check failed") from exc
            if not isinstance(payload, dict):
                raise RuntimeError("control state integrity check failed")
            return int(row[0]), payload

    def current_revision(self) -> int:
        with self._lock:
            row = self._row()
            if row is None:
                if self._evidence_head() != "GENESIS":
                    raise RuntimeError(
                        "control state is missing for the current evidence chain head")
                return 0
            self._verify_row(row)
            return int(row[0])

    def verify_integrity(self) -> bool:
        with self._lock:
            row = self._row()
            if row is not None:
                self._verify_row(row)
            elif self._evidence_head() != "GENESIS":
                raise RuntimeError(
                    "control state is missing for the current evidence chain head")
            return True

    def save(self, payload: dict, *, expected_revision: int) -> int:
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode("utf-8")) > MAX_CONTROL_STATE_BYTES:
            raise ValueError("control state exceeds the size limit")
        with self._lock:
            owns_transaction = not self.db.in_transaction
            if owns_transaction:
                self.db.execute("BEGIN IMMEDIATE")
            try:
                row = self._row()
                if row is not None:
                    # A ControlPlane mutation appends evidence and checkpoints state in
                    # one encompassing transaction. Its previously verified row will
                    # therefore reference the prior head until this save completes.
                    # Standalone saves have no such in-flight evidence advance and must
                    # remain bound to the current head.
                    self._verify_row(row, require_current_head=owns_transaction)
                elif owns_transaction and self._evidence_head() != "GENESIS":
                    raise RuntimeError(
                        "control state is missing for the current evidence chain head")
                current = int(row[0]) if row else 0
                if current != expected_revision:
                    raise RuntimeError("stale control-plane state revision")
                revision = current + 1
                evidence_head = self._evidence_head()
                state_hash = control_state_digest(revision, encoded, evidence_head)
                if row:
                    changed = self.db.execute(
                        "UPDATE control_state SET revision=?, payload=?, state_hash=?, evidence_head=? "
                        "WHERE singleton=1 AND revision=?",
                        (revision, encoded, state_hash, evidence_head, expected_revision),
                    ).rowcount
                    if changed != 1:
                        raise RuntimeError("concurrent control-plane state update")
                else:
                    self.db.execute(
                        "INSERT INTO control_state "
                        "(singleton, revision, payload, state_hash, evidence_head) "
                        "VALUES(1, ?, ?, ?, ?)",
                        (revision, encoded, state_hash, evidence_head),
                    )
                if owns_transaction:
                    self.db.commit()
                return revision
            except BaseException:
                if owns_transaction:
                    self.db.rollback()
                raise


def job_to_dict(job: Job) -> dict:
    data = asdict(job)
    data["level"] = int(job.level)
    data["status"] = job.status.value
    requested = job.action.requested_level
    data["action"]["requested_level"] = int(requested) if requested is not None else None
    return data


def job_from_dict(data: dict) -> Job:
    raw = dict(data)
    action_data = dict(raw.pop("action"))
    if action_data.get("requested_level") is not None:
        action_data["requested_level"] = PermissionLevel(action_data["requested_level"])
    raw["action"] = Action(**action_data)
    raw["level"] = PermissionLevel(raw["level"])
    raw["status"] = JobStatus(raw["status"])
    return Job(**raw)
