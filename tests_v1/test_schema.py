import sqlite3

import pytest

from orca.evidence import EvidenceStore
from orca.idempotency import IdempotencyStore
from orca.schema import (
    CURRENT_SCHEMA_VERSION,
    ensure_schema,
    mutation_receipt_digest,
    mutation_receipt_set_digest,
)
from orca.state import StateStore


def test_schema_version_is_initialized_and_exposed(tmp_path):
    store = EvidenceStore(tmp_path / "orca.db")
    assert store.schema_version == CURRENT_SCHEMA_VERSION
    assert store.db.execute("SELECT version FROM schema_meta").fetchone()[0] == CURRENT_SCHEMA_VERSION


def test_control_state_can_share_the_evidence_connection_lock(tmp_path):
    store = EvidenceStore(tmp_path / "locked.db")
    state = StateStore(store.db, connection_lock=store._lock)
    assert state._lock is store._lock
    assert state.verify_integrity() is True


def test_newer_database_schema_fails_closed(tmp_path):
    path = tmp_path / "future.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE schema_meta(singleton INTEGER PRIMARY KEY, version INTEGER NOT NULL)")
    db.execute("INSERT INTO schema_meta VALUES(1, ?)", (CURRENT_SCHEMA_VERSION + 1,))
    db.commit()
    db.close()
    with pytest.raises(RuntimeError, match="newer"):
        EvidenceStore(path)


def test_v1_snapshot_migrates_to_state_hash_and_evidence_binding(tmp_path):
    path = tmp_path / "v1.db"
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE schema_meta(singleton INTEGER PRIMARY KEY, version INTEGER NOT NULL)"
    )
    db.execute("INSERT INTO schema_meta VALUES(1, 1)")
    db.execute(
        "CREATE TABLE control_state(singleton INTEGER PRIMARY KEY, "
        "revision INTEGER NOT NULL, payload TEXT NOT NULL)"
    )
    db.execute("INSERT INTO control_state VALUES(1, 4, '{}')")
    db.commit()
    db.close()

    store = EvidenceStore(path)
    assert store.schema_version == CURRENT_SCHEMA_VERSION == 4
    columns = {
        row[1] for row in store.db.execute("PRAGMA table_info(control_state)")
    }
    assert {"state_hash", "evidence_head"} <= columns
    assert StateStore(store.db).load() == (4, {})


def test_v2_receipts_migrate_to_full_row_integrity_digests(tmp_path):
    path = tmp_path / "v2.db"
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE schema_meta(singleton INTEGER PRIMARY KEY, version INTEGER NOT NULL)"
    )
    db.execute("INSERT INTO schema_meta VALUES(1, 2)")
    db.execute(
        """CREATE TABLE mutation_receipts (
            idempotency_key TEXT PRIMARY KEY, actor TEXT NOT NULL,
            operation TEXT NOT NULL, request_hash TEXT NOT NULL,
            response TEXT NOT NULL, http_status INTEGER NOT NULL,
            state_revision INTEGER NOT NULL, created_at TEXT NOT NULL
        )"""
    )
    db.execute(
        "INSERT INTO mutation_receipts VALUES(?,?,?,?,?,?,?,?)",
        (
            "migration-request-0001", "orca", "POST /api/jobs", "a" * 64,
            '{"ok":true}', 200, 1, "2026-09-24T00:00:00+00:00",
        ),
    )
    db.execute(
        """CREATE TRIGGER mutation_receipts_no_update
           BEFORE UPDATE ON mutation_receipts BEGIN
               SELECT RAISE(ABORT, 'mutation receipts are append-only');
           END"""
    )
    db.commit()
    db.close()

    store = EvidenceStore(path)
    assert store.schema_version == CURRENT_SCHEMA_VERSION == 4
    columns = {
        row[1] for row in store.db.execute("PRAGMA table_info(mutation_receipts)")
    }
    assert "receipt_hash" in columns
    receipt_hash = store.db.execute(
        "SELECT receipt_hash FROM mutation_receipts"
    ).fetchone()[0]
    assert len(receipt_hash) == 64
    receipts = IdempotencyStore(store.db, connection_lock=store._lock)
    assert receipts.verify() is True
    assert receipts.lookup(
        key="migration-request-0001", actor="orca", operation="POST /api/jobs",
        request_hash="a" * 64,
    ).response == {"ok": True}
    anchor = store.db.execute(
        "SELECT receipt_count, receipt_set_hash FROM mutation_receipt_integrity"
    ).fetchone()
    assert anchor[0] == 1
    assert len(anchor[1]) == 64


def test_fresh_database_anchors_the_empty_receipt_set(tmp_path):
    store = EvidenceStore(tmp_path / "fresh.db")
    anchor = store.db.execute(
        "SELECT receipt_count, receipt_set_hash FROM mutation_receipt_integrity"
    ).fetchone()
    assert tuple(anchor) == (0, mutation_receipt_set_digest([]))
    assert IdempotencyStore(store.db, connection_lock=store._lock).verify() is True


def test_v3_database_adds_empty_set_anchor_without_rewriting_receipts(tmp_path):
    path = tmp_path / "v3.db"
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE schema_meta(singleton INTEGER PRIMARY KEY, version INTEGER NOT NULL)"
    )
    db.execute("INSERT INTO schema_meta VALUES(1, 3)")
    db.execute(
        """CREATE TABLE mutation_receipts (
            idempotency_key TEXT PRIMARY KEY, actor TEXT NOT NULL,
            operation TEXT NOT NULL, request_hash TEXT NOT NULL,
            response TEXT NOT NULL, http_status INTEGER NOT NULL,
            state_revision INTEGER NOT NULL, created_at TEXT NOT NULL,
            receipt_hash TEXT NOT NULL
        )"""
    )
    db.commit()

    assert ensure_schema(db) == CURRENT_SCHEMA_VERSION
    assert tuple(db.execute(
        "SELECT receipt_count, receipt_set_hash FROM mutation_receipt_integrity"
    ).fetchone()) == (0, mutation_receipt_set_digest([]))


def test_failed_v2_migration_rolls_back_all_ddl_and_trigger_changes(tmp_path):
    path = tmp_path / "v2-failure.db"
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE schema_meta(singleton INTEGER PRIMARY KEY, version INTEGER NOT NULL)"
    )
    db.execute("INSERT INTO schema_meta VALUES(1, 2)")
    db.execute(
        """CREATE TABLE mutation_receipts (
            idempotency_key TEXT PRIMARY KEY, actor TEXT NOT NULL,
            operation TEXT NOT NULL, request_hash TEXT NOT NULL,
            response TEXT NOT NULL, http_status INTEGER NOT NULL,
            state_revision INTEGER NOT NULL, created_at TEXT NOT NULL
        )"""
    )
    db.execute(
        "INSERT INTO mutation_receipts VALUES(?,?,?,?,?,?,?,?)",
        (
            "rollback-request-0001", "orca", "POST /api/jobs", "a" * 64,
            '{"ok":true}', "not-an-integer", 1,
            "2026-09-24T00:00:00+00:00",
        ),
    )
    for action in ("UPDATE", "DELETE"):
        db.execute(
            f"""CREATE TRIGGER mutation_receipts_no_{action.lower()}
                BEFORE {action} ON mutation_receipts BEGIN
                    SELECT RAISE(ABORT, 'mutation receipts are append-only');
                END"""
        )
    db.commit()

    with pytest.raises(RuntimeError, match="numeric fields"):
        ensure_schema(db)

    assert db.execute("SELECT version FROM schema_meta").fetchone()[0] == 2
    assert "receipt_hash" not in {
        row[1] for row in db.execute("PRAGMA table_info(mutation_receipts)")
    }
    triggers = {
        row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        )
    }
    assert {
        "mutation_receipts_no_update", "mutation_receipts_no_delete"
    } <= triggers


def test_v2_migration_never_rebaselines_an_existing_bad_receipt_hash(tmp_path):
    path = tmp_path / "v2-existing-hash.db"
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE schema_meta(singleton INTEGER PRIMARY KEY, version INTEGER NOT NULL)"
    )
    db.execute("INSERT INTO schema_meta VALUES(1, 2)")
    db.execute(
        """CREATE TABLE mutation_receipts (
            idempotency_key TEXT PRIMARY KEY, actor TEXT NOT NULL,
            operation TEXT NOT NULL, request_hash TEXT NOT NULL,
            response TEXT NOT NULL, http_status INTEGER NOT NULL,
            state_revision INTEGER NOT NULL, created_at TEXT NOT NULL,
            receipt_hash TEXT NOT NULL
        )"""
    )
    bad_hash = "0" * 64
    db.execute(
        "INSERT INTO mutation_receipts VALUES(?,?,?,?,?,?,?,?,?)",
        (
            "existing-hash-0001", "orca", "POST /api/jobs", "a" * 64,
            '{"ok":true}', 200, 1, "2026-09-24T00:00:00+00:00", bad_hash,
        ),
    )
    db.commit()

    with pytest.raises(RuntimeError, match="existing mutation receipt hash"):
        ensure_schema(db)
    assert db.execute("SELECT version FROM schema_meta").fetchone()[0] == 2
    assert db.execute(
        "SELECT receipt_hash FROM mutation_receipts"
    ).fetchone()[0] == bad_hash


@pytest.mark.parametrize("version", [3.9, 4.9])
def test_fractional_schema_versions_fail_closed(version):
    db = sqlite3.connect(":memory:")
    db.execute(
        "CREATE TABLE schema_meta(singleton INTEGER PRIMARY KEY, version INTEGER NOT NULL)"
    )
    db.execute("INSERT INTO schema_meta VALUES(1, ?)", (version,))
    db.commit()
    with pytest.raises(RuntimeError, match="schema version is invalid"):
        ensure_schema(db)
    stored_type, stored_version = db.execute(
        "SELECT typeof(version), version FROM schema_meta"
    ).fetchone()
    assert (stored_type, stored_version) == ("real", version)


@pytest.mark.parametrize(
    "table_name", ["mutation_receipts", "mutation_receipt_integrity"])
def test_current_v4_schema_requires_both_receipt_integrity_tables(
    tmp_path, table_name
):
    path = tmp_path / f"missing-{table_name}.db"
    store = EvidenceStore(path)
    store.db.execute(f"DROP TABLE {table_name}")
    store.db.commit()
    store.db.close()

    db = sqlite3.connect(path)
    with pytest.raises(RuntimeError, match="integrity tables are missing"):
        ensure_schema(db)
    assert db.execute("SELECT version FROM schema_meta").fetchone()[0] == 4


def test_fractional_receipt_count_fails_current_v4_validation(tmp_path):
    path = tmp_path / "fractional-anchor.db"
    store = EvidenceStore(path)
    store.db.execute(
        "UPDATE mutation_receipt_integrity SET receipt_count=0.9"
    )
    store.db.commit()
    store.db.close()

    db = sqlite3.connect(path)
    with pytest.raises(RuntimeError, match="integrity anchor is invalid"):
        ensure_schema(db)


def test_v3_migration_rejects_a_preexisting_mismatched_receipt_hash():
    db = sqlite3.connect(":memory:")
    db.execute(
        "CREATE TABLE schema_meta(singleton INTEGER PRIMARY KEY, "
        "version INTEGER NOT NULL)"
    )
    db.execute("INSERT INTO schema_meta VALUES(1, 3)")
    db.execute(
        """CREATE TABLE mutation_receipts (
            idempotency_key TEXT PRIMARY KEY, actor TEXT NOT NULL,
            operation TEXT NOT NULL, request_hash TEXT NOT NULL,
            response TEXT NOT NULL, http_status INTEGER NOT NULL,
            state_revision INTEGER NOT NULL, created_at TEXT NOT NULL,
            receipt_hash TEXT NOT NULL
        )"""
    )
    db.execute(
        "INSERT INTO mutation_receipts VALUES(?,?,?,?,?,?,?,?,?)",
        (
            "bad-v3-receipt-0001", "orca", "POST /api/test", "a" * 64,
            '{"ok":true}', 200, 0, "2026-09-24T00:00:00+00:00", "0" * 64,
        ),
    )
    db.commit()

    with pytest.raises(RuntimeError, match="integrity rows are invalid"):
        ensure_schema(db)

    assert db.execute("SELECT version FROM schema_meta").fetchone()[0] == 3
    assert db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='mutation_receipt_integrity'"
    ).fetchone() is None


def test_shape_inference_does_not_bless_a_partial_v3_receipt_hash():
    db = sqlite3.connect(":memory:")
    db.execute(
        """CREATE TABLE mutation_receipts (
            idempotency_key TEXT PRIMARY KEY, actor TEXT NOT NULL,
            operation TEXT NOT NULL, request_hash TEXT NOT NULL,
            response TEXT NOT NULL, http_status INTEGER NOT NULL,
            state_revision INTEGER NOT NULL, created_at TEXT NOT NULL,
            receipt_hash TEXT NOT NULL
        )"""
    )
    db.execute(
        "INSERT INTO mutation_receipts VALUES(?,?,?,?,?,?,?,?,?)",
        (
            "bad-inferred-v3-001", "orca", "POST /api/test", "a" * 64,
            '{"ok":true}', 200, 0, "2026-09-24T00:00:00+00:00", "f" * 64,
        ),
    )
    db.commit()

    with pytest.raises(RuntimeError, match="integrity rows are invalid"):
        ensure_schema(db)

    assert db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_meta'"
    ).fetchone() is None


def test_v4_rejects_exact_column_names_without_required_constraints():
    db = sqlite3.connect(":memory:")
    db.execute(
        "CREATE TABLE schema_meta(singleton INTEGER PRIMARY KEY, "
        "version INTEGER NOT NULL)"
    )
    db.execute("INSERT INTO schema_meta VALUES(1, 4)")
    db.execute(
        """CREATE TABLE mutation_receipts (
            idempotency_key TEXT, actor TEXT, operation TEXT, request_hash TEXT,
            response TEXT, http_status INTEGER, state_revision INTEGER,
            created_at TEXT, receipt_hash TEXT
        )"""
    )
    db.execute(
        """CREATE TABLE mutation_receipt_integrity (
            singleton INTEGER PRIMARY KEY, receipt_count INTEGER NOT NULL,
            receipt_set_hash TEXT NOT NULL
        )"""
    )
    db.execute(
        "INSERT INTO mutation_receipt_integrity VALUES(1,0,?)",
        (mutation_receipt_set_digest([]),),
    )
    db.commit()

    with pytest.raises(RuntimeError, match="schema migration is incomplete"):
        ensure_schema(db)


def test_schema_metadata_requires_exactly_one_singleton_row():
    db = sqlite3.connect(":memory:")
    # This is the supported legacy signature without the newer singleton CHECK,
    # so cardinality must still be verified independently of table shape.
    db.execute(
        "CREATE TABLE schema_meta(singleton INTEGER PRIMARY KEY, "
        "version INTEGER NOT NULL)"
    )
    db.executemany("INSERT INTO schema_meta VALUES(?,?)", [(1, 4), (2, 999)])
    db.commit()

    with pytest.raises(RuntimeError, match="schema version is invalid"):
        ensure_schema(db)


def test_current_schema_atomically_replaces_same_name_noop_receipt_guards(tmp_path):
    store = EvidenceStore(tmp_path / "noop-guards.db")
    for action in ("UPDATE", "DELETE"):
        name = f"mutation_receipts_no_{action.lower()}"
        store.db.execute(f"DROP TRIGGER {name}")
        store.db.execute(
            f"""CREATE TRIGGER {name} BEFORE {action} ON mutation_receipts
                BEGIN SELECT 1; END"""
        )
    store.db.commit()

    assert ensure_schema(store.db) == CURRENT_SCHEMA_VERSION
    trigger_sql = {
        row[0]: row[1]
        for row in store.db.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='trigger' "
            "AND name LIKE 'mutation_receipts_no_%'"
        )
    }
    assert set(trigger_sql) == {
        "mutation_receipts_no_update", "mutation_receipts_no_delete"
    }
    assert all("RAISE(ABORT" in sql for sql in trigger_sql.values())

    values = (
        "guard-probe-key-0001", "orca", "POST /api/test", "a" * 64,
        '{"ok":true}', 200, 0, "2026-09-24T00:00:00+00:00",
    )
    digest = mutation_receipt_digest(*values)
    store.db.execute(
        "INSERT INTO mutation_receipts VALUES(?,?,?,?,?,?,?,?,?)",
        (*values, digest),
    )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.db.execute("UPDATE mutation_receipts SET actor='smith'")
    store.db.rollback()
