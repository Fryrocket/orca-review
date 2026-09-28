from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
import re
import sqlite3
import threading
from typing import Any

from .domain import new_id, utc_now
from .security import redact


RECORD_TYPES = frozenset({
    "product", "supplier_offer", "channel_listing", "inventory_position",
    "customer", "relationship", "order", "fulfillment",
})
RECORD_STATUSES = frozenset({"draft", "active", "paused", "archived", "unknown"})
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
MAX_DOCUMENT_BYTES = 128_000


class BusinessRevisionConflict(RuntimeError):
    """A source tried to overwrite a newer canonical business record."""


@dataclass(frozen=True)
class BusinessWrite:
    record: dict[str, Any]
    event: dict[str, Any]
    replayed: bool = False


class BusinessStore:
    """Canonical business records backed by an append-only source event log.

    This store is deliberately connector-neutral.  A record says what a source
    reported; it never claims that Shopify, Amazon, a supplier, or an ERP is
    connected merely because that source name appears in a draft/import.
    """

    def __init__(self, db: sqlite3.Connection, *, connection_lock=None) -> None:
        self.db = db
        self._lock = connection_lock if connection_lock is not None else threading.RLock()
        with self._lock:
            self.db.executescript(
                """
                CREATE TABLE IF NOT EXISTS business_records (
                    record_type TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    source_system TEXT NOT NULL,
                    source_revision INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    data TEXT NOT NULL,
                    provenance TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    observed_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    record_hash TEXT NOT NULL,
                    PRIMARY KEY(record_type, record_id)
                );
                CREATE TABLE IF NOT EXISTS business_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE NOT NULL,
                    event_type TEXT NOT NULL,
                    record_type TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    source_system TEXT NOT NULL,
                    source_revision INTEGER NOT NULL,
                    correlation_id TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    UNIQUE(source_system, record_type, record_id, source_revision)
                );
                CREATE TRIGGER IF NOT EXISTS business_events_no_update
                BEFORE UPDATE ON business_events BEGIN
                    SELECT RAISE(ABORT, 'business events are append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS business_events_no_delete
                BEFORE DELETE ON business_events BEGIN
                    SELECT RAISE(ABORT, 'business events are append-only');
                END;
                """
            )
            self.db.commit()

    @staticmethod
    def _text(value: object, name: str, *, maximum: int = 128) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise ValueError(f"business {name} is invalid")
        result = value.strip()
        if name in {"record id", "source system", "correlation id"} and not _SAFE_ID.fullmatch(result):
            raise ValueError(f"business {name} is invalid")
        return result

    @staticmethod
    def _document(value: object, name: str) -> tuple[dict[str, Any], str]:
        if not isinstance(value, dict):
            raise ValueError(f"business {name} must be an object")
        safe = redact(value)
        encoded = json.dumps(safe, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode("utf-8")) > MAX_DOCUMENT_BYTES:
            raise ValueError(f"business {name} exceeds the size limit")
        return safe, encoded

    @staticmethod
    def _validate_inventory(data: dict[str, Any]) -> None:
        required = {"sku", "location", "on_hand", "reserved"}
        if not required <= set(data):
            raise ValueError("inventory position requires sku, location, on_hand, and reserved")
        for field in ("on_hand", "reserved"):
            value = data[field]
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or value < 0):
                raise ValueError(f"inventory {field} must be a finite nonnegative number")
        if data["reserved"] > data["on_hand"]:
            raise ValueError("inventory reservation exceeds stock on hand")
        expected = data["on_hand"] - data["reserved"]
        if "available" in data and data["available"] != expected:
            raise ValueError("inventory available must equal on_hand minus reserved")
        data["available"] = expected

    def upsert(
        self, *, record_type: str, record_id: str, source_system: str,
        source_revision: int, status: str, data: dict[str, Any],
        provenance: dict[str, Any], confidence: float, actor: str,
        correlation_id: str, occurred_at: str | None = None,
    ) -> BusinessWrite:
        if record_type not in RECORD_TYPES:
            raise ValueError("business record type is invalid")
        record_id = self._text(record_id, "record id")
        source_system = self._text(source_system, "source system", maximum=80)
        actor = self._text(actor, "actor", maximum=80)
        correlation_id = self._text(correlation_id, "correlation id", maximum=128)
        if type(source_revision) is not int or source_revision < 1:
            raise ValueError("business source revision must be a positive integer")
        if status not in RECORD_STATUSES:
            raise ValueError("business record status is invalid")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise ValueError("business confidence must be numeric")
        confidence = float(confidence)
        if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            raise ValueError("business confidence must be between zero and one")
        safe_data, _ = self._document(data, "data")
        if record_type == "inventory_position":
            self._validate_inventory(safe_data)
        safe_provenance, _ = self._document(provenance, "provenance")
        observed_at = utc_now()
        occurred_at = occurred_at or observed_at
        if not isinstance(occurred_at, str) or not occurred_at or len(occurred_at) > 64:
            raise ValueError("business occurrence time is invalid")
        payload = {
            "confidence": confidence,
            "data": safe_data,
            "provenance": safe_provenance,
            "status": status,
        }
        payload_encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        payload_hash = sha256(payload_encoded.encode()).hexdigest()

        with self._lock:
            existing_event = self.db.execute(
                "SELECT * FROM business_events WHERE source_system=? AND "
                "record_type=? AND record_id=? AND source_revision=?",
                (source_system, record_type, record_id, source_revision),
            ).fetchone()
            if existing_event is not None:
                if existing_event["payload_hash"] != payload_hash:
                    raise BusinessRevisionConflict(
                        "business source revision was reused with different content")
                record = self.get(record_type, record_id)
                return BusinessWrite(record, self._event_dict(existing_event), True)

            current = self.db.execute(
                "SELECT * FROM business_records WHERE record_type=? AND record_id=?",
                (record_type, record_id),
            ).fetchone()
            if current is not None and source_system == current["source_system"]:
                if source_revision <= current["source_revision"]:
                    raise BusinessRevisionConflict("business source revision is stale")
            version = 1 if current is None else int(current["version"]) + 1
            record_base = {
                "record_type": record_type,
                "record_id": record_id,
                "version": version,
                "source_system": source_system,
                "source_revision": source_revision,
                "status": status,
                "data": safe_data,
                "provenance": safe_provenance,
                "confidence": confidence,
                "observed_at": observed_at,
                "updated_at": observed_at,
            }
            record_hash = sha256(json.dumps(
                record_base, sort_keys=True, separators=(",", ":"),
                allow_nan=False).encode()).hexdigest()
            event_id = new_id("business_evt")
            owns_transaction = not self.db.in_transaction
            savepoint = "orca_business_upsert"
            if owns_transaction:
                self.db.execute("BEGIN IMMEDIATE")
            else:
                self.db.execute(f"SAVEPOINT {savepoint}")
            try:
                self.db.execute(
                    "INSERT INTO business_events(event_id,event_type,record_type,record_id,"
                    "source_system,source_revision,correlation_id,actor,occurred_at,observed_at,"
                    "payload,payload_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (event_id, "record.observed", record_type, record_id, source_system,
                     source_revision, correlation_id, actor, occurred_at, observed_at,
                     payload_encoded, payload_hash),
                )
                encoded_data = json.dumps(safe_data, sort_keys=True, separators=(",", ":"))
                encoded_provenance = json.dumps(
                    safe_provenance, sort_keys=True, separators=(",", ":"))
                self.db.execute(
                    "INSERT INTO business_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(record_type,record_id) DO UPDATE SET "
                    "version=excluded.version,source_system=excluded.source_system,"
                    "source_revision=excluded.source_revision,status=excluded.status,"
                    "data=excluded.data,provenance=excluded.provenance,"
                    "confidence=excluded.confidence,observed_at=excluded.observed_at,"
                    "updated_at=excluded.updated_at,record_hash=excluded.record_hash",
                    (record_type, record_id, version, source_system, source_revision,
                     status, encoded_data, encoded_provenance, confidence, observed_at,
                     observed_at, record_hash),
                )
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
            event = self.db.execute(
                "SELECT * FROM business_events WHERE event_id=?", (event_id,)).fetchone()
            return BusinessWrite(self.get(record_type, record_id), self._event_dict(event))

    def get(self, record_type: str, record_id: str) -> dict[str, Any]:
        with self._lock:
            row = self.db.execute(
                "SELECT * FROM business_records WHERE record_type=? AND record_id=?",
                (record_type, record_id),
            ).fetchone()
        if row is None:
            raise KeyError("business record is unknown")
        return self._record_dict(row)

    def snapshot(self, *, event_limit: int = 100) -> dict[str, Any]:
        if type(event_limit) is not int or not 0 <= event_limit <= 500:
            raise ValueError("business event limit is invalid")
        with self._lock:
            rows = self.db.execute(
                "SELECT * FROM business_records ORDER BY record_type, record_id").fetchall()
            events = self.db.execute(
                "SELECT * FROM business_events ORDER BY seq DESC LIMIT ?", (event_limit,)
            ).fetchall()
        records = [self._record_dict(row) for row in rows]
        counts = {record_type: 0 for record_type in sorted(RECORD_TYPES)}
        for record in records:
            counts[record["record_type"]] += 1
        return {
            "records": records,
            "events": [self._event_dict(row) for row in events],
            "counts": counts,
            "connector_claims": "not_inferred_from_source_names",
        }

    def verify(self) -> bool:
        """Verify hashes, projections, and append-only guards."""

        with self._lock:
            try:
                triggers = {
                    row[0] for row in self.db.execute(
                        "SELECT name FROM sqlite_master WHERE type='trigger' AND "
                        "name IN ('business_events_no_update','business_events_no_delete')")
                }
                if triggers != {"business_events_no_update", "business_events_no_delete"}:
                    return False
                for row in self.db.execute("SELECT * FROM business_events ORDER BY seq"):
                    if sha256(str(row["payload"]).encode()).hexdigest() != row["payload_hash"]:
                        return False
                    json.loads(row["payload"])
                for row in self.db.execute("SELECT * FROM business_records"):
                    base = {
                        "record_type": row["record_type"],
                        "record_id": row["record_id"],
                        "version": row["version"],
                        "source_system": row["source_system"],
                        "source_revision": row["source_revision"],
                        "status": row["status"],
                        "data": json.loads(row["data"]),
                        "provenance": json.loads(row["provenance"]),
                        "confidence": row["confidence"],
                        "observed_at": row["observed_at"],
                        "updated_at": row["updated_at"],
                    }
                    expected = sha256(json.dumps(
                        base, sort_keys=True, separators=(",", ":"),
                        allow_nan=False).encode()).hexdigest()
                    if expected != row["record_hash"]:
                        return False
            except (json.JSONDecodeError, TypeError, ValueError, sqlite3.DatabaseError):
                return False
        return True

    @staticmethod
    def _record_dict(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["data"] = json.loads(result["data"])
        result["provenance"] = json.loads(result["provenance"])
        return redact(result)

    @staticmethod
    def _event_dict(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["payload"] = json.loads(result["payload"])
        return redact(result)


def valid_record_hash(value: str) -> bool:
    return isinstance(value, str) and _HASH.fullmatch(value) is not None
