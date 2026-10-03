import json
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


def test_large_tool_evidence_is_compacted_before_the_next_planning_pass(monkeypatch, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "large.md").write_text("A" * 70_000, encoding="utf-8")
    monkeypatch.setenv("ORCA_MASTER_SOURCE_ROOT", str(source))
    monkeypatch.setenv("ORCA_MASTER_WORKSPACE", str(tmp_path / "workspace"))
    seen = []

    class Gateway:
        tool_broker = None

        def master_developer_plan(self, **payload):
            seen.append(payload["evidence"])
            if len(seen) == 1:
                return {"reason": "Inspect the large record", "actions": [
                    {"name": "file.read", "arguments": {"path": "large.md"}}]}
            return {"reason": "Report the bounded result", "actions": [
                {"name": "respond", "arguments": {"message": "Inspection completed."}}]}

    store = MasterDeveloperSessionStore(tmp_path / "artifacts")
    session = store.create()
    result = master_developer_turn(
        store, Gateway(), tmp_path / "artifacts", session["session_id"], "Inspect it.")
    assert result["state"] == "idle"
    assert len(json.dumps(seen[1])) < 5_000
    assert seen[1][0]["truncated_for_planning"] is True
    assert result["messages"][-1]["evidence"][0]["truncated_for_planning"] is True


def test_planning_provider_failure_becomes_a_durable_failed_reply(tmp_path):
    class FailingGateway:
        tool_broker = None

        def master_developer_plan(self, **_payload):
            raise TimeoutError("private upstream detail")

    store = MasterDeveloperSessionStore(tmp_path / "artifacts")
    session = store.create()
    result = master_developer_turn(
        store, FailingGateway(), tmp_path / "artifacts", session["session_id"], "Audit it.")
    assert result["state"] == "failed"
    assert result["messages"][-1]["role"] == "assistant"
    assert "TimeoutError" in result["messages"][-1]["content"]
    assert "private upstream detail" not in result["messages"][-1]["content"]


def test_sixth_planning_pass_is_forced_to_synthesize_a_reply(monkeypatch, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "state.md").write_text("verified\n", encoding="utf-8")
    monkeypatch.setenv("ORCA_MASTER_SOURCE_ROOT", str(source))
    monkeypatch.setenv("ORCA_MASTER_WORKSPACE", str(tmp_path / "workspace"))
    finals = []

    class Gateway:
        tool_broker = None

        def master_developer_plan(self, **payload):
            finals.append(payload.get("final"))
            if payload.get("final"):
                return {"reason": "Synthesize bounded evidence", "actions": [
                    {"name": "respond", "arguments": {
                        "message": "Verified state read; inaccessible sources are labeled."}}]}
            return {"reason": "Continue bounded inspection", "actions": [
                {"name": "file.read", "arguments": {"path": "state.md"}}]}

    store = MasterDeveloperSessionStore(tmp_path / "artifacts")
    session = store.create()
    result = master_developer_turn(
        store, Gateway(), tmp_path / "artifacts", session["session_id"], "Catch up.")
    assert finals == [False, False, False, False, False, True]
    assert result["state"] == "idle"
    assert result["messages"][-1]["content"].startswith("Verified state")


def test_audit_snapshot_exposes_release_session_and_external_record_evidence(
        monkeypatch, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "state.md").write_text("state\n", encoding="utf-8")
    monkeypatch.setenv("ORCA_MASTER_SOURCE_ROOT", str(source))
    monkeypatch.setenv("ORCA_MASTER_WORKSPACE", str(tmp_path / "workspace"))

    class Result:
        def __init__(self, output): self.output = output

    class ToolBroker:
        def execute(self, *, bot_id, requests):
            assert bot_id == "orca"
            request = requests[0]
            if request.name == "node.observe":
                return [Result({"nodes": [{"id": "forge", "state": "healthy"}]})]
            if request.name == "studio.capabilities":
                return [Result({"read_tools": ["drive.read"]})]
            if request.name == "drive.read":
                return [Result({"path": request.arguments["path"], "text": "snapshot"})]
            raise AssertionError(request.name)

    class Gateway:
        tool_broker = ToolBroker()

    artifacts = tmp_path / "artifacts"
    master = artifacts / "master-developer-sessions"
    master.mkdir(parents=True)
    (master / "master_123456789012345678901234.json").write_text(json.dumps({
        "session_id": "master_123456789012345678901234", "created_at": "1",
        "updated_at": "2", "state": "idle", "messages": [{"role": "assistant"}],
    }), encoding="utf-8")
    broker = MasterDeveloperBroker(Gateway(), artifacts)
    monkeypatch.setattr("orca.master_developer.urlopen", lambda *_a, **_k: None)
    snapshot = broker.execute("audit.snapshot", {})
    assert snapshot["external_records"]["status"] == "available"
    assert snapshot["sessions"]["master"]["count"] == 1
    assert snapshot["releases"]["current"]["path"] == "/opt/orca/current"
    assert snapshot["mutated"] is False
    assert snapshot["fleet"]["nodes"][0] == {
        "id": "forge", "name": None, "state": "healthy", "last_verified": None,
        "paused": None, "pause_reasons": None, "detail": None,
        "remote_execution_enabled": None}
    assert snapshot["studio"]["read_tools"] == ["drive.read"]


def test_planner_contract_failure_retries_before_failing(tmp_path):
    calls = []

    class Gateway:
        tool_broker = None

        def master_developer_plan(self, **payload):
            calls.append(payload["prompt"])
            if len(calls) == 1:
                raise ValueError("malformed contract")
            return {"reason": "Answer after contract retry", "actions": [
                {"name": "respond", "arguments": {"message": "Recovered reply."}}]}

    store = MasterDeveloperSessionStore(tmp_path / "artifacts")
    session = store.create()
    result = master_developer_turn(
        store, Gateway(), tmp_path / "artifacts", session["session_id"], "Status.")
    assert result["state"] == "idle"
    assert result["messages"][-1]["content"] == "Recovered reply."
    assert len(calls) == 2
    assert "Contract retry" in calls[1]


def test_audit_uses_deterministic_read_only_start_after_two_contract_failures(
        monkeypatch, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "state.md").write_text("state\n", encoding="utf-8")
    monkeypatch.setenv("ORCA_MASTER_SOURCE_ROOT", str(source))
    monkeypatch.setenv("ORCA_MASTER_WORKSPACE", str(tmp_path / "workspace"))
    plans = []

    class Result:
        output = {}

    class ToolBroker:
        def execute(self, **_kwargs): return [Result()]

    class Gateway:
        tool_broker = ToolBroker()

        def master_developer_plan(self, **payload):
            plans.append(payload)
            if len(plans) <= 2:
                raise ValueError("malformed contract")
            return {"reason": "Report collected evidence", "actions": [
                {"name": "respond", "arguments": {"message": "Audit evidence collected."}}]}

    store = MasterDeveloperSessionStore(tmp_path / "artifacts")
    session = store.create()
    result = master_developer_turn(
        store, Gateway(), tmp_path / "artifacts", session["session_id"],
        "Catch yourself up and reconcile all available records.")
    assert result["state"] == "idle"
    tool_names = [item.get("tool_name") for item in result["messages"]]
    assert "audit.snapshot" in tool_names
    assert "repository.inspect" in tool_names
    assert "sessions.inspect" in tool_names
