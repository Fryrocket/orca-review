from __future__ import annotations

import json
import multiprocessing
import os
from pathlib import Path

import pytest

from orca.fleet import sign_heartbeat
from orca.heartbeat_agent import (
    HeartbeatAgent,
    HeartbeatDeliveryError,
    HeartbeatStateError,
)


KEY = b"heartbeat-agent-test-key-material" * 2


def _agent(path: Path, transport, *, clock=lambda: 1_000) -> HeartbeatAgent:
    return HeartbeatAgent(
        node_id="anvil",
        key=KEY,
        state_path=path,
        transport=transport,
        clock=clock,
    )


def _concurrent_sender(state_path: str, sends: int, start, results) -> None:
    """Spawn-safe worker used to prove inter-process nonce reservation."""

    agent = HeartbeatAgent(
        node_id="anvil",
        key=KEY,
        state_path=state_path,
        transport=lambda *_: True,
        clock=lambda: 1_000,
    )
    start.wait()
    results.put([agent.send(state="healthy").heartbeat.nonce for _ in range(sends)])


def test_builds_existing_signed_heartbeat_and_returns_acknowledgement(tmp_path: Path):
    delivered = []
    acknowledgement = {"accepted": True, "server_nonce": 1}
    agent = _agent(
        tmp_path / "heartbeat-state.json",
        lambda heartbeat, signature: delivered.append((heartbeat, signature))
        or acknowledgement,
    )

    receipt = agent.send(state="healthy", detail="local checks passed")

    assert receipt.acknowledgement is acknowledgement
    assert receipt.heartbeat.node_id == "anvil"
    assert receipt.heartbeat.timestamp == 1_000
    assert receipt.heartbeat.nonce == 1
    assert receipt.signature == sign_heartbeat(receipt.heartbeat, KEY)
    assert delivered == [(receipt.heartbeat, receipt.signature)]
    assert KEY.hex() not in repr(agent)


def test_nonce_persists_monotonically_across_restart(tmp_path: Path):
    path = tmp_path / "heartbeat-state.json"
    acknowledgements = []
    first = _agent(path, lambda heartbeat, _signature: acknowledgements.append(
        heartbeat.nonce) or {"accepted": True})
    assert first.send(state="healthy").heartbeat.nonce == 1
    assert first.send(state="healthy").heartbeat.nonce == 2

    restarted = _agent(path, lambda heartbeat, _signature: acknowledgements.append(
        heartbeat.nonce) or {"accepted": True})
    assert restarted.last_nonce == 2
    assert restarted.send(state="healthy").heartbeat.nonce == 3
    assert acknowledgements == [1, 2, 3]


def test_nonce_file_is_owner_only_json(tmp_path: Path):
    path = tmp_path / "heartbeat-state.json"
    _agent(path, lambda *_: {"accepted": True}).send(state="healthy")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {"last_nonce": 1, "node_id": "anvil", "version": 1}
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600
        lock_path = path.with_name(f"{path.name}.lock")
        assert lock_path.is_file()
        assert not lock_path.is_symlink()
        assert lock_path.stat().st_mode & 0o777 == 0o600


def test_processes_reserve_unique_monotonic_nonces(tmp_path: Path):
    path = tmp_path / "heartbeat-state.json"
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    results = context.Queue()
    processes = [
        context.Process(
            target=_concurrent_sender,
            args=(str(path), 8, start, results),
        )
        for _ in range(3)
    ]
    for process in processes:
        process.start()
    start.set()
    sequences = [results.get(timeout=15) for _ in processes]
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0

    reserved = [nonce for sequence in sequences for nonce in sequence]
    assert sorted(reserved) == list(range(1, 25))
    assert all(
        earlier < later
        for sequence in sequences
        for earlier, later in zip(sequence, sequence[1:])
    )
    restarted = _agent(path, lambda *_: True)
    assert restarted.last_nonce == 24
    assert restarted.send(state="healthy").heartbeat.nonce == 25


def test_atomic_update_failure_keeps_previous_nonce_and_skips_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = tmp_path / "heartbeat-state.json"
    delivered = []
    agent = _agent(
        path, lambda heartbeat, _signature: delivered.append(heartbeat.nonce)
        or {"accepted": True})
    agent.send(state="healthy")

    def fail_replace(_source, _destination, **_kwargs):
        raise OSError("simulated atomic replacement failure")

    monkeypatch.setattr("orca.heartbeat_agent.os.replace", fail_replace)
    with pytest.raises(HeartbeatStateError, match="could not be advanced"):
        agent.send(state="healthy")

    assert json.loads(path.read_text(encoding="utf-8"))["last_nonce"] == 1
    assert delivered == [1]
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.parametrize(
    "payload",
    [
        "not-json",
        json.dumps({"version": 1, "node_id": "anvil", "last_nonce": True}),
        json.dumps({"version": 1, "node_id": "kiln", "last_nonce": 4}),
        json.dumps({"version": 1, "node_id": "anvil", "last_nonce": -1}),
    ],
)
def test_corrupt_or_mismatched_state_fails_closed(tmp_path: Path, payload: str):
    path = tmp_path / "heartbeat-state.json"
    path.write_text(payload, encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(HeartbeatStateError):
        _agent(path, lambda *_: {"accepted": True})


def test_state_rejects_broad_permissions_and_symlinks(tmp_path: Path):
    path = tmp_path / "heartbeat-state.json"
    _agent(path, lambda *_: {"accepted": True}).send(state="healthy")
    if os.name == "posix":
        path.chmod(0o640)
        with pytest.raises(HeartbeatStateError, match="group or others"):
            _agent(path, lambda *_: {"accepted": True})
        path.chmod(0o600)

    link = tmp_path / "heartbeat-link.json"
    link.symlink_to(path)
    with pytest.raises(HeartbeatStateError, match="non-symlink"):
        _agent(link, lambda *_: {"accepted": True})


def test_lock_rejects_broad_permissions_and_symlinks(tmp_path: Path):
    path = tmp_path / "heartbeat-state.json"
    lock_path = path.with_name(f"{path.name}.lock")
    lock_path.write_text("", encoding="utf-8")
    if os.name == "posix":
        lock_path.chmod(0o640)
        with pytest.raises(HeartbeatStateError, match="group or others"):
            _agent(path, lambda *_: True).send(state="healthy")
        lock_path.unlink()

    target = tmp_path / "lock-target"
    target.write_text("", encoding="utf-8")
    target.chmod(0o600)
    lock_path.symlink_to(target)
    with pytest.raises(HeartbeatStateError, match="lock is unavailable"):
        _agent(path, lambda *_: True).send(state="healthy")


def test_state_parent_rejects_symlink_and_group_or_world_write(tmp_path: Path):
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir(mode=0o700)
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(HeartbeatStateError, match="non-symlink directory"):
        _agent(linked_parent / "heartbeat-state.json", lambda *_: True)

    for mode in (0o720, 0o702):
        insecure_parent = tmp_path / f"insecure-{mode:o}"
        insecure_parent.mkdir(mode=mode)
        insecure_parent.chmod(mode)
        with pytest.raises(HeartbeatStateError, match="group or world writable"):
            _agent(insecure_parent / "heartbeat-state.json", lambda *_: True)


def test_state_parent_must_be_owned_by_current_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    effective_uid = os.geteuid()
    monkeypatch.setattr(
        "orca.heartbeat_agent.os.geteuid", lambda: effective_uid + 1)
    with pytest.raises(HeartbeatStateError, match="owned by the current user"):
        _agent(tmp_path / "heartbeat-state.json", lambda *_: True)


def test_parent_symlink_swap_after_initialization_fails_closed(tmp_path: Path):
    state_parent = tmp_path / "state-parent"
    state_parent.mkdir(mode=0o700)
    replacement = tmp_path / "replacement"
    replacement.mkdir(mode=0o700)
    path = state_parent / "heartbeat-state.json"
    agent = _agent(path, lambda *_: True)

    moved_parent = tmp_path / "moved-parent"
    state_parent.rename(moved_parent)
    state_parent.symlink_to(replacement, target_is_directory=True)

    with pytest.raises(HeartbeatStateError, match="non-symlink directory"):
        agent.send(state="healthy")
    assert not (replacement / "heartbeat-state.json").exists()
    assert not (replacement / "heartbeat-state.json.lock").exists()


def test_live_rollback_removing_lock_and_state_fails_closed_across_restart(
    tmp_path: Path,
):
    path = tmp_path / "heartbeat-state.json"
    lock_path = path.with_name(f"{path.name}.lock")
    delivered = []
    agent = _agent(
        path,
        lambda heartbeat, _signature: delivered.append(heartbeat.nonce) or True,
    )
    assert agent.send(state="healthy").heartbeat.nonce == 1

    path.unlink()
    lock_path.unlink()
    with pytest.raises(HeartbeatStateError, match="state disappeared"):
        agent.send(state="healthy")
    assert delivered == [1]
    assert not path.exists()
    assert lock_path.exists()

    restarted = _agent(path, lambda *_: True)
    with pytest.raises(HeartbeatStateError, match="state disappeared"):
        restarted.send(state="healthy")


def test_transport_failure_consumes_nonce_and_never_reuses_it_after_restart(
    tmp_path: Path,
):
    path = tmp_path / "heartbeat-state.json"
    attempted = []

    def fail_transport(heartbeat, _signature):
        attempted.append(heartbeat.nonce)
        raise ConnectionError("simulated offline transport")

    agent = _agent(path, fail_transport)
    with pytest.raises(HeartbeatDeliveryError, match="delivery failed"):
        agent.send(state="healthy")
    assert agent.last_nonce == 1

    restarted = _agent(
        path,
        lambda heartbeat, _signature: attempted.append(heartbeat.nonce)
        or {"accepted": True},
    )
    receipt = restarted.send(state="healthy")
    assert receipt.heartbeat.nonce == 2
    assert attempted == [1, 2]


def test_missing_acknowledgement_also_consumes_nonce(tmp_path: Path):
    path = tmp_path / "heartbeat-state.json"
    with pytest.raises(HeartbeatDeliveryError, match="not acknowledged"):
        _agent(path, lambda *_: None).send(state="healthy")
    receipt = _agent(path, lambda *_: {"accepted": True}).send(state="healthy")
    assert receipt.heartbeat.nonce == 2


@pytest.mark.parametrize(
    "acknowledgement",
    [
        False,
        1,
        "accepted",
        {},
        {"accepted": False},
        {"accepted": True, "rejected": True},
        {"accepted": True, "status": "rejected"},
    ],
)
def test_only_explicit_positive_acknowledgements_succeed_and_rejections_burn_nonce(
    tmp_path: Path, acknowledgement
):
    path = tmp_path / "heartbeat-state.json"
    with pytest.raises(HeartbeatDeliveryError, match="not acknowledged"):
        _agent(path, lambda *_: acknowledgement).send(state="healthy")
    receipt = _agent(path, lambda *_: True).send(state="healthy")
    assert receipt.heartbeat.nonce == 2


def test_transport_exception_is_sanitized_and_burns_nonce(tmp_path: Path):
    path = tmp_path / "heartbeat-state.json"
    secret = "api_key=sk-synthetic-heartbeat-secret"

    def fail_transport(*_):
        raise ConnectionError(secret)

    with pytest.raises(HeartbeatDeliveryError, match="delivery failed") as captured:
        _agent(path, fail_transport).send(state="healthy")
    assert secret not in str(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert _agent(path, lambda *_: True).send(state="healthy").heartbeat.nonce == 2


@pytest.mark.parametrize("state", ["", "HEALTHY", "unknown", 1, None])
def test_invalid_state_is_rejected_before_nonce_reservation(tmp_path: Path, state):
    path = tmp_path / "heartbeat-state.json"
    with pytest.raises(ValueError, match="healthy, degraded, or offline"):
        _agent(path, lambda *_: True).send(state=state)
    assert not path.exists()
    assert not path.with_name(f"{path.name}.lock").exists()


def test_detail_is_locally_type_and_size_bounded_before_nonce_reservation(
    tmp_path: Path,
):
    path = tmp_path / "heartbeat-state.json"
    agent = _agent(path, lambda *_: True)
    with pytest.raises(ValueError, match="string"):
        agent.send(state="healthy", detail=1)
    with pytest.raises(ValueError, match="size limit"):
        agent.send(state="healthy", detail="x" * 4_001)
    assert not path.exists()
    assert agent.send(state="healthy", detail="x" * 4_000).heartbeat.nonce == 1
