import pytest
import sqlite3
import json
from concurrent.futures import ThreadPoolExecutor

from orca import Action, ControlPlane, PermissionLevel
from orca.domain import JobStatus
from orca.evidence import EvidenceStore
from orca.fleet import Heartbeat, sign_heartbeat
from orca.policy import PolicyEngine, PolicyViolation
from orca.registry import AGENTS
from orca.governance import RetentionGuard, RetentionRecord


def test_r0_read_is_ready_without_approval():
    cp = ControlPlane()
    job = cp.submit(title="inspect repo", lane="forge", requested_by="orca",
                    assigned_to="smith", action=Action("read", "repo"))
    assert job.level is PermissionLevel.R0
    assert job.status is JobStatus.READY


def test_reversible_change_with_rollback_is_r1_but_missing_rollback_is_r2():
    policy = PolicyEngine()
    safe = policy.classify(Action("edit", "config", rollback="restore prior file"))
    unsafe = policy.classify(Action("edit", "config"))
    assert safe.level is PermissionLevel.R1
    assert not safe.requires_approval
    assert unsafe.level is PermissionLevel.R2
    assert unsafe.requires_approval


def test_r3_delete_waits_for_fry():
    cp = ControlPlane()
    job = cp.submit(title="remove legacy", lane="orca", requested_by="orca",
                    assigned_to="smith", action=Action(
                        "delete", "legacy", destructive=True, reversible=False))
    assert job.level is PermissionLevel.R3
    assert job.status is JobStatus.WAITING_APPROVAL
    with pytest.raises(PermissionError):
        cp.decide(job.approval_id, actor="orca", approve=True)
    cp.decide(job.approval_id, actor="fry", approve=True, note="cutover approved")
    assert job.status is JobStatus.READY


def test_secret_spend_publication_physical_and_body_are_r3():
    policy = PolicyEngine()
    flags = ("touches_secrets", "spends_money", "publishes", "physical", "body_impact")
    for flag in flags:
        assert policy.classify(Action("change", "x", **{flag: True})).level is PermissionLevel.R3


@pytest.mark.parametrize(("action", "expected"), [
    (Action("read", "x"), PermissionLevel.R0),
    (Action("observe", "x"), PermissionLevel.R0),
    (Action("analyze", "x"), PermissionLevel.R0),
    (Action("edit", "x", rollback="revert"), PermissionLevel.R1),
    (Action("edit", "x"), PermissionLevel.R2),
    (Action("merge", "x", rollback="revert merge"), PermissionLevel.R3),
    (Action("push", "x", rollback="revert push"), PermissionLevel.R3),
    (Action("deploy", "x", rollback="restore release"), PermissionLevel.R3),
    (Action("restore", "x", rollback="restore prior snapshot"), PermissionLevel.R2),
    (Action("grant", "x", rollback="revoke grant"), PermissionLevel.R2),
    (Action("connector_write", "x", rollback="restore provider state"), PermissionLevel.R2),
    (Action("read", "production", production=True), PermissionLevel.R3),
    (Action("remote_execute", "node", rollback="stop process"), PermissionLevel.R3),
    (Action("publish", "external", rollback="retract"), PermissionLevel.R3),
    (Action("spend", "api", rollback="cancel"), PermissionLevel.R3),
    (Action("cutover", "legacy", rollback="restore legacy"), PermissionLevel.R3),
    (Action("read", "x", requested_level=PermissionLevel.R3), PermissionLevel.R3),
])
def test_permission_classifier_matrix(action, expected):
    assert PolicyEngine().classify(action).level is expected


def test_permission_classifier_normalizes_kinds_and_rejects_type_coercion():
    policy = PolicyEngine()
    assert policy.classify(Action(" DELETE ", "legacy", rollback="restore")).level is PermissionLevel.R3
    assert policy.classify(Action("wipe", "disk", rollback="restore")).level is PermissionLevel.R3
    unknown = policy.classify(Action("novel_mutation", "x", rollback="undo"))
    assert unknown.level is PermissionLevel.R2
    assert "unknown action kind" in " ".join(unknown.rationale)
    with pytest.raises(ValueError, match="booleans"):
        policy.classify(Action("edit", "x", reversible="false", rollback="undo"))
    with pytest.raises(ValueError, match="permission level"):
        policy.classify(Action("read", "x", requested_level=99))


def test_author_review_deploy_must_be_separate():
    with pytest.raises(PolicyViolation):
        PolicyEngine().enforce_separation(
            author=AGENTS["smith"], reviewer=AGENTS["quench"], deployer=AGENTS["smith"])


def test_mutation_assignee_approver_and_reviewer_roles_stay_separate():
    cp = ControlPlane()
    with pytest.raises(PolicyViolation, match="author-capable"):
        cp.submit(title="bad assignment", lane="orca", requested_by="orca",
                  assigned_to="quench", action=Action("edit", "code", rollback="revert"))

    self_approval = cp.submit(
        title="production observation", lane="orca", requested_by="orca",
        assigned_to="fry", action=Action("read", "production", production=True))
    with pytest.raises(PermissionError, match="own job"):
        cp.decide(self_approval.approval_id, actor="fry", approve=True)

    job = cp.submit(title="material change", lane="orca", requested_by="orca",
                    assigned_to="smith", action=Action("edit", "code"))
    cp.decide(job.approval_id, actor="fry", approve=True, note="approved")
    cp.start_job(job.id, actor="smith")
    with pytest.raises(PolicyViolation, match="different identities"):
        cp.submit_job_review(job.id, actor="smith", reviewer="fry")
    cp.submit_job_review(job.id, actor="smith", reviewer="quench")
    cp.complete_job(job.id, actor="quench", note="independently reviewed")
    assert job.status is JobStatus.COMPLETE


def test_evidence_is_hash_chained_and_filterable(tmp_path):
    store = EvidenceStore(tmp_path / "events.db")
    cp = ControlPlane(store)
    job = cp.submit(title="read", lane="forge", requested_by="orca",
                    assigned_to="smith", action=Action("read", "repo"))
    cp.pause(job.id, actor="orca", reason="operator request")
    assert store.verify()
    assert len(store.list(correlation_id=job.correlation_id)) == 2


def test_evidence_verification_detects_tampering(tmp_path):
    store = EvidenceStore(tmp_path / "events.db")
    cp = ControlPlane(store)
    cp.submit(title="tamper proof", lane="orca", requested_by="orca",
              assigned_to="smith", action=Action("read", "x"))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.db.execute("UPDATE events SET payload='{}' WHERE seq=1")
    store.db.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.db.execute("DELETE FROM events WHERE seq=1")
    store.db.rollback()
    store.db.execute("DROP TRIGGER events_no_update")
    secret = "sk-abcdefghijklmnop"
    store.db.execute("UPDATE events SET payload=? WHERE seq=1", (
        json.dumps({"token": secret}),))
    store.db.commit()
    assert store.verify() is False
    assert secret not in str(store.list())
    store.db.execute("UPDATE events SET payload='{' WHERE seq=1")
    store.db.commit()
    assert store.verify() is False
    assert store.list()[0]["payload"] == {"error": "invalid evidence payload"}


def test_lane_and_identity_are_mandatory():
    cp = ControlPlane()
    with pytest.raises(ValueError):
        cp.submit(title="bad", lane="unknown", requested_by="orca",
                  assigned_to="smith", action=Action("read", "x"))


def test_internal_control_mutations_enforce_actor_authority():
    cp = ControlPlane()
    with pytest.raises(PermissionError, match="submit work"):
        cp.submit(title="forged", lane="orca", requested_by="smith",
                  assigned_to="smith", action=Action("read", "x"))
    with pytest.raises(PermissionError, match="bot pause"):
        cp.set_bot_pause("smith", actor="quench", paused=True, reason="forged")
    with pytest.raises(PermissionError, match="node pause"):
        cp.set_node_pause("forge", actor="smith", paused=True, reason="forged")
    with pytest.raises(PermissionError, match="lane pause"):
        cp.set_lane_pause("forge", actor="security_gate", paused=True, reason="forged")
    with pytest.raises(ValueError, match="registered identity"):
        cp.report_node_health("forge", actor="unknown", state="degraded")
    with pytest.raises(ValueError, match="boolean"):
        cp.set_node_pause("forge", actor="orca", paused="false", reason="bad type")
    with pytest.raises(ValueError, match="boolean"):
        cp.set_emergency_stop(actor="fry", active=1, reason="bad type")


def test_fleet_target_must_exist_and_match_lane():
    cp = ControlPlane()
    job = cp.submit(title="inspect Forge", lane="forge", requested_by="orca",
                    assigned_to="smith", target_node="forge",
                    action=Action("read", "service inventory"))
    assert job.target_node == "forge"
    assert job.status is JobStatus.PAUSED
    with pytest.raises(PermissionError, match="control boundary"):
        cp.resume(job.id, actor="orca", reason="node is still unproven")
    with pytest.raises(ValueError, match="unknown fleet node"):
        cp.submit(title="bad", lane="forge", requested_by="orca", assigned_to="smith",
                  target_node="unknown", action=Action("read", "x"))
    with pytest.raises(ValueError, match="job lane"):
        cp.submit(title="cross lane", lane="bgm", requested_by="orca", assigned_to="smith",
                  target_node="forge", action=Action("read", "x"))


def test_paused_node_blocks_new_work_and_records_evidence():
    cp = ControlPlane()
    cp.set_node_pause("kiln", actor="orca", paused=True, reason="maintenance")
    job = cp.submit(title="inspect Kiln", lane="forge", requested_by="orca",
                    assigned_to="smith", target_node="kiln",
                    action=Action("read", "services"))
    assert job.status is JobStatus.PAUSED
    assert "kiln" in cp.snapshot()["paused_nodes"]
    assert cp.evidence.verify()


def test_node_and_lane_controls_pause_existing_work_without_auto_resume():
    cp = ControlPlane()
    key = b"forge-health-fixture-key-material-0001"
    cp.enroll_node("forge", actor="fry", key=key)
    heartbeat = Heartbeat("forge", 1_000, 1, "healthy")
    cp.accept_heartbeat(
        heartbeat, signature=sign_heartbeat(heartbeat, key), key=key, now=1_000)
    targeted = cp.submit(
        title="targeted", lane="forge", requested_by="orca", assigned_to="smith",
        target_node="forge", action=Action("read", "services"))
    untargeted = cp.submit(
        title="lane work", lane="forge", requested_by="orca", assigned_to="smith",
        action=Action("read", "inventory"))
    cp.start_job(targeted.id, actor="smith")
    cp.start_job(untargeted.id, actor="smith")

    cp.set_node_pause("forge", actor="orca", paused=True, reason="node control")
    assert targeted.status is JobStatus.PAUSED
    assert untargeted.status is JobStatus.RUNNING
    cp.set_node_pause("forge", actor="orca", paused=False, reason="inspection complete")
    assert targeted.status is JobStatus.PAUSED

    cp.set_lane_pause("forge", actor="orca", paused=True, reason="lane control")
    assert untargeted.status is JobStatus.PAUSED
    cp.set_lane_pause("forge", actor="orca", paused=False, reason="inspection complete")
    assert untargeted.status is JobStatus.PAUSED


def test_node_health_is_explicit_and_remote_execution_stays_disabled():
    cp = ControlPlane()
    assert {n["state"] for n in cp.snapshot()["nodes"]} == {"unproven"}
    cp.report_node_health("forge", actor="orca", state="degraded", detail="manual observation")
    nodes = {n["id"]: n for n in cp.snapshot()["nodes"]}
    assert nodes["forge"]["state"] == "degraded"
    assert nodes["forge"]["last_verified"]
    assert all(not node["remote_execution_enabled"] for node in nodes.values())


def test_core_bot_registry_is_definition_only_and_routes_work():
    cp = ControlPlane()
    bots = {b["id"]: b for b in cp.snapshot()["bots"]}
    assert set(bots) == {"orca", "gemini", "quench", "security_gate"}
    assert all(not bot["runtime_enabled"] for bot in bots.values())
    assert bots["orca"]["may_execute_tools"]
    assert bots["quench"]["may_execute_tools"]
    assert not bots["gemini"]["may_execute_tools"]
    assert not next(bot for bot in bots.values() if bot["id"] == "security_gate")["may_execute_tools"]
    job = cp.queue(title="implement fleet card", lane="orca", requested_by="orca",
                   task_type="coding", action=Action("edit", "UI", rollback="revert patch"))
    assert job.assigned_to == "gemini"
    assert job.task_type == "coding"
    assert job.model_route == "coding"
    assert job.stop_condition == "independent_review_complete"
    events = cp.evidence.list(correlation_id=job.correlation_id)
    assert {event["kind"] for event in events} == {"job.submitted", "job.routed"}


def test_paused_bot_cannot_receive_queued_work():
    cp = ControlPlane()
    cp.set_bot_pause("quench", actor="orca", paused=True, reason="operator hold")
    with pytest.raises(PermissionError, match="bot is paused"):
        cp.queue(title="review", lane="forge", requested_by="orca",
                 task_type="review", action=Action("read", "change"))


def test_legacy_specialists_are_candidates_not_active_bots():
    cp = ControlPlane()
    state = cp.snapshot()
    assert set(state["migration_candidates"]) == {"ampere", "relay"}
    assert not ({"ampere", "relay"} & {b["id"] for b in state["bots"]})
    assert state["bot_build_queue"][0]["status"] == "complete"
    assert state["bot_build_queue"][5]["status"] == "complete"


def test_state_survives_restart(tmp_path):
    path = tmp_path / "orca.db"
    cp = ControlPlane(EvidenceStore(path))
    job = cp.submit(title="persist me", lane="forge", requested_by="orca",
                    assigned_to="smith", target_node="forge",
                    action=Action("read", "inventory"))
    cp.set_bot_pause("quench", actor="orca", paused=True, reason="hold")
    cp.set_node_pause("kiln", actor="orca", paused=True, reason="hold")
    cp.set_lane_pause("bgm", actor="orca", paused=True, reason="hold")
    cp.report_node_health("forge", actor="orca", state="degraded", detail="probe")
    restored = ControlPlane(EvidenceStore(path))
    assert job.id in restored.jobs
    assert restored.jobs[job.id].target_node == "forge"
    assert restored.bots.paused == {"quench"}
    assert restored.paused_nodes == {"forge", "kiln"}
    assert restored.paused_lanes == {"bgm"}
    assert restored.node_health["forge"]["state"] == "degraded"
    assert restored.jobs[job.id].status is JobStatus.PAUSED


def test_legacy_iris_state_migrates_to_temper_on_restore(tmp_path):
    path = tmp_path / "orca.db"
    cp = ControlPlane(EvidenceStore(path))
    job = cp.submit(title="legacy edge work", lane="forge", requested_by="orca",
                    assigned_to="smith", target_node="temper",
                    action=Action("read", "sensor queue"))
    job.target_node = "iris"
    cp.paused_nodes.add("iris")
    cp.node_health["iris"] = cp.node_health.pop("temper")
    cp.node_enrollments["iris"] = {
        "key_fingerprint": "legacy-fingerprint", "last_nonce": -1}
    cp._persist()

    restored = ControlPlane(EvidenceStore(path))
    assert restored.jobs[job.id].target_node == "temper"
    assert "temper" in restored.paused_nodes and "iris" not in restored.paused_nodes
    assert "temper" in restored.node_health and "iris" not in restored.node_health
    assert "temper" in restored.node_enrollments and "iris" not in restored.node_enrollments


def test_global_emergency_stop_is_fry_only_persistent_and_fail_closed(tmp_path):
    path = tmp_path / "orca.db"
    cp = ControlPlane(EvidenceStore(path))
    with pytest.raises(PermissionError):
        cp.set_emergency_stop(actor="orca", active=True, reason="forged")
    cp.set_emergency_stop(actor="fry", active=True, reason="incident")
    job = cp.submit(title="blocked", lane="forge", requested_by="orca",
                    assigned_to="smith", action=Action("read", "inventory"))
    assert job.status is JobStatus.PAUSED
    restored = ControlPlane(EvidenceStore(path))
    assert restored.emergency_stop is True
    restored.set_emergency_stop(actor="fry", active=False, reason="contained")
    assert restored.emergency_stop is False


def test_incident_lifecycle_persists_and_requires_independent_closure(tmp_path):
    path = tmp_path / "orca.db"
    cp = ControlPlane(EvidenceStore(path))
    incident = cp.open_incident(severity="S1", title="service unavailable",
                                lane="forge", owner="orca", detail="investigating")
    cp.update_incident(incident.id, actor="smith", status="contained", detail="isolated")
    with pytest.raises(PermissionError):
        cp.update_incident(incident.id, actor="smith", status="closed", detail="done")
    cp.update_incident(incident.id, actor="quench", status="closed", detail="verified")
    restored = ControlPlane(EvidenceStore(path))
    assert restored.incidents[incident.id].status.value == "closed"
    assert len(restored.evidence.list(correlation_id=incident.correlation_id)) == 3

    owned = cp.open_incident(severity="S1", title="reviewer-owned incident",
                             lane="orca", owner="quench")
    cp.update_incident(owned.id, actor="quench", status="contained")
    with pytest.raises(PermissionError, match="other than the owner"):
        cp.update_incident(owned.id, actor="quench", status="closed")
    cp.update_incident(owned.id, actor="fry", status="closed", detail="independent closure")


def test_evidence_and_incidents_redact_secret_shaped_values():
    cp = ControlPlane()
    incident = cp.open_incident(severity="S2", title="token leak",
                                lane="orca", owner="orca",
                                detail="api_key=sk-abcdefghijklmnop")
    assert "abcdefghijklmnop" not in incident.detail
    event = cp.evidence.list(correlation_id=incident.correlation_id)[0]
    assert "abcdefghijklmnop" not in str(event["payload"])


def test_incident_deduplication_and_alert_outbox_persist(tmp_path):
    path = tmp_path / "orca.db"
    cp = ControlPlane(EvidenceStore(path))
    first = cp.open_incident(severity="S2", title="Gitea offline", lane="forge", owner="orca")
    duplicate = cp.open_incident(severity="S3", title="  gitea OFFLINE  ", lane="forge", owner="fry")
    assert duplicate.id == first.id
    assert len(cp.incidents) == 1
    assert len(cp.alert_outbox) == 1
    assert cp.alert_outbox[0]["status"] == "queued"
    restored = ControlPlane(EvidenceStore(path))
    assert restored.alert_outbox == cp.alert_outbox


def test_governance_declares_retention_and_deny_delete():
    state = ControlPlane().snapshot()
    assert state["governance"]["access"]["delete_evidence"] == ()
    evidence = next(x for x in state["governance"]["retention"] if x["artifact"] == "evidence")
    assert evidence["minimum_days"] is None
    assert state["governance"]["retention_enforcement"]["automatic_deletion"] is False


def test_retention_guard_never_deletes_and_requires_fry_r3_review():
    guard = RetentionGuard()
    old_incident = RetentionRecord("incidents", "incident-old", "2020-01-01T00:00:00+00:00")
    eligible = guard.assess(old_incident, now="2030-01-01T00:00:00+00:00")
    assert eligible.status == "eligible_for_fry_r3_review"
    with pytest.raises(PermissionError, match="Fry R3"):
        guard.assert_deletion_allowed(
            old_incident, now="2030-01-01T00:00:00+00:00",
            actor="orca", approved_level=PermissionLevel.R3)
    assert guard.assert_deletion_allowed(
        old_incident, now="2030-01-01T00:00:00+00:00",
        actor="fry", approved_level=PermissionLevel.R3).record_id == "incident-old"
    with pytest.raises(PermissionError, match="prohibited"):
        guard.assert_deletion_allowed(
            RetentionRecord("evidence", "evt", "2020-01-01T00:00:00+00:00"),
            now="2030-01-01T00:00:00+00:00", actor="fry",
            approved_level=PermissionLevel.R3)


def test_retention_audit_is_persistent_dry_run_with_evidence(tmp_path):
    path = tmp_path / "orca.db"
    cp = ControlPlane(EvidenceStore(path))
    cp.submit(title="retained", lane="orca", requested_by="orca",
              assigned_to="smith", action=Action("read", "fixture"))
    report = cp.run_retention_audit(actor="orca", now="2030-01-01T00:00:00+00:00")
    assert report["mode"] == "dry_run"
    assert report["automatic_deletions"] == 0
    assert report["record_count"] >= 2
    restored = ControlPlane(EvidenceStore(path))
    assert restored.retention_audits[0]["id"] == report["id"]
    assert any(event["kind"] == "retention.audit_completed" for event in restored.evidence.list())


def test_stale_control_plane_cannot_overwrite_newer_state(tmp_path):
    path = tmp_path / "orca.db"
    first = ControlPlane(EvidenceStore(path))
    stale = ControlPlane(EvidenceStore(path))
    first.set_lane_pause("forge", actor="orca", paused=True, reason="test")
    with pytest.raises(RuntimeError, match="stale control-plane"):
        stale.set_lane_pause("bgm", actor="orca", paused=True, reason="stale")
    restored = ControlPlane(EvidenceStore(path))
    assert restored.paused_lanes == {"forge"}


def test_state_and_evidence_roll_back_together_when_snapshot_write_fails(tmp_path):
    path = tmp_path / "orca.db"
    cp = ControlPlane(EvidenceStore(path))
    cp.evidence.db.execute(
        """CREATE TRIGGER reject_control_insert BEFORE INSERT ON control_state BEGIN
               SELECT RAISE(ABORT, 'injected state failure');
           END"""
    )
    cp.evidence.db.commit()

    with pytest.raises(sqlite3.IntegrityError, match="injected state failure"):
        cp.submit(title="must roll back", lane="orca", requested_by="orca",
                  assigned_to="smith", action=Action("read", "fixture"))

    assert cp.jobs == {}
    assert cp.approvals == {}
    assert cp.state_revision == 0
    assert cp.evidence.list() == []
    assert ControlPlane(EvidenceStore(path)).jobs == {}
    assert cp.evidence.verify()

    cp.evidence.db.execute("DROP TRIGGER reject_control_insert")
    cp.evidence.db.commit()
    job = cp.submit(title="persisted", lane="orca", requested_by="orca",
                    assigned_to="smith", action=Action("read", "fixture"))
    event_count = len(cp.evidence.list())
    cp.evidence.db.execute(
        """CREATE TRIGGER reject_control_update BEFORE UPDATE ON control_state BEGIN
               SELECT RAISE(ABORT, 'injected update failure');
           END"""
    )
    cp.evidence.db.commit()

    with pytest.raises(sqlite3.IntegrityError, match="injected update failure"):
        cp.pause(job.id, actor="orca", reason="must roll back")

    assert cp.jobs[job.id] is job
    assert job.status is JobStatus.READY
    assert len(cp.evidence.list()) == event_count
    assert ControlPlane(EvidenceStore(path)).jobs[job.id].status is JobStatus.READY
    assert cp.evidence.verify()


def test_secret_shaped_job_and_operator_inputs_never_reach_durable_state(tmp_path):
    path = tmp_path / "orca.db"
    cp = ControlPlane(EvidenceStore(path))
    secret = "sk-abcdefghijklmnop"
    job = cp.submit(
        title=f"release {secret}", lane="orca", requested_by="orca",
        assigned_to="smith",
        action=Action(
            "deploy", f"service token={secret}", production=True,
            rollback=f"password={secret}", metadata={f"token={secret}": secret}),
        model_route=f"route-{secret}", stop_condition=f"review token={secret}",
    )
    cp.decide(job.approval_id, actor="fry", approve=False, note=f"deny {secret}")
    cp.report_node_health("forge", actor="orca", state="degraded", detail=f"token={secret}")

    raw_state = cp.evidence.db.execute(
        "SELECT payload FROM control_state WHERE singleton=1").fetchone()[0]
    cp.evidence.append(
        correlation_id=secret, actor=secret, lane=secret, kind=secret,
        payload={secret: secret})
    # Direct EvidenceStore writes intentionally leave the control snapshot
    # behind; checkpoint this test-only event before reading through ControlPlane.
    with cp.evidence.transaction():
        cp._persist()
    raw_event = "|".join(str(value) for value in cp.evidence.db.execute(
        "SELECT correlation_id, actor, lane, kind, payload FROM events ORDER BY seq DESC LIMIT 1"
    ).fetchone())
    assert secret not in raw_state
    assert secret not in raw_event
    assert secret not in str(cp.snapshot())
    assert secret not in str(ControlPlane(EvidenceStore(path)).snapshot())
    assert cp.evidence.verify()

    payload = json.loads(raw_state)
    payload["jobs"][0]["title"] = secret
    cp.evidence.db.execute(
        "UPDATE control_state SET payload=? WHERE singleton=1",
        (json.dumps(payload),))
    cp.evidence.db.commit()
    with pytest.raises(RuntimeError, match="control state integrity"):
        ControlPlane(EvidenceStore(path))


def test_evidence_tampering_blocks_startup_and_further_mutation(tmp_path):
    path = tmp_path / "tampered-evidence.db"
    cp = ControlPlane(EvidenceStore(path))
    cp.submit(title="proof", lane="orca", requested_by="orca",
              assigned_to="smith", action=Action("read", "fixture"))
    cp.evidence.db.execute("DROP TRIGGER events_no_update")
    cp.evidence.db.execute("UPDATE events SET payload='{}' WHERE seq=1")
    cp.evidence.db.commit()

    with pytest.raises(RuntimeError, match="evidence chain integrity"):
        cp.set_lane_pause("orca", actor="orca", paused=True, reason="blocked")
    with pytest.raises(RuntimeError, match="evidence chain integrity"):
        ControlPlane(EvidenceStore(path))


def test_direct_state_and_evidence_payloads_are_bounded():
    cp = ControlPlane()
    with pytest.raises(ValueError, match="job action exceeds"):
        cp.submit(
            title="oversized", lane="orca", requested_by="orca", assigned_to="smith",
            action=Action("read", "fixture", metadata={"blob": "x" * 70_000}))
    with pytest.raises(ValueError, match="evidence payload exceeds"):
        cp.evidence.append(
            correlation_id="c", actor="orca", lane="orca", kind="test",
            payload={"blob": "x" * 256_001})
    with pytest.raises(ValueError, match="JSON"):
        cp.submit(
            title="non-finite", lane="orca", requested_by="orca", assigned_to="smith",
            action=Action("read", "fixture", metadata={"value": float("nan")}))
    assert cp.jobs == {}
    assert cp.evidence.list() == []
    assert cp.evidence.verify()


def test_concurrent_evidence_appends_preserve_hash_chain(tmp_path):
    path = tmp_path / "evidence.db"
    stores = [EvidenceStore(path), EvidenceStore(path)]

    def append(index):
        stores[index % 2].append(correlation_id=f"c{index}", actor="orca",
                                 lane="orca", kind="test", payload={"index": index})

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(append, range(100)))
    assert stores[0].verify()
    assert len(stores[0].list(limit=200)) == 100


def test_same_control_plane_serializes_concurrent_mutations(tmp_path):
    cp = ControlPlane(EvidenceStore(tmp_path / "orca.db"))

    def submit(index):
        return cp.submit(title=f"job {index}", lane="orca", requested_by="orca",
                         assigned_to="smith", action=Action("read", f"fixture {index}"))

    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = list(pool.map(submit, range(40)))
    assert len({job.id for job in jobs}) == 40
    assert len(cp.jobs) == 40
    assert cp.evidence.verify()
    assert ControlPlane(EvidenceStore(tmp_path / "orca.db")).snapshot()["jobs"]


def test_job_lifecycle_requires_assigned_author_and_independent_reviewer():
    cp = ControlPlane()
    job = cp.submit(title="implement", lane="orca", requested_by="orca",
                    assigned_to="smith", action=Action("edit", "code", rollback="revert"))
    with pytest.raises(PermissionError, match="assigned bot"):
        cp.start_job(job.id, actor="orca")
    cp.start_job(job.id, actor="smith")
    with pytest.raises(PermissionError, match="running job author"):
        cp.submit_job_review(job.id, actor="orca")
    cp.submit_job_review(job.id, actor="smith", reviewer="quench")
    with pytest.raises(PermissionError, match="independent reviewer"):
        cp.complete_job(job.id, actor="smith", note="self approved")
    with pytest.raises(ValueError, match="evidence note"):
        cp.complete_job(job.id, actor="quench", note="")
    cp.complete_job(job.id, actor="quench", note="tests and diff reviewed")
    assert job.status is JobStatus.COMPLETE
    assert [e["kind"] for e in reversed(cp.evidence.list(correlation_id=job.correlation_id))] == [
        "job.submitted", "job.started", "job.review_requested", "job.completed"]


def test_bot_pause_and_emergency_stop_pause_active_jobs():
    cp = ControlPlane()
    first = cp.submit(title="one", lane="orca", requested_by="orca",
                      assigned_to="gemini", action=Action("read", "x"))
    cp.start_job(first.id, actor="gemini")
    cp.set_bot_pause("gemini", actor="orca", paused=True, reason="hold")
    assert first.status is JobStatus.PAUSED
    cp.set_bot_pause("gemini", actor="orca", paused=False, reason="cleared")
    second = cp.submit(title="two", lane="orca", requested_by="orca",
                       assigned_to="gemini", action=Action("read", "x"))
    cp.set_emergency_stop(actor="fry", active=True, reason="incident")
    assert second.status is JobStatus.PAUSED


def test_approved_job_stays_paused_while_control_boundary_is_active():
    cp = ControlPlane()
    job = cp.submit(title="material", lane="orca", requested_by="orca",
                    assigned_to="smith", action=Action("deploy", "x", rollback="restore"))
    cp.set_emergency_stop(actor="fry", active=True, reason="incident")
    cp.decide(job.approval_id, actor="fry", approve=True, note="approved after containment")
    assert job.status is JobStatus.PAUSED
