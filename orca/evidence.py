from __future__ import annotations

from dataclasses import asdict, dataclass
from contextlib import contextmanager
from hashlib import sha256
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .domain import new_id, utc_now
from .security import redact, redact_text
from .schema import ensure_schema


MAX_EVENT_PAYLOAD_BYTES = 256_000


@dataclass(frozen=True)
class EvidenceEvent:
    id: str
    timestamp: str
    correlation_id: str
    actor: str
    lane: str
    kind: str
    payload: dict[str, Any]
    previous_hash: str
    event_hash: str


class EvidenceStore:
    """Append-only SQLite event log with a verifiable hash chain."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self.db.execute("PRAGMA busy_timeout=5000")
        if self.path != ":memory:":
            self.db.execute("PRAGMA journal_mode=WAL")
        self.schema_version = ensure_schema(self.db)
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                id TEXT UNIQUE NOT NULL, timestamp TEXT NOT NULL,
                correlation_id TEXT NOT NULL, actor TEXT NOT NULL,
                lane TEXT NOT NULL, kind TEXT NOT NULL,
                payload TEXT NOT NULL, previous_hash TEXT NOT NULL,
                event_hash TEXT UNIQUE NOT NULL
            )"""
        )
        self.db.execute(
            """CREATE TRIGGER IF NOT EXISTS events_no_update
               BEFORE UPDATE ON events BEGIN
                   SELECT RAISE(ABORT, 'events are append-only');
               END"""
        )
        self.db.execute(
            """CREATE TRIGGER IF NOT EXISTS events_no_delete
               BEFORE DELETE ON events BEGIN
                   SELECT RAISE(ABORT, 'events are append-only');
               END"""
        )
        self.db.commit()

    @contextmanager
    def transaction(self):
        """Hold the store lock and own one immediate transaction when needed."""
        with self._lock:
            owns_transaction = not self.db.in_transaction
            if owns_transaction:
                self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
                if owns_transaction:
                    self.db.commit()
            except BaseException:
                if owns_transaction:
                    self.db.rollback()
                raise

    def append(self, *, correlation_id: str, actor: str, lane: str,
               kind: str, payload: dict[str, Any]) -> EvidenceEvent:
        with self.transaction():
            previous = self.db.execute(
                "SELECT event_hash FROM events ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            previous_hash = previous[0] if previous else "GENESIS"
            safe_payload = redact(payload)
            encoded_payload = json.dumps(
                safe_payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
            if len(encoded_payload.encode("utf-8")) > MAX_EVENT_PAYLOAD_BYTES:
                raise ValueError("evidence payload exceeds the size limit")
            base = {
                "id": new_id("evt"), "timestamp": utc_now(),
                "correlation_id": redact_text(str(correlation_id))[:240],
                "actor": redact_text(str(actor))[:240],
                "lane": redact_text(str(lane))[:240],
                "kind": redact_text(str(kind))[:240], "payload": safe_payload,
                "previous_hash": previous_hash,
            }
            digest = sha256(json.dumps(
                base, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()).hexdigest()
            event = EvidenceEvent(**base, event_hash=digest)
            self.db.execute(
                "INSERT INTO events (id,timestamp,correlation_id,actor,lane,kind,payload,previous_hash,event_hash) VALUES (?,?,?,?,?,?,?,?,?)",
                (event.id, event.timestamp, event.correlation_id, event.actor, event.lane,
                 event.kind, encoded_payload, event.previous_hash, event.event_hash),
            )
            return event

    def list(self, *, correlation_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        sql = "SELECT * FROM events"
        args: list[Any] = []
        if correlation_id:
            sql += " WHERE correlation_id = ?"
            args.append(correlation_id)
        sql += " ORDER BY seq DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self.db.execute(sql, args).fetchall()
        events = []
        for row in rows:
            event = dict(row)
            for field in ("correlation_id", "actor", "lane", "kind"):
                event[field] = redact_text(str(event[field]))
            try:
                event["payload"] = redact(json.loads(row["payload"]))
            except (json.JSONDecodeError, TypeError, ValueError):
                event["payload"] = {"error": "invalid evidence payload"}
            events.append(event)
        return events

    def verify(self) -> bool:
        previous = "GENESIS"
        with self._lock:
            try:
                for row in self.db.execute("SELECT * FROM events ORDER BY seq"):
                    base = {k: row[k] for k in (
                        "id", "timestamp", "correlation_id", "actor", "lane", "kind")}
                    base["payload"] = json.loads(row["payload"])
                    base["previous_hash"] = previous
                    expected = sha256(json.dumps(
                        base, sort_keys=True, separators=(",", ":"), allow_nan=False
                    ).encode()).hexdigest()
                    if row["previous_hash"] != previous or row["event_hash"] != expected:
                        return False
                    previous = row["event_hash"]
            except (json.JSONDecodeError, TypeError, ValueError):
                return False
        return True
