import json
from pathlib import Path
import sys

import pytest

from orca.master_developer import (
    MasterDeveloperBroker, MasterDeveloperSessionStore, _acceptance_followup,
    _acceptance_summary, _prompt_requires_workspace_write,
    master_developer_turn)
from orca.runtime import ModelRuntimeGateway


class PlanningGateway:
    tool_broker = None

    def __init__(self, plans):
        self.plans = list(plans)

    def master_developer_plan(self, **_payload):
        return self.plans.pop(0)


def test_master_planner_prioritizes_named_code_before_acceptance(monkeypatch):
    captured = {}

    def transport(_endpoint, payload, _timeout):
        captured.update(payload)
        return {"choices": [{"message": {"content": json.dumps({
            "reason": "inspect target", "actions": [{
                "name": "file.read", "arguments_json": '{"path":"sample.py"}'}],
        })}}]}

    monkeypatch.setattr("orca.runtime.bounded_json_transport", transport)
    gateway = ModelRuntimeGateway(enabled_services={"kiln_codex"})
    gateway._definitions["kiln_codex"] = ("http://example.invalid", "test", {"orca"})
    gateway.master_developer_plan(prompt="Extend sample.py")
    system = captured["messages"][0]["content"]
    assert "prioritize the named implementation" in system
    assert "file.write to implement it before testing" in system


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


def test_audit_completes_deterministically_when_provider_contract_never_recovers(
        monkeypatch, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "docs").mkdir()
    (source / "docs" / "STATE_v12_upload.md").write_text(
        "verified state\n", encoding="utf-8")
    monkeypatch.setenv("ORCA_MASTER_SOURCE_ROOT", str(source))
    monkeypatch.setenv("ORCA_MASTER_WORKSPACE", str(tmp_path / "workspace"))

    class Result:
        def __init__(self, output): self.output = output

    class ToolBroker:
        def execute(self, *, requests, **_kwargs):
            request = requests[0]
            if request.name == "health.check":
                return [Result({"status": "healthy", "integrity_valid": True})]
            if request.name == "node.observe":
                return [Result({"nodes": [{"id": "forge", "name": "FORGE",
                    "state": "healthy", "paused": False,
                    "last_verified": "now", "detail": "healthy"}],
                    "paused_nodes": []})]
            if request.name == "studio.capabilities":
                return [Result({"read_tools": ["drive.read"]})]
            if request.name == "drive.read":
                return [Result({"path": request.arguments["path"], "text": "records"})]
            raise AssertionError(request.name)

    class Gateway:
        tool_broker = ToolBroker()

        def master_developer_plan(self, **_payload):
            raise ValueError("malformed contract forever")

    store = MasterDeveloperSessionStore(tmp_path / "artifacts")
    session = store.create()
    result = master_developer_turn(
        store, Gateway(), tmp_path / "artifacts", session["session_id"],
        "Catch yourself up and reconcile all available records.")
    assert result["state"] == "idle", result["messages"][-12:]
    assert "deterministic evidence recovery" in result["messages"][-1]["content"]
    assert "Provider JSON failed repeatedly" in result["messages"][-1]["content"]
    tool_names = [item.get("tool_name") for item in result["messages"]]
    assert "drive.read" in tool_names
    assert "health.check" in tool_names
    assert "node.observe" in tool_names


def test_clean_master_workspace_refreshes_and_dirty_workspace_is_preserved(
        monkeypatch, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    tracked = source / "sample.py"
    tracked.write_text("VALUE = 1\n", encoding="utf-8")
    workspace = tmp_path / "workspace"
    artifacts = tmp_path / "artifacts"
    monkeypatch.setenv("ORCA_MASTER_SOURCE_ROOT", str(source))
    monkeypatch.setenv("ORCA_MASTER_WORKSPACE", str(workspace))

    class Gateway:
        tool_broker = None

    MasterDeveloperBroker(Gateway(), artifacts)
    assert (workspace / "sample.py").read_text() == "VALUE = 1\n"
    tracked.write_text("VALUE = 2\n", encoding="utf-8")
    MasterDeveloperBroker(Gateway(), artifacts)
    assert (workspace / "sample.py").read_text() == "VALUE = 2\n"
    assert list((artifacts / "master-developer-rollback").glob("workspace-refresh-*"))

    (workspace / "sample.py").write_text("OWNER CHANGE\n", encoding="utf-8")
    tracked.write_text("VALUE = 3\n", encoding="utf-8")
    MasterDeveloperBroker(Gateway(), artifacts)
    assert (workspace / "sample.py").read_text() == "OWNER CHANGE\n"


def test_master_developer_uses_verified_configured_test_python(monkeypatch, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    monkeypatch.setenv("ORCA_MASTER_SOURCE_ROOT", str(source))
    monkeypatch.setenv("ORCA_MASTER_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("ORCA_MASTER_TEST_PYTHON", sys.executable)

    class Gateway:
        tool_broker = None

    broker = MasterDeveloperBroker(Gateway(), tmp_path / "artifacts")
    assert broker._test_python() == Path(sys.executable)


def test_master_developer_rejects_invalid_test_target(monkeypatch, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    monkeypatch.setenv("ORCA_MASTER_SOURCE_ROOT", str(source))
    monkeypatch.setenv("ORCA_MASTER_WORKSPACE", str(tmp_path / "workspace"))

    class Gateway:
        tool_broker = None

    broker = MasterDeveloperBroker(Gateway(), tmp_path / "artifacts")
    with pytest.raises(ValueError, match="focused or full"):
        broker.execute("tests.run", {"target": "arbitrary"})


def test_master_developer_test_environment_is_isolated(monkeypatch, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    monkeypatch.setenv("ORCA_MASTER_SOURCE_ROOT", str(source))
    monkeypatch.setenv("ORCA_MASTER_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("ORCA_ENABLED_MODEL_SERVICES", "must-not-leak")

    class Gateway:
        tool_broker = None

    broker = MasterDeveloperBroker(Gateway(), tmp_path / "artifacts")
    environment = broker._test_environment()
    assert "ORCA_ENABLED_MODEL_SERVICES" not in environment
    assert environment["PYTHONPATH"] == str(broker.workspace)
    assert environment["PYTHONDONTWRITEBYTECODE"] == "1"
    assert "no:cacheprovider" in environment["PYTEST_ADDOPTS"]


def test_test_receipt_is_labeled_and_kept_outside_workspace(monkeypatch, tmp_path):
    source = tmp_path / "source"
    (source / "tests_v1").mkdir(parents=True)
    (source / "tests_v1" / "test_ok.py").write_text(
        "def test_ok(): assert True\n", encoding="utf-8")
    workspace = tmp_path / "workspace"
    artifacts = tmp_path / "artifacts"
    monkeypatch.setenv("ORCA_MASTER_SOURCE_ROOT", str(source))
    monkeypatch.setenv("ORCA_MASTER_WORKSPACE", str(workspace))
    monkeypatch.setenv("ORCA_MASTER_TEST_PYTHON", sys.executable)

    class Gateway:
        tool_broker = None

    broker = MasterDeveloperBroker(Gateway(), artifacts)
    result = broker.execute("tests.run", {"target": "focused"})
    assert result["passed"] is True
    assert result["target"] == "focused"
    assert not (workspace / ".master-test.json").exists()
    receipt = json.loads((artifacts / "master-test-receipts" / "latest.json").read_text())
    assert receipt["target"] == "focused"
    assert receipt["results"]["focused"]["passed"] is True


def test_test_receipts_preserve_focused_and_full_results(monkeypatch, tmp_path):
    source = tmp_path / "source"
    (source / "tests").mkdir(parents=True)
    (source / "tests_v1").mkdir()
    (source / "tests" / "test_legacy_ok.py").write_text("def test_ok(): assert True\n")
    (source / "tests_v1" / "test_current_ok.py").write_text(
        "def test_ok_v1(): assert True\n")
    artifacts = tmp_path / "artifacts"
    monkeypatch.setenv("ORCA_MASTER_SOURCE_ROOT", str(source))
    monkeypatch.setenv("ORCA_MASTER_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("ORCA_MASTER_TEST_PYTHON", sys.executable)

    class Gateway:
        tool_broker = None

    broker = MasterDeveloperBroker(Gateway(), artifacts)
    assert broker.execute("tests.run", {"target": "focused"})["passed"] is True
    assert broker.execute("tests.run", {"target": "full"})["passed"] is True
    receipt = json.loads((artifacts / "master-test-receipts" / "latest.json").read_text())
    assert set(receipt["results"]) == {"focused", "full"}


def test_git_diff_ignores_bytecode_and_includes_test_receipts(monkeypatch, tmp_path):
    source = tmp_path / "source"
    (source / "__pycache__").mkdir(parents=True)
    (source / "__pycache__" / "sample.pyc").write_bytes(b"source cache")
    (source / "sample.py").write_text("VALUE = 1\n")
    artifacts = tmp_path / "artifacts"
    monkeypatch.setenv("ORCA_MASTER_SOURCE_ROOT", str(source))
    monkeypatch.setenv("ORCA_MASTER_WORKSPACE", str(tmp_path / "workspace"))

    class Gateway:
        tool_broker = None

    broker = MasterDeveloperBroker(Gateway(), artifacts)
    (broker.workspace / "sample.py").write_text("VALUE = 2\n")
    (broker.workspace / "__pycache__").mkdir(exist_ok=True)
    (broker.workspace / "__pycache__" / "other.pyc").write_bytes(b"workspace cache")
    receipt_dir = artifacts / "master-test-receipts"
    receipt_dir.mkdir(parents=True)
    (receipt_dir / "latest.json").write_text('{"results":{"focused":{"passed":true}}}\n')
    result = broker.execute("git.diff", {})
    assert result["files"] == ["sample.py"]
    assert "__pycache__" not in result["diff"]
    assert result["test_receipts"]["results"]["focused"]["passed"] is True


def test_acceptance_followup_enforces_focused_full_then_final_diff():
    prompt = "Run focused and full regression and inspect the final diff."
    evidence = []
    assert _acceptance_followup(prompt, evidence) == {
        "name": "tests.run", "arguments": {"target": "focused"}}
    evidence.append({"name": "tests.run", "status": "completed", "output": {
        "target": "focused", "passed": True}})
    assert _acceptance_followup(prompt, evidence) == {
        "name": "tests.run", "arguments": {"target": "full"}}
    evidence.append({"name": "tests.run", "status": "completed", "output": {
        "target": "full", "passed": True}})
    assert _acceptance_followup(prompt, evidence) == {
        "name": "git.diff", "arguments": {}}
    evidence.append({"name": "git.diff", "status": "completed", "output": {
        "files": ["sample.py"], "test_receipts": {"results": {
            "focused": {"passed": True}, "full": {"passed": True}}}}})
    assert _acceptance_followup(prompt, evidence) is None


def test_acceptance_followup_requires_full_after_latest_focused():
    prompt = "Run focused and full regression and inspect the final diff."
    evidence = [
        {"name": "tests.run", "status": "completed", "output": {
            "target": "full", "passed": True}},
        {"name": "tests.run", "status": "completed", "output": {
            "target": "focused", "passed": True}},
    ]
    assert _acceptance_followup(prompt, evidence) == {
        "name": "tests.run", "arguments": {"target": "full"}}


def test_acceptance_summary_closes_a_proven_sequence_deterministically():
    prompt = "Run focused and full regression and inspect the final diff."
    evidence = [
        {"name": "tests.run", "status": "completed", "output": {
            "target": "focused", "passed": True}},
        {"name": "tests.run", "status": "completed", "output": {
            "target": "full", "passed": True}},
        {"name": "git.diff", "status": "completed", "output": {
            "files": ["orca/readiness_probe.py"], "test_receipts": {"results": {
                "focused": {"passed": True}, "full": {"passed": True}}}}},
    ]
    summary = _acceptance_summary(prompt, evidence)
    assert summary is not None
    assert "Acceptance passed" in summary
    assert "orca/readiness_probe.py" in summary


def test_acceptance_summary_rejects_stale_diff():
    prompt = "Run focused and full regression and inspect the final diff."
    evidence = [
        {"name": "git.diff", "status": "completed", "output": {
            "files": [], "test_receipts": {"results": {
                "focused": {"passed": True}, "full": {"passed": True}}}}},
        {"name": "tests.run", "status": "completed", "output": {
            "target": "focused", "passed": True}},
        {"name": "tests.run", "status": "completed", "output": {
            "target": "full", "passed": True}},
    ]
    assert _acceptance_summary(prompt, evidence) is None


def test_acceptance_turn_overrides_out_of_order_planner_action(monkeypatch, tmp_path):
    source = tmp_path / "source"
    (source / "tests").mkdir(parents=True)
    (source / "tests_v1").mkdir()
    (source / "tests" / "test_old.py").write_text("def test_old(): assert True\n")
    (source / "tests_v1" / "test_new.py").write_text("def test_new(): assert True\n")
    monkeypatch.setenv("ORCA_MASTER_SOURCE_ROOT", str(source))
    monkeypatch.setenv("ORCA_MASTER_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("ORCA_MASTER_TEST_PYTHON", sys.executable)
    store = MasterDeveloperSessionStore(tmp_path / "artifacts")
    session = store.create()
    gateway = PlanningGateway([
        {"reason": "Try to skip focused", "actions": [
            {"name": "tests.run", "arguments": {"target": "full"}}]},
        {"reason": "Try to skip full", "actions": [
            {"name": "git.diff", "arguments": {}}]},
        {"reason": "Try to rerun focused", "actions": [
            {"name": "tests.run", "arguments": {"target": "focused"}}]},
        {"reason": "Try to reopen the loop", "actions": [
            {"name": "tests.run", "arguments": {"target": "focused"}}]},
    ])
    result = master_developer_turn(
        store, gateway, tmp_path / "artifacts", session["session_id"],
        "Run focused and full regression and inspect the final diff.")
    tools = [message.get("tool_name") for message in result["messages"]
             if message.get("role") == "tool" and message.get("content", "").startswith("Running")]
    assert tools == ["tests.run", "tests.run", "git.diff"]
    assert result["state"] == "idle"
    assert "Acceptance passed" in result["messages"][-1]["content"]


def test_acceptance_turn_allows_implementation_before_tests(monkeypatch, tmp_path):
    source = tmp_path / "source"
    (source / "tests").mkdir(parents=True)
    (source / "tests_v1").mkdir()
    (source / "tests" / "test_old.py").write_text("def test_old(): assert True\n")
    (source / "tests_v1" / "test_new.py").write_text("def test_new(): assert True\n")
    (source / "sample.py").write_text("VALUE = 1\n")
    monkeypatch.setenv("ORCA_MASTER_SOURCE_ROOT", str(source))
    monkeypatch.setenv("ORCA_MASTER_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("ORCA_MASTER_TEST_PYTHON", sys.executable)
    store = MasterDeveloperSessionStore(tmp_path / "artifacts")
    session = store.create()
    gateway = PlanningGateway([
        {"reason": "Implement first", "actions": [
            {"name": "file.write", "arguments": {
                "path": "sample.py", "content": "VALUE = 2\n"}}]},
        {"reason": "Begin acceptance", "actions": [
            {"name": "tests.run", "arguments": {"target": "focused"}}]},
        {"reason": "Try to wander", "actions": [
            {"name": "file.search", "arguments": {"query": "VALUE"}}]},
        {"reason": "Try to wander again", "actions": [
            {"name": "file.search", "arguments": {"query": "VALUE"}}]},
        {"reason": "Try to reopen", "actions": [
            {"name": "tests.run", "arguments": {"target": "focused"}}]},
    ])
    result = master_developer_turn(
        store, gateway, tmp_path / "artifacts", session["session_id"],
        "Implement sample, run focused and full regression, and inspect the final diff.")
    tools = [message.get("tool_name") for message in result["messages"]
             if message.get("role") == "tool" and message.get("content", "").startswith("Running")]
    assert tools == ["file.write", "tests.run", "tests.run", "git.diff"]
    assert (tmp_path / "workspace" / "sample.py").read_text() == "VALUE = 2\n"
    assert result["state"] == "idle"


def test_explicit_change_prompt_requires_a_workspace_write():
    assert _prompt_requires_workspace_write("Harden the parser and add tests") is True
    assert _prompt_requires_workspace_write("Verify the parser without changes") is False


def test_acceptance_turn_defers_tests_until_explicit_change_is_written(monkeypatch, tmp_path):
    source = tmp_path / "source"
    (source / "tests").mkdir(parents=True)
    (source / "tests_v1").mkdir()
    (source / "tests" / "test_old.py").write_text("def test_old(): assert True\n")
    (source / "tests_v1" / "test_new.py").write_text("def test_new(): assert True\n")
    (source / "sample.py").write_text("VALUE = 1\n")
    monkeypatch.setenv("ORCA_MASTER_SOURCE_ROOT", str(source))
    monkeypatch.setenv("ORCA_MASTER_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("ORCA_MASTER_TEST_PYTHON", sys.executable)
    store = MasterDeveloperSessionStore(tmp_path / "artifacts")
    session = store.create()
    gateway = PlanningGateway([
        {"reason": "Premature test", "actions": [
            {"name": "tests.run", "arguments": {"target": "focused"}}]},
        {"reason": "Implement after guard", "actions": [
            {"name": "file.write", "arguments": {
                "path": "sample.py", "content": "VALUE = 2\n"}}]},
        {"reason": "Start acceptance", "actions": [
            {"name": "tests.run", "arguments": {"target": "focused"}}]},
        {"reason": "Continue", "actions": [
            {"name": "file.search", "arguments": {"query": "VALUE"}}]},
        {"reason": "Continue", "actions": [
            {"name": "file.search", "arguments": {"query": "VALUE"}}]},
        {"reason": "Finish", "actions": [
            {"name": "respond", "arguments": {"message": "done"}}]},
    ])
    result = master_developer_turn(
        store, gateway, tmp_path / "artifacts", session["session_id"],
        "Harden sample, run focused and full regression, and inspect the final diff.")
    tools = [message.get("tool_name") for message in result["messages"]
             if message.get("role") == "tool" and message.get("content", "").startswith("Running")]
    assert tools == ["file.write", "tests.run", "tests.run", "git.diff"]
    assert any(item.get("name") == "acceptance.guard"
               for item in result["messages"][-1]["evidence"])
    assert result["state"] == "idle"
