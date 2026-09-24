from __future__ import annotations

import json
from threading import Event, Thread

import pytest

from orca import Action, ControlPlane
from orca.domain import JobStatus
from orca.evidence import EvidenceStore
from orca.fleet import Heartbeat, sign_heartbeat
from orca.maintenance import MaintenanceTicker
from orca.registry import NODES


KEY = b"maintenance-tick-test-key-material-0001"


def _healthy_node(
    control_plane: ControlPlane,
    node_id: str,
    *,
    accepted_at: int = 1_000,
    nonce: int = 1,
) -> None:
    key = (KEY + node_id.encode())[:32]
    control_plane.enroll_node(node_id, actor="fry", key=key)
    heartbeat = Heartbeat(node_id, accepted_at, nonce, "healthy", "fixture")
    control_plane.accept_heartbeat(
        heartbeat,
        signature=sign_heartbeat(heartbeat, key),
        key=key,
        now=accepted_at,
    )


def test_ticker_is_inert_until_tick_is_called():
    control_plane = ControlPlane()
    _healthy_node(control_plane, "ember")
    calls = []
    ticker = MaintenanceTicker(
        control_plane, clock=lambda: calls.append("clock") or 1_180)

    assert calls == []
    assert ticker.last_tick_epoch is None
    assert control_plane.node_health["ember"]["state"] == "healthy"

    report = ticker.tick()
    assert calls == ["clock"]
    assert report.changes[0].node_id == "ember"
    assert report.changes[0].state == "degraded"
    assert ticker.last_tick_epoch == 1_180


def test_tick_report_is_deterministic_bounded_and_json_safe():
    control_plane = ControlPlane()
    for node_id in reversed(sorted(NODES)):
        _healthy_node(control_plane, node_id)

    report = MaintenanceTicker(control_plane, clock=lambda: 1_600).tick()
    expected_nodes = sorted(NODES)
    assert [change.node_id for change in report.changes] == expected_nodes
    assert {change.state for change in report.changes} == {"offline"}
    assert report.evaluated_nodes == len(NODES)
    assert report.changed is True
    assert report.to_dict() == {
        "schema_version": 1,
        "tick_epoch": 1_600,
        "degraded_after": 180,
        "offline_after": 600,
        "evaluated_nodes": len(NODES),
        "changed": True,
        "changed_count": len(NODES),
        "changes": [
            {"node_id": node_id, "state": "offline"}
            for node_id in expected_nodes
        ],
        "state_revision": control_plane.state_revision,
    }
    assert len(report.changes) <= len(NODES)
    json.dumps(report.to_dict(), allow_nan=False)


def test_repeated_ticks_are_idempotent_and_progress_degraded_to_offline():
    control_plane = ControlPlane()
    _healthy_node(control_plane, "ember")
    times = iter((1_180, 1_180, 1_600, 1_600))
    ticker = MaintenanceTicker(control_plane, clock=lambda: next(times))

    degraded = ticker.tick()
    degraded_revision = control_plane.state_revision
    degraded_events = len(control_plane.evidence.list(limit=100))
    assert degraded.to_dict()["changes"] == [
        {"node_id": "ember", "state": "degraded"}
    ]

    repeated_degraded = ticker.tick()
    assert repeated_degraded.changed is False
    assert control_plane.state_revision == degraded_revision
    assert len(control_plane.evidence.list(limit=100)) == degraded_events

    offline = ticker.tick()
    offline_revision = control_plane.state_revision
    offline_events = len(control_plane.evidence.list(limit=100))
    assert offline.to_dict()["changes"] == [
        {"node_id": "ember", "state": "offline"}
    ]

    repeated_offline = ticker.tick()
    assert repeated_offline.changed is False
    assert control_plane.state_revision == offline_revision
    assert len(control_plane.evidence.list(limit=100)) == offline_events


def test_stale_expiry_never_improves_an_offline_node():
    control_plane = ControlPlane()
    key = KEY[:32]
    control_plane.enroll_node("ember", actor="fry", key=key)
    heartbeat = Heartbeat("ember", 1_000, 1, "offline", "node reported offline")
    control_plane.accept_heartbeat(
        heartbeat,
        signature=sign_heartbeat(heartbeat, key),
        key=key,
        now=1_000,
    )
    revision = control_plane.state_revision
    events = len(control_plane.evidence.list(limit=100))

    report = MaintenanceTicker(control_plane, clock=lambda: 1_180).tick()

    assert report.changed is False
    assert control_plane.node_health["ember"]["state"] == "offline"
    assert control_plane.state_revision == revision
    assert len(control_plane.evidence.list(limit=100)) == events


def test_tick_report_is_coherent_with_expiry_revision_under_concurrency():
    control_plane = ControlPlane()
    _healthy_node(control_plane, "ember")
    expiry_done = Event()
    mutation_attempted = Event()
    expiry_revisions = []
    original_expire = control_plane.expire_stale_nodes

    def wrapped_expire(**kwargs):
        changed = original_expire(**kwargs)
        expiry_revisions.append(control_plane.state_revision)
        expiry_done.set()
        assert mutation_attempted.wait(timeout=2)
        return changed

    control_plane.expire_stale_nodes = wrapped_expire

    def mutate_after_expiry():
        assert expiry_done.wait(timeout=2)
        mutation_attempted.set()
        control_plane.set_emergency_stop(
            actor="fry", active=True, reason="concurrency fixture")

    concurrent = Thread(target=mutate_after_expiry)
    concurrent.start()
    report = MaintenanceTicker(control_plane, clock=lambda: 1_600).tick()
    concurrent.join(timeout=2)

    assert not concurrent.is_alive()
    assert report.state_revision == expiry_revisions[0]
    assert report.to_dict()["changes"] == [
        {"node_id": "ember", "state": "offline"}
    ]
    assert control_plane.state_revision == report.state_revision + 1
    assert control_plane.emergency_stop is True


def test_tick_validation_rejects_bad_configuration_and_clock_values():
    control_plane = ControlPlane()
    with pytest.raises(TypeError, match="ControlPlane"):
        MaintenanceTicker(object(), clock=lambda: 1)
    with pytest.raises(TypeError, match="callable"):
        MaintenanceTicker(control_plane, clock=1)
    for degraded, offline in ((0, 1), (1, 1), (2, 1), (True, 10), (1, False)):
        with pytest.raises(ValueError, match="positive and ordered"):
            MaintenanceTicker(
                control_plane,
                clock=lambda: 1,
                degraded_after=degraded,
                offline_after=offline,
            )

    for invalid in (-1, True, 1.5, "1", 1 << 63):
        ticker = MaintenanceTicker(control_plane, clock=lambda value=invalid: value)
        with pytest.raises(ValueError, match="bounded non-negative integer"):
            ticker.tick()


def test_ticker_rejects_clock_regression_without_mutating_state():
    control_plane = ControlPlane()
    times = iter((1_000, 999))
    ticker = MaintenanceTicker(control_plane, clock=lambda: next(times))
    first = ticker.tick()
    revision = control_plane.state_revision
    assert first.changed is False

    with pytest.raises(ValueError, match="moved backwards"):
        ticker.tick()
    assert ticker.last_tick_epoch == 1_000
    assert control_plane.state_revision == revision


def test_expiry_and_paused_work_survive_restart_and_remain_idempotent(tmp_path):
    path = tmp_path / "orca.db"
    control_plane = ControlPlane(EvidenceStore(path))
    _healthy_node(control_plane, "ember")
    job = control_plane.submit(
        title="maintenance restart fixture",
        lane="forge",
        requested_by="orca",
        assigned_to="smith",
        target_node="ember",
        action=Action("read", "fixture"),
    )
    control_plane.start_job(job.id, actor="smith")

    report = MaintenanceTicker(control_plane, clock=lambda: 1_600).tick()
    assert report.to_dict()["changes"] == [
        {"node_id": "ember", "state": "offline"}
    ]
    assert control_plane.jobs[job.id].status is JobStatus.PAUSED
    revision = control_plane.state_revision
    control_plane.evidence.db.close()

    restored = ControlPlane(EvidenceStore(path))
    assert restored.node_health["ember"]["state"] == "offline"
    assert "ember" in restored.paused_nodes
    assert restored.jobs[job.id].status is JobStatus.PAUSED
    assert restored.state_revision == revision
    event_count = len(restored.evidence.list(limit=100))

    repeated = MaintenanceTicker(restored, clock=lambda: 1_600).tick()
    assert repeated.changed is False
    assert restored.state_revision == revision
    assert len(restored.evidence.list(limit=100)) == event_count


def test_restart_rejects_clock_regression_from_durable_expiry_state(tmp_path):
    path = tmp_path / "maintenance-clock.db"
    control_plane = ControlPlane(EvidenceStore(path))
    _healthy_node(control_plane, "ember")
    MaintenanceTicker(control_plane, clock=lambda: 1_600).tick()
    assert control_plane.node_health["ember"]["state"] == "offline"
    control_plane.evidence.db.close()

    restored = ControlPlane(EvidenceStore(path))
    revision = restored.state_revision
    event_count = len(restored.evidence.list(limit=100))
    ticker = MaintenanceTicker(restored, clock=lambda: 1_180)

    with pytest.raises(ValueError, match="moved backwards"):
        ticker.tick()
    assert restored.node_health["ember"]["state"] == "offline"
    assert restored.state_revision == revision
    assert len(restored.evidence.list(limit=100)) == event_count
