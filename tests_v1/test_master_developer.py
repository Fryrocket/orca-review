from pathlib import Path

from orca.master_developer import (
    MasterDeveloperBroker, MasterDeveloperSessionStore, master_developer_turn)


class PlanningGateway:
    tool_broker = None

    def __init__(self, plans):
        self.plans = list(plans)

    def master_developer_plan(self, **_payload):
        return self.plans.pop(0)


def test_master_developer_message_authorizes_write_test_and_response(monkeypatch, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "sample.py").write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setenv("ORCA_MASTER_SOURCE_ROOT", str(source))
    monkeypatch.setenv("ORCA_MASTER_WORKSPACE", str(tmp_path / "workspace"))
    store = MasterDeveloperSessionStore(tmp_path / "artifacts")
    session = store.create()
    gateway = PlanningGateway([
        {"reason": "Apply the requested technical edit", "actions": [
            {"name": "file.write", "arguments": {"path": "sample.py", "content": "VALUE = 2\n"}}]},
        {"reason": "Report verified completion", "actions": [
            {"name": "respond", "arguments": {"message": "Updated sample.py with rollback preserved."}}]},
    ])
    completed = master_developer_turn(
        store, gateway, tmp_path / "artifacts", session["session_id"], "Update the value.")
    assert completed["state"] == "idle"
    assert (tmp_path / "workspace" / "sample.py").read_text() == "VALUE = 2\n"
    assert completed["messages"][-1]["role"] == "assistant"
    assert any(message.get("tool_name") == "file.write" for message in completed["messages"])


def test_master_developer_capabilities_cover_connected_and_technical_surfaces():
    capabilities = " ".join(MasterDeveloperBroker.capabilities())
    for phrase in ("repository", "tests", "restart", "deploy", "rollback",
                   "Google Drive", "Notion", "Linear", "web", "browser"):
        assert phrase.casefold() in capabilities.casefold()
