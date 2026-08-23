"""Persist + dashboard wiring against the guarded Blackboard."""

import pytest

from mao.blackboard import Blackboard
from mao.bus import MessageBus
from mao.errors import HardPrivilegeError, OrcaConfigError
from mao.persist import load_blackboard, save_blackboard, save_bus
from mao.roles import Privilege, PrivilegeBroker


def test_persist_roundtrip_uses_writer_not_author(tmp_path):
    broker = PrivilegeBroker(enforce=True)
    board = Blackboard(guard=lambda writer, key: broker.require(writer, Privilege.WRITE))
    board.commit("k", "v1", writer="grok", note="first")
    path = tmp_path / "board.json"
    save_blackboard(board, path)

    restored = Blackboard(guard=lambda writer, key: broker.require(writer, Privilege.WRITE))
    load_blackboard(path, restored)
    assert restored.get("k") == "v1"
    entry = restored.get_entry("k")
    assert entry.writer == "grok"
    assert entry.meta.get("note") == "first"


def test_persist_load_requires_guarded_board(tmp_path):
    with pytest.raises(OrcaConfigError, match=r"guard"):
        Blackboard()
    with pytest.raises(OrcaConfigError, match=r"guarded Blackboard"):
        load_blackboard(tmp_path / "missing.json", None)


def test_persist_denied_writer_does_not_mutate(tmp_path):
    broker = PrivilegeBroker(enforce=True)
    src = Blackboard(guard=lambda writer, key: None)
    src.commit("secret", "x", writer="claude")
    path = tmp_path / "board.json"
    save_blackboard(src, path)

    dst = Blackboard(guard=lambda writer, key: broker.require(writer, Privilege.WRITE))
    with pytest.raises(HardPrivilegeError):
        load_blackboard(path, dst)
    assert "secret" not in dst


def test_save_bus_uses_history(tmp_path):
    bus = MessageBus()
    bus.publish("grok", "hello", topic="step")
    path = tmp_path / "bus.json"
    save_bus(bus, path)
    data = path.read_text()
    assert "hello" in data
    assert "step" in data


def test_dashboard_state_constructs_with_guard(tmp_path, monkeypatch):
    import mao.web_ui.server as server

    monkeypatch.setenv("ORCA_PROFILE", "")
    monkeypatch.setenv("ORCA_REPO_ROOT", str(tmp_path))
    monkeypatch.delenv("ORCA_API_KEY", raising=False)
    monkeypatch.delenv("MAO_API_KEY", raising=False)
    (tmp_path / "runs").mkdir(exist_ok=True)
    monkeypatch.setattr(server, "STATE", None)
    st = server.DashboardState()
    assert st.memory is st.orch.memory
    with pytest.raises(HardPrivilegeError):
        st.memory.commit("k", "v", writer="claude")
    st.memory.commit("k", "v", writer="grok")
    snap = st.snapshot()
    assert "privileges" in snap
    assert snap["bus"] == []
    server._publish(st.bus, "ui.turn.start", {"agent": "claude"})
    snap = st.snapshot()
    assert snap["bus"][0]["topic"] == "ui.turn.start"
    assert snap["bus"][0]["sender"] == "ui"
    assert "id" in snap["bus"][0]
