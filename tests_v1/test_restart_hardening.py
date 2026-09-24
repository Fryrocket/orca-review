"""Process-style restart and durable-state failure-boundary tests."""

from __future__ import annotations

import sqlite3

import pytest

from orca import Action, ControlPlane
from orca.domain import JobStatus
from orca.evidence import EvidenceStore
from orca.fleet import Heartbeat, sign_heartbeat
from orca.schema import control_state_digest


def _open(path) -> ControlPlane:
    return ControlPlane(EvidenceStore(path))


def _close(control_plane: ControlPlane) -> None:
    """Close the sole durable handle to model a process exit, not a live reload."""
    control_plane.evidence.db.close()


def test_complete_mutable_state_survives_process_style_restart(tmp_path):
    path = tmp_path / "orca.db"
    cp = _open(path)

    anvil_key = b"restart-anvil-node-key-material-0001"
    cp.enroll_node("anvil", actor="fry", key=anvil_key)
    anvil_heartbeat = Heartbeat("anvil", 49_000, 1, "healthy", "restart fixture")
    cp.accept_heartbeat(
        anvil_heartbeat,
        signature=sign_heartbeat(anvil_heartbeat, anvil_key),
        key=anvil_key,
        now=49_000,
    )

    job = cp.submit(
        title="release restart fixture",
        lane="forge",
        requested_by="orca",
        assigned_to="smith",
        target_node="anvil",
        action=Action("deploy", "restart fixture", rollback="restore prior fixture"),
    )
    approval_id = job.approval_id
    assert approval_id is not None
    cp.decide(approval_id, actor="fry", approve=True, note="bounded fixture")
    cp.start_job(job.id, actor="smith")

    cp.set_bot_pause("smith", actor="orca", paused=True, reason="restart drill")
    cp.set_node_pause("anvil", actor="orca", paused=True, reason="restart drill")
    cp.set_lane_pause("forge", actor="orca", paused=True, reason="restart drill")
    cp.set_emergency_stop(actor="fry", active=True, reason="restart drill")
    assert job.status is JobStatus.PAUSED

    incident = cp.open_incident(
        severity="S2",
        title="restart fixture alert",
        lane="forge",
        owner="orca",
        detail="investigating",
    )
    cp.update_incident(
        incident.id, actor="smith", status="contained", detail="isolated"
    )

    report = cp.run_security_gate(
        author="smith",
        lane="forge",
        artifacts={"compose.yaml": "privileged: true"},
        requested_by="security_gate",
    )
    finding = report["findings"][0]
    adjudication = cp.review_security_finding(
        report_id=report["id"],
        fingerprint=finding["fingerprint"],
        actor="quench",
        verdict="confirmed",
        note="fixture reviewed independently",
    )
    exception = cp.record_security_exception(
        report_id=report["id"],
        fingerprint=finding["fingerprint"],
        actor="fry",
        reason="bounded restart fixture",
        duration_minutes=30,
    )

    cp.costs.record(
        job_id=job.id,
        bot_id="smith",
        lane="forge",
        model="local-fixture",
        tokens_in=13,
        tokens_out=8,
        cost_usd=0.0,
    )
    node_key = b"restart-fixture-node-key-32bytes!"
    assert len(node_key) >= 32
    cp.enroll_node("kiln", actor="fry", key=node_key)
    heartbeat = Heartbeat("kiln", 50_000, 19, "healthy", "restart fixture")
    cp.accept_heartbeat(
        heartbeat,
        signature=sign_heartbeat(heartbeat, node_key),
        key=node_key,
        now=50_000,
    )
    retention = cp.run_retention_audit(
        actor="orca", now="2035-01-01T00:00:00+00:00"
    )

    expected_revision = cp.state_revision
    expected_alerts = list(cp.alert_outbox)
    _close(cp)

    restored = _open(path)
    assert restored.state_revision == expected_revision
    assert restored.jobs[job.id].status is JobStatus.PAUSED
    assert restored.jobs[job.id].approval_id == approval_id
    assert restored.approvals[approval_id].status == "approved"
    assert restored.approvals[approval_id].decided_by == "fry"
    assert restored.bots.paused == {"smith"}
    assert restored.paused_nodes == {"anvil"}
    assert restored.paused_lanes == {"forge"}
    assert restored.emergency_stop is True
    assert restored.incidents[incident.id].status.value == "contained"
    assert restored.security_reports == [report]
    assert restored.security_adjudications == [adjudication]
    assert restored.security_exceptions == [exception]
    assert restored.retention_audits == [retention]
    assert restored.alert_outbox == expected_alerts
    assert restored.alert_outbox[0]["incident_id"] == incident.id
    assert restored.costs.summary()["budget_status"] == "zero_spend"
    assert restored.costs.summary()["total_usd"] == 0.0
    assert restored.costs.summary()["by_dimension"]["model"] == [
        {
            "key": "local-fixture",
            "tokens_in": 13,
            "tokens_out": 8,
            "cost_usd": 0.0,
        }
    ]
    assert restored.node_enrollments["kiln"]["last_nonce"] == 19
    assert restored.node_health["kiln"]["state"] == "healthy"
    assert restored.evidence.verify()

    # Releasing each durable boundary must not auto-resume the job. The explicit
    # resume must recover the approved pre-pause state and permit normal review.
    restored.set_emergency_stop(actor="fry", active=False, reason="drill complete")
    restored.set_bot_pause("smith", actor="orca", paused=False, reason="drill complete")
    restored.set_node_pause("anvil", actor="orca", paused=False, reason="drill complete")
    restored.set_lane_pause("forge", actor="orca", paused=False, reason="drill complete")
    assert restored.jobs[job.id].status is JobStatus.PAUSED
    restored.resume(job.id, actor="orca", reason="continue after verified restart")
    assert restored.jobs[job.id].status is JobStatus.READY
    restored.start_job(job.id, actor="smith")
    restored.submit_job_review(job.id, actor="smith", reviewer="quench")
    restored.complete_job(job.id, actor="quench", note="restart path verified")
    assert restored.jobs[job.id].status is JobStatus.COMPLETE
    _close(restored)

    completed = _open(path)
    assert completed.jobs[job.id].status is JobStatus.COMPLETE
    assert completed.approvals[approval_id].status == "approved"
    assert completed.emergency_stop is False
    _close(completed)


def test_pending_approval_is_reconstructed_after_restart_and_cannot_be_bypassed(tmp_path):
    path = tmp_path / "pending.db"
    cp = _open(path)
    cp.set_emergency_stop(actor="fry", active=True, reason="approval restart fixture")
    job = cp.submit(
        title="pending restart fixture",
        lane="orca",
        requested_by="orca",
        assigned_to="smith",
        action=Action("push", "fixture", rollback="revert fixture"),
    )
    approval_id = job.approval_id
    assert approval_id is not None
    assert job.status is JobStatus.PAUSED
    _close(cp)

    restored = _open(path)
    assert restored.approvals[approval_id].status == "pending"
    restored.set_emergency_stop(actor="fry", active=False, reason="fixture released")
    restored.resume(job.id, actor="orca", reason="return to approval gate")
    assert restored.jobs[job.id].status is JobStatus.WAITING_APPROVAL
    with pytest.raises(ValueError, match="not ready"):
        restored.start_job(job.id, actor="smith")
    restored.decide(approval_id, actor="fry", approve=False, note="fixture denied")
    _close(restored)

    denied = _open(path)
    assert denied.jobs[job.id].status is JobStatus.DENIED
    assert denied.approvals[approval_id].status == "denied"
    with pytest.raises(ValueError, match="terminal"):
        denied.pause(job.id, actor="orca", reason="must remain terminal")
    _close(denied)


def test_heartbeat_nonce_replay_boundary_survives_each_restart(tmp_path):
    path = tmp_path / "fleet.db"
    key = b"durable-heartbeat-key-material-0001"
    cp = _open(path)
    cp.enroll_node("ember", actor="fry", key=key)
    first = Heartbeat("ember", 10_000, 41, "healthy", "first")
    first_signature = sign_heartbeat(first, key)
    cp.accept_heartbeat(first, signature=first_signature, key=key, now=10_000)
    _close(cp)

    restored = _open(path)
    with pytest.raises(PermissionError, match="replay"):
        restored.accept_heartbeat(
            first, signature=first_signature, key=key, now=10_000
        )
    second = Heartbeat("ember", 10_001, 42, "degraded", "second")
    restored.accept_heartbeat(
        second, signature=sign_heartbeat(second, key), key=key, now=10_001
    )
    _close(restored)

    final = _open(path)
    assert final.node_enrollments["ember"]["last_nonce"] == 42
    assert final.node_enrollments["ember"]["last_seen_epoch"] == 10_001
    assert final.node_health["ember"]["state"] == "degraded"
    assert "ember" in final.paused_nodes
    _close(final)


def test_stale_instance_rolls_back_memory_and_cannot_append_or_overwrite(tmp_path):
    path = tmp_path / "stale.db"
    current = _open(path)
    stale = _open(path)

    durable_job = current.submit(
        title="durable writer",
        lane="orca",
        requested_by="orca",
        assigned_to="smith",
        action=Action("read", "fixture"),
    )
    revision = current.state_revision
    event_count = len(current.evidence.list(limit=100))

    with pytest.raises(RuntimeError, match="stale control-plane"):
        stale.submit(
            title="stale writer",
            lane="orca",
            requested_by="orca",
            assigned_to="smith",
            action=Action("read", "fixture"),
        )

    assert stale.jobs == {}
    assert stale.approvals == {}
    assert stale.state_revision == 0
    assert len(current.evidence.list(limit=100)) == event_count
    assert current.state_store.current_revision() == revision
    _close(stale)
    _close(current)

    restored = _open(path)
    assert set(restored.jobs) == {durable_job.id}
    assert restored.state_revision == revision
    assert restored.evidence.verify()
    _close(restored)


def test_valid_evidence_extension_without_state_checkpoint_blocks_restart(tmp_path):
    """A valid later event must not leave an older snapshot looking current."""
    path = tmp_path / "old-evidence-head.db"
    cp = _open(path)
    job = cp.submit(
        title="evidence head fixture",
        lane="orca",
        requested_by="orca",
        assigned_to="smith",
        action=Action("read", "fixture"),
    )
    saved_head = cp.evidence.db.execute(
        "SELECT evidence_head FROM control_state WHERE singleton=1"
    ).fetchone()[0]
    event = cp.evidence.append(
        correlation_id=job.correlation_id,
        actor="orca",
        lane="orca",
        kind="fixture.uncheckpointed",
        payload={"job_id": job.id},
    )
    assert cp.evidence.verify()
    assert event.previous_hash == saved_head
    _close(cp)

    with pytest.raises(RuntimeError, match="does not match current evidence chain head"):
        _open(path)


def test_evidence_without_any_control_snapshot_blocks_startup(tmp_path):
    path = tmp_path / "evidence-without-state.db"
    store = EvidenceStore(path)
    store.append(
        correlation_id="fixture",
        actor="orca",
        lane="orca",
        kind="fixture.orphaned",
        payload={"ok": True},
    )
    store.db.close()

    with pytest.raises(RuntimeError, match="control state is missing"):
        _open(path)


def test_duplicate_incident_event_checkpoints_current_evidence_head(tmp_path):
    path = tmp_path / "duplicate-incident-head.db"
    cp = _open(path)
    first = cp.open_incident(
        severity="S2", title="Forge offline", lane="forge", owner="orca"
    )
    previous_revision = cp.state_revision

    duplicate = cp.open_incident(
        severity="S3", title="  forge OFFLINE  ", lane="forge", owner="fry"
    )

    assert duplicate.id == first.id
    assert cp.state_revision == previous_revision + 1
    saved_head = cp.evidence.db.execute(
        "SELECT evidence_head FROM control_state WHERE singleton=1"
    ).fetchone()[0]
    current_head = cp.evidence.db.execute(
        "SELECT event_hash FROM events ORDER BY seq DESC LIMIT 1"
    ).fetchone()[0]
    assert saved_head == current_head
    _close(cp)

    restored = _open(path)
    assert set(restored.incidents) == {first.id}
    assert restored.evidence.list(limit=1)[0]["kind"] == "incident.deduplicated"
    _close(restored)


def test_connector_read_preparation_checkpoints_current_evidence_head(tmp_path):
    path = tmp_path / "connector-read-head.db"
    cp = _open(path)
    cp.submit(
        title="establish snapshot",
        lane="orca",
        requested_by="orca",
        assigned_to="smith",
        action=Action("read", "fixture"),
    )
    previous_revision = cp.state_revision

    prepared = cp.prepare_connector_read(
        actor="orca", connector="gitea", operation="read", resource="repos/fry/orca"
    )

    assert prepared["connector"] == "gitea"
    assert cp.state_revision == previous_revision + 1
    saved_head = cp.evidence.db.execute(
        "SELECT evidence_head FROM control_state WHERE singleton=1"
    ).fetchone()[0]
    current_head = cp.evidence.db.execute(
        "SELECT event_hash FROM events ORDER BY seq DESC LIMIT 1"
    ).fetchone()[0]
    assert saved_head == current_head
    _close(cp)

    restored = _open(path)
    assert restored.evidence.list(limit=1)[0]["kind"] == "connector.read_prepared"
    _close(restored)


@pytest.mark.parametrize("column", ["payload", "state_hash"])
def test_control_snapshot_hash_corruption_blocks_restart(tmp_path, column):
    path = tmp_path / f"corrupt-{column}.db"
    cp = _open(path)
    cp.submit(
        title="corruption fixture",
        lane="orca",
        requested_by="orca",
        assigned_to="smith",
        action=Action("read", "fixture"),
    )
    _close(cp)

    db = sqlite3.connect(path)
    if column == "payload":
        db.execute("UPDATE control_state SET payload='{}' WHERE singleton=1")
    else:
        db.execute("UPDATE control_state SET state_hash=? WHERE singleton=1", ("0" * 64,))
    db.commit()
    db.close()

    with pytest.raises(RuntimeError, match="control state integrity"):
        _open(path)


def test_validly_hashed_malformed_json_snapshot_blocks_restart(tmp_path):
    path = tmp_path / "malformed-json.db"
    cp = _open(path)
    cp.submit(
        title="malformed fixture",
        lane="orca",
        requested_by="orca",
        assigned_to="smith",
        action=Action("read", "fixture"),
    )
    _close(cp)

    db = sqlite3.connect(path)
    revision, evidence_head = db.execute(
        "SELECT revision, evidence_head FROM control_state WHERE singleton=1"
    ).fetchone()
    malformed = "[not-json"
    db.execute(
        "UPDATE control_state SET payload=?, state_hash=? WHERE singleton=1",
        (malformed, control_state_digest(revision, malformed, evidence_head)),
    )
    db.commit()
    db.close()

    with pytest.raises(RuntimeError, match="control state integrity"):
        _open(path)


def test_snapshot_reference_to_missing_evidence_blocks_restart(tmp_path):
    path = tmp_path / "missing-evidence.db"
    cp = _open(path)
    cp.submit(
        title="evidence reference fixture",
        lane="orca",
        requested_by="orca",
        assigned_to="smith",
        action=Action("read", "fixture"),
    )
    _close(cp)

    db = sqlite3.connect(path)
    db.execute("DROP TRIGGER events_no_delete")
    db.execute("DELETE FROM events")
    db.commit()
    db.close()

    with pytest.raises(RuntimeError, match="evidence reference is missing"):
        _open(path)
