from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
from hmac import compare_digest
import json
import sqlite3
from typing import Callable, Iterator


CURRENT_SCHEMA_VERSION = 4
_SCHEMA_META_SIGNATURE = (
    ("singleton", "INTEGER", 0, 1),
    ("version", "INTEGER", 1, 0),
)
_RECEIPT_V2_SIGNATURE = (
    ("idempotency_key", "TEXT", 0, 1),
    ("actor", "TEXT", 1, 0),
    ("operation", "TEXT", 1, 0),
    ("request_hash", "TEXT", 1, 0),
    ("response", "TEXT", 1, 0),
    ("http_status", "INTEGER", 1, 0),
    ("state_revision", "INTEGER", 1, 0),
    ("created_at", "TEXT", 1, 0),
)
_RECEIPT_V4_SIGNATURE = _RECEIPT_V2_SIGNATURE + (
    ("receipt_hash", "TEXT", 1, 0),
)
_RECEIPT_INTEGRITY_SIGNATURE = (
    ("singleton", "INTEGER", 0, 1),
    ("receipt_count", "INTEGER", 1, 0),
    ("receipt_set_hash", "TEXT", 1, 0),
)
_RECEIPT_GUARD_SQL = {
    "mutation_receipts_no_update":
        """CREATE TRIGGER mutation_receipts_no_update
           BEFORE UPDATE ON mutation_receipts BEGIN
               SELECT RAISE(ABORT, 'mutation receipts are append-only');
           END""",
    "mutation_receipts_no_delete":
        """CREATE TRIGGER mutation_receipts_no_delete
           BEFORE DELETE ON mutation_receipts BEGIN
               SELECT RAISE(ABORT, 'mutation receipts are append-only');
           END""",
}


def control_state_digest(revision: int, payload: str, evidence_head: str) -> str:
    """Bind one serialized control snapshot to its evidence-chain position."""
    encoded = json.dumps(
        {"evidence_head": evidence_head, "payload": payload, "revision": revision},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def mutation_receipt_digest(
    idempotency_key: str,
    actor: str,
    operation: str,
    request_hash: str,
    response: str,
    http_status: int,
    state_revision: int,
    created_at: str,
) -> str:
    """Digest every durable field in an idempotency receipt."""

    encoded = json.dumps(
        {
            "actor": actor,
            "created_at": created_at,
            "http_status": http_status,
            "idempotency_key": idempotency_key,
            "operation": operation,
            "request_hash": request_hash,
            "response": response,
            "state_revision": state_revision,
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def mutation_receipt_set_digest(rows: list[tuple[str, str]]) -> str:
    """Digest the complete ordered receipt-key/hash set, including emptiness."""

    encoded = json.dumps(
        sorted(rows),
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return sha256(b"orca-mutation-receipt-set-v1\x00" + encoded).hexdigest()


def _table_exists(db: sqlite3.Connection, name: str) -> bool:
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _table_signature(
    db: sqlite3.Connection, name: str
) -> tuple[tuple[str, str, int, int], ...]:
    return tuple(
        (str(row[1]), str(row[2]).upper(), int(row[3]), int(row[5]))
        for row in db.execute(f"PRAGMA table_info({name})")
    )


def _require_table_signature(
    db: sqlite3.Connection,
    name: str,
    expected: tuple[tuple[str, str, int, int], ...],
    error: str,
) -> None:
    if not _table_exists(db, name) or _table_signature(db, name) != expected:
        raise RuntimeError(error)


def validate_receipt_schema(db: sqlite3.Connection) -> None:
    """Require the exact durable receipt structures, not merely column names."""

    _require_table_signature(
        db, "mutation_receipts", _RECEIPT_V4_SIGNATURE,
        "mutation receipt schema migration is incomplete",
    )
    _require_table_signature(
        db, "mutation_receipt_integrity", _RECEIPT_INTEGRITY_SIGNATURE,
        "mutation receipt schema migration is incomplete",
    )


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _receipt_hash_rows(db: sqlite3.Connection) -> list[tuple[str, str]]:
    rows = db.execute(
        "SELECT idempotency_key, actor, operation, request_hash, response, "
        "http_status, state_revision, created_at, receipt_hash "
        "FROM mutation_receipts "
        "ORDER BY idempotency_key"
    ).fetchall()
    result: list[tuple[str, str]] = []
    for row in rows:
        if (any(not isinstance(row[index], str)
                for index in (0, 1, 2, 3, 4, 7, 8))
                or type(row[5]) is not int or type(row[6]) is not int):
            raise RuntimeError("mutation receipt integrity rows are invalid")
        expected_hash = mutation_receipt_digest(
            row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7])
        if (not _is_digest(row[8])
                or not compare_digest(row[8], expected_hash)):
            raise RuntimeError("mutation receipt integrity rows are invalid")
        result.append((row[0], row[8]))
    return result


def _normalize_sql(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.rstrip(";").split()).casefold()


def validate_receipt_guards(db: sqlite3.Connection) -> None:
    rows = db.execute(
        "SELECT name, tbl_name, sql FROM sqlite_master "
        "WHERE type='trigger' AND name IN "
        "('mutation_receipts_no_update','mutation_receipts_no_delete')"
    ).fetchall()
    actual = {
        str(row[0]): (str(row[1]), _normalize_sql(row[2])) for row in rows
    }
    expected = {
        name: ("mutation_receipts", _normalize_sql(sql))
        for name, sql in _RECEIPT_GUARD_SQL.items()
    }
    if actual != expected:
        raise RuntimeError("mutation receipt append-only guards are invalid")


def replace_receipt_guards(db: sqlite3.Connection) -> None:
    """Atomically replace same-name no-op or otherwise malformed guards."""

    with _schema_transaction(db):
        for name in _RECEIPT_GUARD_SQL:
            db.execute(f"DROP TRIGGER IF EXISTS {name}")
        for statement in _RECEIPT_GUARD_SQL.values():
            db.execute(statement)
        validate_receipt_guards(db)


def ensure_receipt_guards(db: sqlite3.Connection) -> None:
    """Keep valid guards intact and replace missing or malformed definitions."""

    try:
        validate_receipt_guards(db)
    except RuntimeError:
        replace_receipt_guards(db)


def _validate_v4_schema(db: sqlite3.Connection) -> None:
    tables = {
        str(row[0])
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND "
            "name IN ('mutation_receipts','mutation_receipt_integrity')"
        )
    }
    if tables != {"mutation_receipts", "mutation_receipt_integrity"}:
        raise RuntimeError("mutation receipt integrity tables are missing")
    validate_receipt_schema(db)

    anchors = db.execute(
        "SELECT singleton, receipt_count, receipt_set_hash "
        "FROM mutation_receipt_integrity"
    ).fetchall()
    rows = _receipt_hash_rows(db)
    if len(anchors) != 1:
        raise RuntimeError("mutation receipt integrity anchor is invalid")
    singleton, receipt_count, receipt_set_hash = anchors[0]
    expected_hash = mutation_receipt_set_digest(rows)
    if (type(singleton) is not int or singleton != 1
            or type(receipt_count) is not int or receipt_count != len(rows)
            or not _is_digest(receipt_set_hash)
            or not compare_digest(receipt_set_hash, expected_hash)):
        raise RuntimeError("mutation receipt integrity anchor is invalid")


@contextmanager
def _schema_transaction(db: sqlite3.Connection) -> Iterator[None]:
    """Make every schema change, including DDL, one atomic unit."""

    owns_transaction = not db.in_transaction
    savepoint = "orca_schema_migration_guard"
    if owns_transaction:
        db.execute("BEGIN IMMEDIATE")
    else:
        db.execute(f"SAVEPOINT {savepoint}")
    try:
        yield
    except BaseException:
        if owns_transaction:
            db.rollback()
        else:
            db.execute(f"ROLLBACK TO {savepoint}")
            db.execute(f"RELEASE {savepoint}")
        raise
    else:
        if owns_transaction:
            db.commit()
        else:
            db.execute(f"RELEASE {savepoint}")


def _migration_2(db: sqlite3.Connection) -> None:
    if not _table_exists(db, "control_state"):
        return
    columns = {str(row[1]) for row in db.execute("PRAGMA table_info(control_state)")}
    if "state_hash" not in columns:
        db.execute(
            "ALTER TABLE control_state ADD COLUMN state_hash TEXT NOT NULL DEFAULT ''"
        )
    if "evidence_head" not in columns:
        db.execute(
            "ALTER TABLE control_state ADD COLUMN evidence_head TEXT NOT NULL DEFAULT 'GENESIS'"
        )
    row = db.execute(
        "SELECT revision, payload FROM control_state WHERE singleton=1"
    ).fetchone()
    if row is None:
        return
    evidence_head = "GENESIS"
    if _table_exists(db, "events"):
        event = db.execute(
            "SELECT event_hash FROM events ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        if event is not None:
            evidence_head = str(event[0])
    revision, payload = int(row[0]), str(row[1])
    db.execute(
        "UPDATE control_state SET state_hash=?, evidence_head=? WHERE singleton=1",
        (control_state_digest(revision, payload, evidence_head), evidence_head),
    )


def _create_receipt_guards(db: sqlite3.Connection) -> None:
    replace_receipt_guards(db)


def _migration_3(db: sqlite3.Connection) -> None:
    db.execute("DROP TRIGGER IF EXISTS mutation_receipts_no_update")
    db.execute("DROP TRIGGER IF EXISTS mutation_receipts_no_delete")
    if not _table_exists(db, "mutation_receipts"):
        db.execute(
            """CREATE TABLE mutation_receipts (
                idempotency_key TEXT PRIMARY KEY,
                actor TEXT NOT NULL,
                operation TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                response TEXT NOT NULL,
                http_status INTEGER NOT NULL,
                state_revision INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                receipt_hash TEXT NOT NULL
            )"""
        )
    else:
        columns = {
            str(row[1]) for row in db.execute("PRAGMA table_info(mutation_receipts)")
        }
        hash_already_present = "receipt_hash" in columns
        _require_table_signature(
            db,
            "mutation_receipts",
            _RECEIPT_V4_SIGNATURE if hash_already_present else _RECEIPT_V2_SIGNATURE,
            "mutation receipt schema migration is incomplete",
        )
        if not hash_already_present:
            db.execute(
                "ALTER TABLE mutation_receipts "
                "ADD COLUMN receipt_hash TEXT NOT NULL DEFAULT ''"
            )
        rows = db.execute(
            "SELECT idempotency_key, actor, operation, request_hash, response, "
            "http_status, state_revision, created_at, receipt_hash "
            "FROM mutation_receipts"
        ).fetchall()
        for row in rows:
            if type(row[5]) is not int or type(row[6]) is not int:
                raise RuntimeError("legacy mutation receipt numeric fields are invalid")
            if any(not isinstance(row[index], str)
                   for index in (0, 1, 2, 3, 4, 7)):
                raise RuntimeError("legacy mutation receipt field types are invalid")
            values = tuple(row[:8])
            expected_hash = mutation_receipt_digest(*values)
            if hash_already_present:
                stored_hash = row[8]
                if (not _is_digest(stored_hash)
                        or not compare_digest(stored_hash, expected_hash)):
                    raise RuntimeError(
                        "existing mutation receipt hash is invalid")
            else:
                db.execute(
                    "UPDATE mutation_receipts SET receipt_hash=? "
                    "WHERE idempotency_key=?",
                    (expected_hash, values[0]),
                )
        _receipt_hash_rows(db)
    _create_receipt_guards(db)


def _migration_4(db: sqlite3.Connection) -> None:
    """Anchor receipt presence so omitted rows and tables fail closed."""

    if not _table_exists(db, "mutation_receipts"):
        raise RuntimeError("mutation receipt table is missing")
    _require_table_signature(
        db, "mutation_receipts", _RECEIPT_V4_SIGNATURE,
        "mutation receipt schema migration is incomplete",
    )
    rows = _receipt_hash_rows(db)
    db.execute(
        """CREATE TABLE IF NOT EXISTS mutation_receipt_integrity (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1),
            receipt_count INTEGER NOT NULL CHECK(receipt_count >= 0),
            receipt_set_hash TEXT NOT NULL
        )"""
    )
    _require_table_signature(
        db, "mutation_receipt_integrity", _RECEIPT_INTEGRITY_SIGNATURE,
        "mutation receipt schema migration is incomplete",
    )
    anchors = db.execute(
        "SELECT singleton, receipt_count, receipt_set_hash "
        "FROM mutation_receipt_integrity"
    ).fetchall()
    expected = (len(rows), mutation_receipt_set_digest(rows))
    if not anchors:
        db.execute(
            "INSERT INTO mutation_receipt_integrity VALUES(1, ?, ?)", expected)
    elif (len(anchors) != 1
            or type(anchors[0][0]) is not int or anchors[0][0] != 1
            or type(anchors[0][1]) is not int
            or not isinstance(anchors[0][2], str)
            or (anchors[0][1], anchors[0][2]) != expected):
        raise RuntimeError("mutation receipt integrity anchor is invalid")
    _validate_v4_schema(db)


MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    2: _migration_2,
    3: _migration_3,
    4: _migration_4,
}


def ensure_schema(db: sqlite3.Connection) -> int:
    with _schema_transaction(db):
        db.execute(
            """CREATE TABLE IF NOT EXISTS schema_meta (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                version INTEGER NOT NULL
            )"""
        )
        _require_table_signature(
            db, "schema_meta", _SCHEMA_META_SIGNATURE,
            "database schema metadata is invalid",
        )
        metadata = db.execute(
            "SELECT singleton, version FROM schema_meta").fetchall()
        if not metadata:
            is_fresh = not any(
                _table_exists(db, name)
                for name in ("control_state", "events", "mutation_receipts")
            )
            if is_fresh:
                _migration_3(db)
                _migration_4(db)
                db.execute(
                    "INSERT INTO schema_meta VALUES(1, ?)",
                    (CURRENT_SCHEMA_VERSION,),
                )
                version = CURRENT_SCHEMA_VERSION
            else:
                version = CURRENT_SCHEMA_VERSION
                if _table_exists(db, "control_state"):
                    columns = {
                        str(item[1])
                        for item in db.execute("PRAGMA table_info(control_state)")
                    }
                    if "state_hash" not in columns or "evidence_head" not in columns:
                        version = 1
                    elif not _table_exists(db, "mutation_receipts"):
                        version = min(version, 2)
                if _table_exists(db, "mutation_receipts"):
                    receipt_columns = {
                        str(item[1])
                        for item in db.execute("PRAGMA table_info(mutation_receipts)")
                    }
                    if "receipt_hash" not in receipt_columns:
                        version = min(version, 2)
                    else:
                        version = min(version, 3)
                elif _table_exists(db, "events"):
                    version = min(version, 1)
                db.execute("INSERT INTO schema_meta VALUES(1, ?)", (version,))
        else:
            if (len(metadata) != 1 or type(metadata[0][0]) is not int
                    or metadata[0][0] != 1
                    or type(metadata[0][1]) is not int):
                raise RuntimeError("database schema version is invalid")
            version = metadata[0][1]
        if version > CURRENT_SCHEMA_VERSION:
            raise RuntimeError("database schema is newer than this ORCA build")
        while version < CURRENT_SCHEMA_VERSION:
            target = version + 1
            migration = MIGRATIONS.get(target)
            if migration is None:
                raise RuntimeError(f"missing database migration to version {target}")
            migration(db)
            db.execute("UPDATE schema_meta SET version=? WHERE singleton=1", (target,))
            version = target
        _validate_v4_schema(db)
        ensure_receipt_guards(db)
        validate_receipt_guards(db)
        return version
