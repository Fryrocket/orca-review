import time

import pytest

from orca import Action
from orca.control_plane import ControlPlane
from orca.evidence import EvidenceStore
from orca.fleet import Heartbeat, sign_heartbeat
from orca.connectors import CONNECTOR_ACTIONS
from orca.domain import JobStatus, PermissionLevel
from orca.registry import NODES


def test_fry_enrollment_and_signed_heartbeat_persist_without_key(tmp_path):
    path = tmp_path / "orca.db"
    cp = ControlPlane(EvidenceStore(path))
    key = b"a" * 32
    with pytest.raises(PermissionError, match="only Fry"):
        cp.enroll_node("forge", actor="orca", key=key)
    record = cp.enroll_node("forge", actor="fry", key=key)
    now = int(time.time())
    heartbeat = Heartbeat("forge", now, 1, "healthy", "services verified")
    cp.accept_heartbeat(heartbeat, signature=sign_heartbeat(heartbeat, key), key=key, now=now)
    assert cp.node_health["forge"]["state"] == "healthy"
    restored = ControlPlane(EvidenceStore(path))
    assert restored.node_enrollments["forge"]["key_fingerprint"] == record["key_fingerprint"]
    assert "a" * 32 not in str(restored.snapshot())


def test_heartbeat_rejects_bad_key_signature_replay_and_stale_time():
    cp = ControlPlane()
    key = b"b" * 32
    cp.enroll_node("kiln", actor="fry", key=key)
    heartbeat = Heartbeat("kiln", 1000, 1, "healthy")
    with pytest.raises(PermissionError, match="this key"):
        cp.accept_heartbeat(heartbeat, signature="bad", key=b"c" * 32, now=1000)
    with pytest.raises(PermissionError, match="signature"):
        cp.accept_heartbeat(heartbeat, signature="bad", key=key, now=1000)
    signature = sign_heartbeat(heartbeat, key)
    cp.accept_heartbeat(heartbeat, signature=signature, key=key, now=1000)
    with pytest.raises(PermissionError, match="replay"):
        cp.accept_heartbeat(heartbeat, signature=signature, key=key, now=1000)
    stale = Heartbeat("kiln", 1, 2, "healthy")
    with pytest.raises(PermissionError, match="stale"):
        cp.accept_heartbeat(stale, signature=sign_heartbeat(stale, key), key=key, now=1000)
    malformed = Heartbeat("kiln", True, True, "healthy")
    with pytest.raises(ValueError, match="invalid types"):
        cp.accept_heartbeat(
            malformed, signature="0" * 64, key=key, now=1000)
    with pytest.raises(PermissionError, match="signature"):
        cp.accept_heartbeat(
            Heartbeat("kiln", 1000, 2, "healthy"), signature="not-a-signature",
            key=key, now=1000)
    with pytest.raises(ValueError, match="32 bytes"):
        cp.enroll_node("forge", actor="fry", key=b"short")


def test_key_rotation_invalidates_health_pauses_work_and_requires_new_key():
    cp = ControlPlane()
    first_key = b"first-forge-key-material-00000001"
    second_key = b"second-forge-key-material-0000001"
    cp.enroll_node("forge", actor="fry", key=first_key)
    first = Heartbeat("forge", 1_000, 7, "healthy")
    cp.accept_heartbeat(
        first, signature=sign_heartbeat(first, first_key), key=first_key, now=1_000)
    job = cp.submit(
        title="rotation fixture", lane="forge", requested_by="orca",
        assigned_to="smith", target_node="forge", action=Action("read", "fixture"))
    cp.start_job(job.id, actor="smith")

    cp.enroll_node("forge", actor="fry", key=second_key)

    assert cp.node_health["forge"]["state"] == "unproven"
    assert "forge" in cp.paused_nodes
    assert job.status is JobStatus.PAUSED
    assert cp.evidence.list(limit=1)[0]["kind"] == "node.key_rotated"
    with pytest.raises(PermissionError, match="this key"):
        cp.accept_heartbeat(
            Heartbeat("forge", 1_001, 8, "healthy"),
            signature=sign_heartbeat(Heartbeat("forge", 1_001, 8, "healthy"), first_key),
            key=first_key,
            now=1_001,
        )
    replacement = Heartbeat("forge", 1_001, 1, "healthy")
    cp.accept_heartbeat(
        replacement, signature=sign_heartbeat(replacement, second_key),
        key=second_key, now=1_001)
    assert cp.node_health["forge"]["state"] == "healthy"
    assert "forge" in cp.paused_nodes
    cp.set_node_pause("forge", actor="orca", paused=False, reason="new key verified")
    cp.resume(job.id, actor="orca", reason="rotation verified")
    assert job.status is JobStatus.READY


def test_receiver_time_not_client_time_drives_staleness():
    cp = ControlPlane()
    key = b"server-clock-fixture-key-material-01"
    cp.enroll_node("ember", actor="fry", key=key)
    heartbeat = Heartbeat("ember", 1_100, 1, "healthy")
    cp.accept_heartbeat(
        heartbeat, signature=sign_heartbeat(heartbeat, key), key=key, now=1_000)
    assert cp.node_enrollments["ember"]["last_seen_epoch"] == 1_000
    assert cp.expire_stale_nodes(now=1_179) == []
    assert cp.expire_stale_nodes(now=1_180) == ["ember"]


def test_manual_health_cannot_claim_healthy():
    cp = ControlPlane()
    with pytest.raises(PermissionError, match="authenticated heartbeat"):
        cp.report_node_health("forge", actor="orca", state="healthy")


def test_loss_of_contact_degrades_then_offlines_and_pauses_node():
    cp = ControlPlane()
    key = b"d" * 32
    cp.enroll_node("ember", actor="fry", key=key)
    heartbeat = Heartbeat("ember", 1000, 1, "healthy")
    cp.accept_heartbeat(heartbeat, signature=sign_heartbeat(heartbeat, key), key=key, now=1000)
    assert cp.expire_stale_nodes(now=1179) == []
    assert cp.expire_stale_nodes(now=1180) == ["ember"]
    assert cp.node_health["ember"]["state"] == "degraded"
    assert "ember" in cp.paused_nodes
    assert cp.expire_stale_nodes(now=1600) == ["ember"]
    assert cp.node_health["ember"]["state"] == "offline"


def test_fresh_signed_heartbeat_clears_only_availability_pause():
    cp = ControlPlane()
    key = b"recovery-heartbeat-key-material-001"
    cp.enroll_node("ember", actor="fry", key=key)
    first = Heartbeat("ember", 1_000, 1, "healthy")
    cp.accept_heartbeat(first, signature=sign_heartbeat(first, key), key=key, now=1_000)
    cp.expire_stale_nodes(now=1_600)

    assert cp.node_pause_reasons["ember"] == {"heartbeat_stale"}
    recovered = Heartbeat("ember", 1_601, 2, "healthy")
    cp.accept_heartbeat(
        recovered, signature=sign_heartbeat(recovered, key), key=key, now=1_601)

    assert "ember" not in cp.paused_nodes
    assert "ember" not in cp.node_pause_reasons
    assert cp.evidence.list(limit=2)[1]["kind"] == "node.recovered_automatically"


def test_healthy_heartbeat_never_clears_operator_or_key_rotation_pause():
    cp = ControlPlane()
    first_key = b"first-recovery-key-material-00001"
    second_key = b"second-recovery-key-material-0001"
    cp.enroll_node("forge", actor="fry", key=first_key)
    cp.set_node_pause("forge", actor="fry", paused=True, reason="maintenance")
    first = Heartbeat("forge", 1_000, 1, "healthy")
    cp.accept_heartbeat(first, signature=sign_heartbeat(first, first_key), key=first_key, now=1_000)
    assert cp.node_pause_reasons["forge"] == {"operator"}

    cp.enroll_node("forge", actor="fry", key=second_key)
    replacement = Heartbeat("forge", 1_001, 1, "healthy")
    cp.accept_heartbeat(
        replacement, signature=sign_heartbeat(replacement, second_key),
        key=second_key, now=1_001)

    assert "forge" in cp.paused_nodes
    assert cp.node_pause_reasons["forge"] == {"key_rotation", "operator"}


@pytest.mark.parametrize("node_id", sorted(NODES))
def test_every_registered_node_accepts_authentication_then_fails_closed_stale(node_id):
    cp = ControlPlane()
    key = (node_id.encode() * 32)[:32]
    cp.enroll_node(node_id, actor="fry", key=key)
    heartbeat = Heartbeat(node_id, 10_000, 1, "healthy", "test fixture")
    cp.accept_heartbeat(
        heartbeat, signature=sign_heartbeat(heartbeat, key), key=key, now=10_000)
    assert cp.node_health[node_id]["state"] == "healthy"
    assert cp.expire_stale_nodes(now=10_600) == [node_id]
    assert cp.node_health[node_id]["state"] == "offline"
    assert node_id in cp.paused_nodes


def test_connector_gateway_prepares_only_classified_reads():
    cp = ControlPlane()
    request = cp.prepare_connector_read(actor="orca", connector="gitea",
                                        operation="read", resource="repos/fry/orca")
    assert request["level"].name == "R0"
    with pytest.raises(PermissionError, match="write disabled"):
        cp.prepare_connector_read(actor="orca", connector="gitea",
                                  operation="push", resource="repo")
    with pytest.raises(PermissionError, match="unknown connector"):
        cp.prepare_connector_read(actor="orca", connector="unknown",
                                  operation="read", resource="x")


def test_every_connector_has_declared_read_and_mutation_classifications():
    cp = ControlPlane()
    assert set(CONNECTOR_ACTIONS) == {row["id"] for row in cp.snapshot()["connectors"]}
    for connector, rules in CONNECTOR_ACTIONS.items():
        assert rules["read"].level is PermissionLevel.R0
        assert rules["read"].mutates is False
        assert any(rule.mutates for rule in rules.values()), connector
    assert CONNECTOR_ACTIONS["gitea"]["push"].level is PermissionLevel.R3
    assert CONNECTOR_ACTIONS["cloudflare"]["change_dns"].level is PermissionLevel.R3
