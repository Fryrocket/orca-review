from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from hmac import compare_digest
import json
import re
import sqlite3
import threading
from typing import Any

from .domain import utc_now
from .schema import (
    mutation_receipt_digest,
    mutation_receipt_set_digest,
    ensure_receipt_guards,
    validate_receipt_guards,
    validate_receipt_schema,
)
from .security import redact


_KEY = re.compile(r"^[A-Za-z0-9_.:-]{16,128}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
MAX_RESPONSE_BYTES = 1_000_000


class IdempotencyConflict(RuntimeError):
    """An idempotency key was reused for a different mutation."""


class StateRevisionConflict(RuntimeError):
    """A mutation targeted a control-plane revision that is no longer current."""


@dataclass(frozen=True)
class MutationReceipt:
    key: str
    actor: str
    operation: str
    request_hash: str
    response: dict[str, Any]
    http_status: int
    state_revision: int
    created_at: str
    receipt_hash: str


class IdempotencyStore:
    """Append-only mutation receipts stored in the control-plane database."""

    def __init__(self, db: sqlite3.Connection, *, connection_lock=None) -> None:
        self.db = db
        self._lock = connection_lock if connection_lock is not None else threading.RLock()
        with self._lock:
            owns_transaction = not self.db.in_transaction
            savepoint = "orca_idempotency_init_guard"
            if owns_transaction:
                self.db.execute("BEGIN IMMEDIATE")
            else:
                self.db.execute(f"SAVEPOINT {savepoint}")
            try:
                validate_receipt_schema(self.db)
                ensure_receipt_guards(self.db)
                validate_receipt_guards(self.db)
                if owns_transaction:
                    self.db.commit()
                else:
                    self.db.execute(f"RELEASE {savepoint}")
            except BaseException:
                if owns_transaction:
                    self.db.rollback()
                else:
                    self.db.execute(f"ROLLBACK TO {savepoint}")
                    self.db.execute(f"RELEASE {savepoint}")
                raise

    @contextmanager
    def _read_snapshot(self):
        """Keep multi-query integrity reads on one SQLite snapshot."""

        owns_transaction = not self.db.in_transaction
        if owns_transaction:
            self.db.execute("BEGIN")
        try:
            yield
            if owns_transaction:
                self.db.commit()
        except BaseException:
            if owns_transaction:
                self.db.rollback()
            raise

    @staticmethod
    def validate(key: str, actor: str, operation: str, request_hash: str) -> None:
        if not isinstance(key, str) or not _KEY.fullmatch(key):
            raise ValueError("idempotency key must contain 16-128 safe characters")
        if not isinstance(actor, str) or not actor or len(actor) > 120:
            raise ValueError("idempotency actor must be concise non-empty text")
        if not isinstance(operation, str) or not operation or len(operation) > 240:
            raise ValueError("idempotency operation must be concise non-empty text")
        if not isinstance(request_hash, str) or not _HASH.fullmatch(request_hash):
            raise ValueError("idempotency request hash must be lowercase SHA-256")

    def lookup(self, *, key: str, actor: str, operation: str,
               request_hash: str) -> MutationReceipt | None:
        self.validate(key, actor, operation, request_hash)
        with self._lock:
            with self._read_snapshot():
                self._verify_anchor()
                row = self.db.execute(
                    "SELECT * FROM mutation_receipts WHERE idempotency_key=?", (key,)
                ).fetchone()
                if row is None:
                    return None
                receipt = self._decode_row(row)
                if (receipt.actor, receipt.operation, receipt.request_hash) != (
                        actor, operation, request_hash):
                    raise IdempotencyConflict(
                        "idempotency key was already used for a different mutation")
                return receipt

    def record(self, *, key: str, actor: str, operation: str,
               request_hash: str, response: dict[str, Any], http_status: int,
               state_revision: int) -> MutationReceipt:
        self.validate(key, actor, operation, request_hash)
        if (isinstance(http_status, bool) or not isinstance(http_status, int)
                or not 100 <= http_status <= 599):
            raise ValueError("idempotency HTTP status is invalid")
        if type(state_revision) is not int or state_revision < 0:
            raise ValueError("idempotency state revision is invalid")
        if not isinstance(response, dict):
            raise ValueError("idempotency response must be an object")
        safe_response = redact(response)
        encoded = json.dumps(
            safe_response, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode("utf-8")) > MAX_RESPONSE_BYTES:
            raise ValueError("idempotency response exceeds the size limit")
        created_at = utc_now()
        receipt_hash = mutation_receipt_digest(
            key, actor, operation, request_hash, encoded, http_status,
            state_revision, created_at)
        receipt = MutationReceipt(
            key, actor, operation, request_hash, safe_response, http_status,
            state_revision, created_at, receipt_hash,
        )
        with self._lock:
            owns_transaction = not self.db.in_transaction
            savepoint = "orca_idempotency_record_guard"
            if owns_transaction:
                self.db.execute("BEGIN IMMEDIATE")
            else:
                self.db.execute(f"SAVEPOINT {savepoint}")
            try:
                self._verify_anchor()
                self.db.execute(
                    "INSERT INTO mutation_receipts VALUES(?,?,?,?,?,?,?,?,?)",
                    (receipt.key, receipt.actor, receipt.operation, receipt.request_hash,
                     encoded, receipt.http_status, receipt.state_revision,
                     receipt.created_at, receipt.receipt_hash),
                )
                rows = self._receipt_hash_rows()
                changed = self.db.execute(
                    "UPDATE mutation_receipt_integrity SET receipt_count=?, "
                    "receipt_set_hash=? WHERE singleton=1",
                    (len(rows), mutation_receipt_set_digest(rows)),
                ).rowcount
                if changed != 1:
                    raise RuntimeError("mutation receipt integrity anchor is missing")
                if owns_transaction:
                    self.db.commit()
                else:
                    self.db.execute(f"RELEASE {savepoint}")
            except BaseException:
                if owns_transaction:
                    self.db.rollback()
                else:
                    self.db.execute(f"ROLLBACK TO {savepoint}")
                    self.db.execute(f"RELEASE {savepoint}")
                raise
        return receipt

    def verify(self) -> bool:
        """Validate the complete contents and digest of every stored receipt."""

        with self._lock:
            try:
                with self._read_snapshot():
                    self._verify_anchor()
            except sqlite3.DatabaseError as exc:
                raise RuntimeError("mutation receipt integrity check failed") from exc
        return True

    def _receipt_hash_rows(self) -> list[tuple[str, str]]:
        rows = self.db.execute(
            "SELECT * FROM mutation_receipts ORDER BY idempotency_key"
        ).fetchall()
        receipts = [self._decode_row(row) for row in rows]
        return [(receipt.key, receipt.receipt_hash) for receipt in receipts]

    def _verify_anchor(self) -> int:
        anchor = self.db.execute(
            "SELECT receipt_count, receipt_set_hash "
            "FROM mutation_receipt_integrity WHERE singleton=1"
        ).fetchone()
        extra = self.db.execute(
            "SELECT COUNT(*) FROM mutation_receipt_integrity"
        ).fetchone()
        if (anchor is None or extra is None
                or type(extra[0]) is not int or extra[0] != 1):
            raise RuntimeError("mutation receipt integrity anchor is invalid")
        rows = self._receipt_hash_rows()
        stored_count = anchor[0]
        stored_hash = anchor[1]
        expected_hash = mutation_receipt_set_digest(rows)
        if (type(stored_count) is not int or stored_count != len(rows)
                or not isinstance(stored_hash, str)
                or not _HASH.fullmatch(stored_hash)
                or not compare_digest(stored_hash, expected_hash)):
            raise RuntimeError("mutation receipt integrity anchor is invalid")
        return len(rows)

    @classmethod
    def _decode_row(cls, row) -> MutationReceipt:
        try:
            if (len(row) != 9
                    or any(not isinstance(row[index], str)
                           for index in (0, 1, 2, 3, 4, 7, 8))):
                raise ValueError("receipt text fields are invalid")
            key, actor, operation, request_hash = row[:4]
            cls.validate(key, actor, operation, request_hash)
            encoded = row[4]
            response = json.loads(encoded)
            if not isinstance(response, dict):
                raise ValueError("response is not an object")
            canonical = json.dumps(
                response, sort_keys=True, separators=(",", ":"), allow_nan=False)
            if canonical != encoded or len(encoded.encode("utf-8")) > MAX_RESPONSE_BYTES:
                raise ValueError("response encoding is invalid")
            http_status = row[5]
            state_revision = row[6]
            if (type(http_status) is not int or not 100 <= http_status <= 599
                    or type(state_revision) is not int or state_revision < 0):
                raise ValueError("receipt numeric fields are invalid")
            created_at = row[7]
            parsed_at = datetime.fromisoformat(created_at)
            if len(created_at) > 64 or parsed_at.tzinfo is None:
                raise ValueError("receipt timestamp is invalid")
            stored_hash = row[8]
            expected_hash = mutation_receipt_digest(
                key, actor, operation, request_hash, encoded, http_status,
                state_revision, created_at)
            if not re.fullmatch(r"[0-9a-f]{64}", stored_hash):
                raise ValueError("receipt hash is invalid")
            if not compare_digest(stored_hash, expected_hash):
                raise ValueError("receipt hash mismatch")
        except (IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("stored idempotency receipt is invalid") from exc
        return MutationReceipt(
            key, actor, operation, request_hash, response, http_status,
            state_revision, created_at, stored_hash,
        )

    def count(self) -> int:
        with self._lock:
            with self._read_snapshot():
                return self._verify_anchor()
