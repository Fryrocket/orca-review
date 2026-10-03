"""Behavioral regressions discovered during the September 23 code review."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from orca import Action, ControlPlane, PermissionLevel
from orca.domain import JobStatus
from orca.evidence import EvidenceStore
from orca.fleet import Heartbeat, sign_heartbeat
from orca.models import ModelRoute, ModelRouter
from orca.policy import PolicyEngine
from orca.security import redact


def test_credentials_in_named_fields_are_redacted_before_persistence(tmp_path):
    secret = "synthetic-credential-for-review"
    payload = {"api_key": secret, "nested": {"Authorization": secret},
               "password": secret, "key_fingerprint": "safe-public-fingerprint"}
    assert secret not in str(redact(payload))
    assert redact(payload)["key_fingerprint"] == "safe-public-fingerprint"
    store = EvidenceStore(tmp_path / "redaction.db")
    store.append(correlation_id="review", actor="orca", lane="orca", kind="test", payload=payload)
    assert secret not in store.db.execute("SELECT payload FROM events").fetchone()[0]


def test_work_submitted_during_stop_preserves_approval_and_can_resume(tmp_path):
    path = tmp_path / "paused.db"
    cp = ControlPlane(EvidenceStore(path))
    cp.set_emergency_stop(actor="fry", active=True, reason="review")
    job = cp.submit(title="release", lane="orca", requested_by="orca",
                    assigned_to="smith", action=Action("deploy", "test fixture"))
    assert job.status is JobStatus.PAUSED
    assert job.approval_id in cp.approvals
    cp.set_emergency_stop(actor="fry", active=False, reason="review done")
    cp.resume(job.id, actor="orca", reason="return for approval")
    assert job.status is JobStatus.WAITING_APPROVAL
    cp.decide(job.approval_id, actor="fry", approve=True, note="fixture approval")
    cp.start_job(job.id, actor="smith")
    cp.pause(job.id, actor="orca", reason="operator checkpoint")
    restored = ControlPlane(EvidenceStore(path))
    restored.resume(job.id, actor="orca", reason="restart work")
    assert restored.jobs[job.id].status is JobStatus.READY
    restored.start_job(job.id, actor="smith")
    restored.submit_job_review(job.id, actor="smith", reviewer="quench")
    restored.pause(job.id, actor="orca", reason="hold review")
    restored.resume(job.id, actor="orca", reason="continue review")
    assert restored.jobs[job.id].status is JobStatus.REVIEW
    restored.complete_job(job.id, actor="quench", note="reviewed fixture")
    with pytest.raises(ValueError, match="terminal"):
        restored.pause(job.id, actor="orca", reason="must not reopen")


def test_resume_cannot_bypass_active_boundaries_or_worker_authority():
    cp = ControlPlane()
    cp.set_bot_pause("gemini", actor="orca", paused=True, reason="review")
    job = cp.submit(title="read", lane="orca", requested_by="orca",
                    assigned_to="gemini", action=Action("read", "fixture"))
    assert job.status is JobStatus.PAUSED
    with pytest.raises(PermissionError):
        cp.resume(job.id, actor="gemini", reason="self resume")
    with pytest.raises(PermissionError, match="boundary"):
        cp.resume(job.id, actor="orca", reason="blocked")
    cp.set_bot_pause("gemini", actor="orca", paused=False, reason="released")
    assert job.status is JobStatus.PAUSED
    cp.resume(job.id, actor="orca", reason="explicit resume")
    assert job.status is JobStatus.READY


def test_reenrollment_with_same_key_cannot_reset_replay_protection():
    cp = ControlPlane()
    key = b"synthetic-node-key-for-review-12345"
    cp.enroll_node("forge", actor="fry", key=key)
    heartbeat = Heartbeat("forge", 10000, 5, "healthy")
    signature = sign_heartbeat(heartbeat, key)
    cp.accept_heartbeat(heartbeat, signature=signature, key=key, now=10000)
    cp.enroll_node("forge", actor="fry", key=key)
    with pytest.raises(PermissionError, match="replay"):
        cp.accept_heartbeat(heartbeat, signature=signature, key=key, now=10000)


def test_float_permission_level_is_rejected():
    with pytest.raises(ValueError, match="permission level"):
        PolicyEngine().classify(Action("read", "fixture", requested_level=2.0))


def test_string_approval_cannot_authorize_cloud_route():
    router = ModelRouter({"coding": ModelRoute("coding", "local", "cloud", monthly_hard_cap_usd=1)})
    with pytest.raises(ValueError, match="boolean"):
        router.select("coding", local_capable=False, cloud_approved="false",
                      cloud_approved_by="fry", approved_level=PermissionLevel.R3)


def test_cost_record_waits_for_other_control_transaction():
    cp = ControlPlane()
    attempting = Event()

    def record_cost():
        attempting.set()
        cp.costs.record(job_id="fixture", bot_id="smith", lane="orca", model="local",
                        tokens_in=1, tokens_out=1, cost_usd=0)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(RuntimeError, match="rollback fixture"):
            with cp.evidence.transaction():
                future = pool.submit(record_cost)
                assert attempting.wait(2)
                with pytest.raises(TimeoutError):
                    future.result(timeout=0.05)
                raise RuntimeError("rollback fixture")
        future.result(timeout=2)
    assert cp.costs.summary()["by_dimension"]["bot_id"][0]["tokens_in"] == 1


@pytest.mark.parametrize("worker", ["orca", "quench"])
def test_read_only_worker_can_finish_through_independent_review(worker):
    cp = ControlPlane()
    job = cp.submit(title="verification", lane="orca", requested_by="orca",
                    assigned_to=worker, action=Action("read", "fixture"))
    cp.start_job(job.id, actor=worker)
    cp.submit_job_review(job.id, actor=worker, reviewer="fry")
    cp.complete_job(job.id, actor="fry", note="reviewed result")
    assert job.status is JobStatus.COMPLETE
