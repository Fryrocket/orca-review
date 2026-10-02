from __future__ import annotations

from datetime import datetime, timezone
import json

from deploy.recovery.orca_fleet_readiness import assess
from deploy.recovery.orca_wake_guard import magic_packet, write_state


def _snapshot(now: int) -> dict:
    verified = datetime.fromtimestamp(now - 30, timezone.utc).isoformat()
    return {
        "evidence_chain_valid": True,
        "emergency_stop": False,
        "paused_nodes": [],
        "state_revision": 42,
        "nodes": [
            {"id": node_id, "state": "healthy", "last_verified": verified}
            for node_id in ("anvil", "forge", "kiln", "ember", "temper")
        ],
    }


def test_magic_packet_has_standard_shape():
    packet = magic_packet("08:bf:b8:d4:42:9b")
    assert packet[:6] == b"\xff" * 6
    assert len(packet) == 102
    assert packet[6:12] == bytes.fromhex("08bfb8d4429b")


def test_atomic_state_is_private_and_valid_json(tmp_path):
    target = tmp_path / "recovery.json"
    write_state(target, {"state": "healthy"})
    assert json.loads(target.read_text()) == {"state": "healthy"}
    assert target.stat().st_mode & 0o777 == 0o600


def test_fleet_readiness_requires_every_fresh_active_node():
    now = 2_000_000_000
    report = assess(_snapshot(now), now=now, max_age=180)
    assert report["ready"] is True
    assert report["failures"] == []

    snapshot = _snapshot(now)
    snapshot["paused_nodes"] = ["anvil"]
    snapshot["nodes"][4]["last_verified"] = datetime.fromtimestamp(
        now - 181, timezone.utc).isoformat()
    report = assess(snapshot, now=now, max_age=180)
    assert report["ready"] is False
    assert "node_paused:anvil" in report["failures"]
    assert "heartbeat_stale:temper:181" in report["failures"]


def test_fleet_readiness_fails_closed_on_bad_integrity_or_missing_node():
    now = 2_000_000_000
    snapshot = _snapshot(now)
    snapshot["evidence_chain_valid"] = False
    snapshot["nodes"] = snapshot["nodes"][:-1]
    report = assess(snapshot, now=now, max_age=180)
    assert report["ready"] is False
    assert "evidence_integrity_invalid" in report["failures"]
    assert "node_missing:temper" in report["failures"]
