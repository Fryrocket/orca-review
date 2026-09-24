from __future__ import annotations

from hashlib import sha256
import sqlite3
from threading import Event, Thread

import pytest

from orca import Action, ControlPlane
from orca.evidence import EvidenceStore
from orca.idempotency import IdempotencyConflict, IdempotencyStore
from orca.schema import mutation_receipt_digest, mutation_receipt_set_digest


def _hash(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def _submit(cp: ControlPlane, title: str = "idempotent read") -> tuple[dict, int]:
    job = cp.submit(
        title=title, lane="orca", requested_by="orca", assigned_to="smith",
        action=Action("read", "fixture"),
    )
    return cp._job_dict(job), 201


def test_idempotent_mutation_replays_after_restart_without_repeating_work(tmp_path):
    path = tmp_path / "orca.db"
    cp = ControlPlane(EvidenceStore(path))
    first, status, replayed, receipt_revision = cp.execute_idempotent(
        key="request-00000001", actor="orca", operation="POST /api/jobs",
        request_hash=_hash("request one"), expected_revision=0,
        mutation=lambda: _submit(cp),
    )
    assert status == 201
    assert replayed is False
    assert receipt_revision == cp.state_revision == 1
    assert cp.idempotency.count() == 1
    assert len(cp.jobs) == 1
    event_count = len(cp.evidence.list())

    restored = ControlPlane(EvidenceStore(path))
    second, second_status, replayed, replay_revision = restored.execute_idempotent(
        key="request-00000001", actor="orca", operation="POST /api/jobs",
        request_hash=_hash("request one"), expected_revision=0,
        mutation=lambda: _submit(restored, "must not run"),
    )
    assert (second, second_status, replayed) == (first, status, True)
    assert replay_revision == receipt_revision
    assert len(restored.jobs) == 1
    assert len(restored.evidence.list()) == event_count


def test_idempotency_key_reuse_with_different_request_fails_closed():
    cp = ControlPlane()
    cp.execute_idempotent(
        key="request-00000002", actor="orca", operation="POST /api/jobs",
        request_hash=_hash("first"), expected_revision=0,
        mutation=lambda: _submit(cp),
    )
    with pytest.raises(IdempotencyConflict, match="different mutation"):
        cp.execute_idempotent(
            key="request-00000002", actor="orca", operation="POST /api/jobs",
            request_hash=_hash("second"), expected_revision=1,
            mutation=lambda: _submit(cp, "must not run"),
        )
    assert len(cp.jobs) == 1


def test_new_request_requires_the_expected_state_revision():
    cp = ControlPlane()
    cp.submit(title="existing", lane="orca", requested_by="orca",
              assigned_to="smith", action=Action("read", "fixture"))
    with pytest.raises(RuntimeError, match="expected state revision is stale"):
        cp.execute_idempotent(
            key="request-00000003", actor="orca", operation="POST /api/jobs",
            request_hash=_hash("stale"), expected_revision=0,
            mutation=lambda: _submit(cp, "must not run"),
        )
    assert len(cp.jobs) == 1
    assert cp.idempotency.count() == 0


def test_mutation_and_receipt_roll_back_together_on_failure(tmp_path):
    cp = ControlPlane(EvidenceStore(tmp_path / "orca.db"))

    def fail_after_mutation():
        _submit(cp)
        raise RuntimeError("injected failure")

    with pytest.raises(RuntimeError, match="injected failure"):
        cp.execute_idempotent(
            key="request-00000004", actor="orca", operation="POST /api/jobs",
            request_hash=_hash("rollback"), expected_revision=0,
            mutation=fail_after_mutation,
        )
    assert cp.jobs == {}
    assert cp.evidence.list() == []
    assert cp.idempotency.count() == 0
    assert cp.state_revision == 0


def test_receipts_are_append_only_and_responses_are_redacted():
    cp = ControlPlane()
    secret = "sk-abcdefghijklmnop"
    response, _, _, _ = cp.execute_idempotent(
        key="request-00000005", actor="orca", operation="POST /api/test",
        request_hash=_hash("redaction"), expected_revision=0,
        mutation=lambda: ({"token": secret, "ok": True}, 200),
    )
    assert secret not in str(response)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        cp.evidence.db.execute("UPDATE mutation_receipts SET actor='fry'")
    cp.evidence.db.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        cp.evidence.db.execute("DELETE FROM mutation_receipts")
    cp.evidence.db.rollback()


def test_replay_never_bypasses_evidence_integrity_checks():
    cp = ControlPlane()
    cp.execute_idempotent(
        key="request-00000006", actor="orca", operation="POST /api/jobs",
        request_hash=_hash("tamper replay"), expected_revision=0,
        mutation=lambda: _submit(cp),
    )
    cp.evidence.db.execute("DROP TRIGGER events_no_update")
    cp.evidence.db.execute("UPDATE events SET payload='{}' WHERE seq=1")
    cp.evidence.db.commit()

    with pytest.raises(RuntimeError, match="evidence chain integrity"):
        cp.execute_idempotent(
            key="request-00000006", actor="orca", operation="POST /api/jobs",
            request_hash=_hash("tamper replay"), expected_revision=0,
            mutation=lambda: _submit(cp, "must not run"),
        )


def test_receipt_full_row_digest_detects_out_of_band_corruption():
    cp = ControlPlane()
    cp.execute_idempotent(
        key="request-00000007", actor="orca", operation="POST /api/test",
        request_hash=_hash("receipt tamper"), expected_revision=0,
        mutation=lambda: ({"ok": True}, 200),
    )
    cp.evidence.db.execute("DROP TRIGGER mutation_receipts_no_update")
    cp.evidence.db.execute(
        "UPDATE mutation_receipts SET response='{\"ok\":false}'")
    cp.evidence.db.commit()

    with pytest.raises(RuntimeError, match="stored idempotency receipt is invalid"):
        cp.idempotency.verify()


@pytest.mark.parametrize("deleted_key", ["first", "middle", "last", "all"])
def test_receipt_anchor_detects_out_of_band_row_omission(deleted_key):
    cp = ControlPlane()
    keys = [f"receipt-anchor-{number:04d}" for number in range(3)]
    for number, key in enumerate(keys):
        cp.execute_idempotent(
            key=key,
            actor="orca",
            operation="POST /api/test",
            request_hash=_hash(f"anchor {number}"),
            expected_revision=0,
            mutation=lambda number=number: ({"number": number}, 200),
        )
    cp.evidence.db.execute("DROP TRIGGER mutation_receipts_no_delete")
    if deleted_key == "all":
        cp.evidence.db.execute("DELETE FROM mutation_receipts")
    else:
        index = {"first": 0, "middle": 1, "last": 2}[deleted_key]
        cp.evidence.db.execute(
            "DELETE FROM mutation_receipts WHERE idempotency_key=?",
            (keys[index],),
        )
    cp.evidence.db.commit()

    with pytest.raises(RuntimeError, match="integrity anchor"):
        cp.idempotency.verify()
    with pytest.raises(RuntimeError, match="integrity anchor"):
        cp.idempotency.lookup(
            key=keys[0], actor="orca", operation="POST /api/test",
            request_hash=_hash("anchor 0"),
        )
    with pytest.raises(RuntimeError, match="integrity anchor"):
        cp.idempotency.count()


def test_receipt_anchor_detects_out_of_band_row_insertion():
    cp = ControlPlane()
    key = "out-of-band-insert-0001"
    actor = "orca"
    operation = "POST /api/test"
    request_hash = _hash("out-of-band insert")
    response = '{"ok":true}'
    created_at = "2026-09-24T00:00:00+00:00"
    receipt_hash = mutation_receipt_digest(
        key, actor, operation, request_hash, response, 200, 0, created_at)
    cp.evidence.db.execute(
        "INSERT INTO mutation_receipts VALUES(?,?,?,?,?,?,?,?,?)",
        (
            key, actor, operation, request_hash, response, 200, 0,
            created_at, receipt_hash,
        ),
    )
    cp.evidence.db.commit()

    with pytest.raises(RuntimeError, match="integrity anchor"):
        cp.idempotency.verify()
    with pytest.raises(RuntimeError, match="integrity anchor"):
        cp.idempotency.lookup(
            key=key, actor=actor, operation=operation,
            request_hash=request_hash,
        )


def test_fractional_receipt_count_fails_all_store_integrity_reads():
    cp = ControlPlane()
    key = "fractional-anchor-0001"
    request_hash = _hash("fractional anchor")
    cp.execute_idempotent(
        key=key, actor="orca", operation="POST /api/test",
        request_hash=request_hash, expected_revision=0,
        mutation=lambda: ({"ok": True}, 200),
    )
    cp.evidence.db.execute(
        "UPDATE mutation_receipt_integrity SET receipt_count=1.9"
    )
    cp.evidence.db.commit()

    with pytest.raises(RuntimeError, match="integrity anchor"):
        cp.idempotency.verify()
    with pytest.raises(RuntimeError, match="integrity anchor"):
        cp.idempotency.lookup(
            key=key, actor="orca", operation="POST /api/test",
            request_hash=request_hash,
        )
    with pytest.raises(RuntimeError, match="integrity anchor"):
        cp.idempotency.count()


def test_store_constructor_preserves_caller_transaction_ownership():
    store = EvidenceStore()
    store.db.execute("CREATE TABLE transaction_probe(value TEXT)")
    store.db.commit()
    store.db.execute("INSERT INTO transaction_probe VALUES('uncommitted')")
    assert store.db.in_transaction is True

    IdempotencyStore(store.db, connection_lock=store._lock)

    assert store.db.in_transaction is True
    store.db.rollback()
    assert store.db.execute(
        "SELECT COUNT(*) FROM transaction_probe"
    ).fetchone()[0] == 0


def test_record_failure_rolls_back_its_savepoint_inside_caller_transaction():
    store = EvidenceStore()
    receipts = IdempotencyStore(store.db, connection_lock=store._lock)
    store.db.execute(
        """CREATE TRIGGER fail_receipt_anchor
           BEFORE UPDATE ON mutation_receipt_integrity BEGIN
               SELECT RAISE(ABORT, 'injected anchor failure');
           END"""
    )
    store.db.execute("CREATE TABLE transaction_probe(value TEXT)")
    store.db.commit()
    store.db.execute("INSERT INTO transaction_probe VALUES('uncommitted')")

    with pytest.raises(sqlite3.IntegrityError, match="injected anchor failure"):
        receipts.record(
            key="nested-record-fail-001",
            actor="orca",
            operation="POST /api/test",
            request_hash=_hash("nested failure"),
            response={"ok": True},
            http_status=200,
            state_revision=0,
        )

    assert store.db.in_transaction is True
    assert store.db.execute(
        "SELECT COUNT(*) FROM mutation_receipts"
    ).fetchone()[0] == 0
    assert store.db.execute(
        "SELECT receipt_count FROM mutation_receipt_integrity"
    ).fetchone()[0] == 0
    store.db.rollback()
    assert store.db.execute(
        "SELECT COUNT(*) FROM transaction_probe"
    ).fetchone()[0] == 0


def test_integrity_reads_preserve_caller_transaction_ownership():
    store = EvidenceStore()
    receipts = IdempotencyStore(store.db, connection_lock=store._lock)
    store.db.execute("CREATE TABLE transaction_probe(value TEXT)")
    store.db.commit()
    store.db.execute("INSERT INTO transaction_probe VALUES('uncommitted')")

    assert receipts.count() == 0
    assert receipts.verify() is True
    assert store.db.in_transaction is True

    store.db.rollback()
    assert store.db.execute(
        "SELECT COUNT(*) FROM transaction_probe"
    ).fetchone()[0] == 0


@pytest.mark.parametrize("read_method", ["count", "verify"])
def test_integrity_read_uses_one_snapshot_during_a_valid_concurrent_append(
    tmp_path, read_method
):
    path = tmp_path / f"{read_method}-snapshot.db"
    reader_store = EvidenceStore(path)
    reader = IdempotencyStore(
        reader_store.db, connection_lock=reader_store._lock)
    writer_store = EvidenceStore(path)
    writer = IdempotencyStore(
        writer_store.db, connection_lock=writer_store._lock)
    start = Event()
    done = Event()
    failures: list[BaseException] = []

    def append_receipt():
        try:
            if not start.wait(5):
                raise RuntimeError("reader never reached the race point")
            writer.record(
                key="concurrent-count-0001",
                actor="orca",
                operation="POST /api/test",
                request_hash=_hash("concurrent count"),
                response={"ok": True},
                http_status=200,
                state_revision=0,
            )
        except BaseException as exc:  # surfaced in the owning test thread below
            failures.append(exc)
        finally:
            done.set()

    worker = Thread(target=append_receipt)
    worker.start()
    paused = False

    def pause_after_anchor_read(sql: str):
        nonlocal paused
        if (not paused
                and sql.startswith(
                    "SELECT COUNT(*) FROM mutation_receipt_integrity")):
            paused = True
            start.set()
            if not done.wait(5):
                failures.append(RuntimeError("concurrent append did not finish"))

    reader_store.db.set_trace_callback(pause_after_anchor_read)
    try:
        result = getattr(reader, read_method)()
        assert result == (0 if read_method == "count" else True)
    finally:
        reader_store.db.set_trace_callback(None)
        worker.join(timeout=5)
    assert not worker.is_alive()
    assert failures == []
    assert reader.count() == 1


def test_lookup_cannot_cross_from_verified_snapshot_to_unanchored_row(tmp_path):
    path = tmp_path / "lookup-snapshot.db"
    store = EvidenceStore(path)
    receipts = IdempotencyStore(store.db, connection_lock=store._lock)
    writer = sqlite3.connect(path, check_same_thread=False)
    writer.execute("PRAGMA busy_timeout=5000")
    start = Event()
    done = Event()
    failures: list[BaseException] = []
    key = "concurrent-forged-001"
    actor = "orca"
    operation = "POST /api/test"
    request_hash = _hash("concurrent forged receipt")
    encoded = '{"ok":true}'
    created_at = "2026-09-24T00:00:00+00:00"
    receipt_hash = mutation_receipt_digest(
        key, actor, operation, request_hash, encoded, 200, 0, created_at)

    def insert_without_anchor():
        try:
            if not start.wait(5):
                raise RuntimeError("reader never reached the race point")
            writer.execute(
                "INSERT INTO mutation_receipts VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    key, actor, operation, request_hash, encoded, 200, 0,
                    created_at, receipt_hash,
                ),
            )
            writer.commit()
        except BaseException as exc:  # surfaced in the owning test thread below
            failures.append(exc)
        finally:
            done.set()

    worker = Thread(target=insert_without_anchor)
    worker.start()
    paused = False

    def pause_before_receipt_lookup(sql: str):
        nonlocal paused
        if (not paused
                and sql.startswith(
                    "SELECT * FROM mutation_receipts WHERE idempotency_key=")):
            paused = True
            start.set()
            if not done.wait(5):
                failures.append(RuntimeError("concurrent insert did not finish"))

    store.db.set_trace_callback(pause_before_receipt_lookup)
    try:
        assert receipts.lookup(
            key=key,
            actor=actor,
            operation=operation,
            request_hash=request_hash,
        ) is None
    finally:
        store.db.set_trace_callback(None)
        worker.join(timeout=5)
        writer.close()
    assert not worker.is_alive()
    assert failures == []
    with pytest.raises(RuntimeError, match="integrity anchor"):
        receipts.count()


def test_receipt_text_fields_must_be_stored_as_sqlite_text():
    store = EvidenceStore()
    key = "blob-actor-receipt-01"
    raw_actor = b"orca"
    interpreted_actor = str(raw_actor)
    operation = "POST /api/test"
    request_hash = _hash("blob actor")
    encoded = '{"ok":true}'
    created_at = "2026-09-24T00:00:00+00:00"
    receipt_hash = mutation_receipt_digest(
        key, interpreted_actor, operation, request_hash, encoded,
        200, 0, created_at,
    )
    store.db.execute(
        "INSERT INTO mutation_receipts VALUES(?,?,?,?,?,?,?,?,?)",
        (
            key, sqlite3.Binary(raw_actor), operation, request_hash, encoded,
            200, 0, created_at, receipt_hash,
        ),
    )
    store.db.execute(
        "UPDATE mutation_receipt_integrity SET receipt_count=1, "
        "receipt_set_hash=?",
        (mutation_receipt_set_digest([(key, receipt_hash)]),),
    )
    store.db.commit()
    receipts = IdempotencyStore(store.db, connection_lock=store._lock)

    assert store.db.execute(
        "SELECT typeof(actor) FROM mutation_receipts"
    ).fetchone()[0] == "blob"
    with pytest.raises(RuntimeError, match="stored idempotency receipt is invalid"):
        receipts.verify()


@pytest.mark.parametrize(
    "table_name", ["mutation_receipts", "mutation_receipt_integrity"])
def test_missing_receipt_integrity_table_fails_startup(tmp_path, table_name):
    path = tmp_path / f"missing-{table_name}.db"
    cp = ControlPlane(EvidenceStore(path))
    cp.execute_idempotent(
        key="receipt-table-0001",
        actor="orca",
        operation="POST /api/test",
        request_hash=_hash("table omission"),
        expected_revision=0,
        mutation=lambda: ({"ok": True}, 200),
    )
    cp.evidence.db.execute(f"DROP TABLE {table_name}")
    cp.evidence.db.commit()
    cp.evidence.db.close()

    with pytest.raises(RuntimeError, match="integrity tables are missing"):
        ControlPlane(EvidenceStore(path))


@pytest.mark.parametrize("key", ["short", "space is not allowed", "x" * 129])
def test_idempotency_envelope_is_strict(key):
    cp = ControlPlane()
    with pytest.raises(ValueError, match="idempotency key"):
        cp.execute_idempotent(
            key=key, actor="orca", operation="POST /api/test",
            request_hash=_hash("invalid"), expected_revision=0,
            mutation=lambda: ({"ok": True}, 200),
        )
