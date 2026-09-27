import pytest
from concurrent.futures import ThreadPoolExecutor

from orca.costs import CostLedger
from orca.domain import PermissionLevel
from orca.evidence import EvidenceStore
from orca.runtime import (
    DisabledRuntime,
    OfflineEvaluator,
    PROMPT_CONTRACTS,
    SandboxedLocalAdapter,
    SandboxedOpenAIAdapter,
    ModelRuntimeGateway,
)
from orca.tools import (
    BOT_TOOL_MANIFESTS, TOOL_CATALOG, ReadOnlyToolBroker, ToolAuthorizer,
    ToolRequest,
)
from orca.read_tools import WorkspaceReadTools
from orca.connector_tools import (
    GoogleDriveReadTools, PublicWebReadTools, RcloneDriveReadTools,
)
from orca.models import ModelRoute, ModelRouter


def test_prompt_contracts_are_versioned_and_complete():
    assert set(PROMPT_CONTRACTS) == {"orca", "smith", "quench", "security_gate"}
    assert all(contract.version == "1.1.0" for contract in PROMPT_CONTRACTS.values())
    assert all("evidence" in contract.required_output_fields for contract in PROMPT_CONTRACTS.values())
    assert all("Never claim an action ran" in contract.system for contract in PROMPT_CONTRACTS.values())


def test_offline_evaluator_accepts_contract_and_rejects_secrets():
    evaluator = OfflineEvaluator()
    valid = {"summary": "done", "evidence": ["test"], "uncertainty": "none", "next_gate": "review"}
    assert evaluator.evaluate("smith", valid) == (True, ())
    invalid = {**valid, "summary": "api_key=sk-abcdefghijklmnop"}
    ok, failures = evaluator.evaluate("smith", invalid)
    assert not ok
    assert "output contains secret-shaped data" in failures


def test_offline_evaluator_rejects_execution_fields_and_malformed_contracts():
    evaluator = OfflineEvaluator()
    base = {"summary": "done", "evidence": ["test"], "uncertainty": "none", "next_gate": "review"}
    ok, failures = evaluator.evaluate("smith", {**base, "tool_calls": [{"name": "shell"}]})
    assert not ok
    assert any("unexpected output fields" in failure for failure in failures)
    ok, failures = evaluator.evaluate("smith", {**base, "evidence": "not a list", "next_gate": "deploy_now"})
    assert not ok
    assert "evidence must be a list of non-empty text items" in failures
    assert "next_gate is not an allowed control-plane gate" in failures
    ok, failures = evaluator.evaluate("smith", {**base, "next_gate": []})
    assert not ok
    assert "next_gate is not an allowed control-plane gate" in failures
    ok, failures = evaluator.evaluate("smith", {**base, "summary": float("nan")})
    assert not ok
    assert "output must be JSON serializable" in failures


def test_bot_runtime_and_tools_fail_closed():
    with pytest.raises(PermissionError, match="runtime is disabled"):
        DisabledRuntime().invoke("smith", "change code")
    authorizer = ToolAuthorizer()
    assert authorizer.authorize(
        bot_id="smith", tool_name="repo.read", approved_level=PermissionLevel.R0
    ) == TOOL_CATALOG["repo.read"]
    with pytest.raises(PermissionError, match="unknown tool"):
        authorizer.authorize(bot_id="smith", tool_name="shell.any", approved_level=PermissionLevel.R3)


def test_read_only_tool_families_are_manifested_without_mutation_authority():
    assert {capability.family for capability in TOOL_CATALOG.values()} >= {
        "files", "web", "terminal", "drive"
    }
    assert all(not capability.mutates for capability in TOOL_CATALOG.values())
    required = {"file.read", "web.search", "terminal.inspect", "drive.read"}
    assert required <= BOT_TOOL_MANIFESTS["orca"]
    assert required <= BOT_TOOL_MANIFESTS["smith"]
    assert BOT_TOOL_MANIFESTS["security_gate"] == frozenset()


def test_cost_ledger_zero_budget_and_persistence(tmp_path):
    store = EvidenceStore(tmp_path / "orca.db")
    ledger = CostLedger(store.db)
    ledger.record(job_id="job", bot_id="smith", lane="orca", model="local",
                  tokens_in=10, tokens_out=5, cost_usd=0.0)
    assert ledger.summary()["total_usd"] == 0.0
    assert ledger.summary()["by_dimension"]["bot_id"][0]["key"] == "smith"
    with pytest.raises(PermissionError, match="hard cap"):
        ledger.preflight(0.01)
    restored = CostLedger(EvidenceStore(tmp_path / "orca.db").db)
    assert restored.summary()["total_usd"] == 0.0


def test_cost_ledger_rejects_negative_usage():
    ledger = CostLedger(EvidenceStore().db)
    with pytest.raises(ValueError):
        ledger.record(job_id="j", bot_id="smith", lane="orca", model="local",
                      tokens_in=-1, tokens_out=0, cost_usd=0.0)
    for invalid in (float("nan"), float("inf"), True):
        with pytest.raises(ValueError):
            ledger.record(job_id="j", bot_id="smith", lane="orca", model="local",
                          tokens_in=0, tokens_out=0, cost_usd=invalid)
    with pytest.raises(ValueError):
        ledger.record(job_id="j", bot_id="smith", lane="orca", model="local",
                      tokens_in=True, tokens_out=0, cost_usd=0.0)


def test_cost_dimensions_are_bounded_and_redacted():
    ledger = CostLedger(EvidenceStore().db)
    secret = "sk-abcdefghijklmnop"
    ledger.record(job_id=f"job-{secret}", bot_id="smith", lane="orca",
                  model=f"model-{secret}", connector="drive",
                  tokens_in=1, tokens_out=1, cost_usd=0.0)
    assert secret not in str(ledger.summary())
    with pytest.raises(ValueError, match="concise"):
        ledger.record(job_id="x" * 241, bot_id="smith", lane="orca", model="local",
                      tokens_in=0, tokens_out=0, cost_usd=0.0)


def test_cost_warning_and_hard_stop_are_deterministic():
    ledger = CostLedger(EvidenceStore().db, hard_cap_usd=1.0, warning_threshold_usd=0.5)
    ledger.record(job_id="j", bot_id="smith", lane="orca", model="test",
                  tokens_in=1, tokens_out=1, cost_usd=0.6)
    assert ledger.summary()["budget_status"] == "warning"
    assert ledger.summary()["paid_execution_authorized"] is True
    with pytest.raises(PermissionError, match="hard cap"):
        ledger.preflight(0.5)


def test_concurrent_cost_records_cannot_cross_the_approved_cap(tmp_path):
    path = tmp_path / "costs.db"
    ledgers = [
        CostLedger(EvidenceStore(path).db, hard_cap_usd=1.0),
        CostLedger(EvidenceStore(path).db, hard_cap_usd=1.0),
    ]

    def record(index):
        try:
            ledgers[index % 2].record(
                job_id=f"j{index}", bot_id="smith", lane="orca", model="test",
                tokens_in=1, tokens_out=1, cost_usd=0.25)
            return True
        except PermissionError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted = list(pool.map(record, range(8)))
    assert sum(accepted) == 4
    assert ledgers[0].summary()["total_usd"] == 1.0
    assert ledgers[0].summary()["budget_status"] == "hard_stop"


def test_cloud_model_route_requires_fry_r3_and_positive_cap():
    route = ModelRoute("coding", "local", "cloud", monthly_hard_cap_usd=1.0)
    router = ModelRouter({"coding": route})
    assert router.select("coding") == "local"
    with pytest.raises(PermissionError, match="Fry R3"):
        router.select("coding", local_capable=False, cloud_approved=True,
                      cloud_approved_by="orca", approved_level=PermissionLevel.R3,
                      estimated_cost_usd=0.1)
    assert router.select(
        "coding", local_capable=False, cloud_approved=True,
        cloud_approved_by="fry", approved_level=PermissionLevel.R3,
        estimated_cost_usd=0.1) == "cloud"
    with pytest.raises(PermissionError, match="cap"):
        router.select(
            "coding", local_capable=False, cloud_approved=True,
            cloud_approved_by="fry", approved_level=PermissionLevel.R3,
            estimated_cost_usd=1.1)
    with pytest.raises(ValueError, match="negative"):
        router.select("coding", estimated_cost_usd=-0.1)


def test_sandboxed_local_adapter_is_loopback_allowlisted_bounded_and_contract_checked():
    calls = []
    valid = {"summary": "done", "evidence": ["test"], "uncertainty": "none", "next_gate": "review"}
    adapter = SandboxedLocalAdapter(
        endpoint="http://127.0.0.1:11434/api/generate", allowed_models=("llama3.2:3b",),
        transport=lambda url, payload, timeout: calls.append((url, payload, timeout)) or
        {"response": __import__("json").dumps(valid)}, max_prompt_chars=64)
    assert adapter.invoke(bot_id="smith", model="llama3.2:3b", prompt="implement") == valid
    assert calls[0][1]["stream"] is False
    assert "tools" not in calls[0][1]
    with pytest.raises(PermissionError, match="not allowlisted"):
        adapter.invoke(bot_id="smith", model="cloud-model", prompt="implement")
    with pytest.raises(ValueError, match="exceeds"):
        adapter.invoke(bot_id="smith", model="llama3.2:3b", prompt="x" * 65)
    with pytest.raises(ValueError, match="secret-shaped"):
        adapter.invoke(
            bot_id="smith", model="llama3.2:3b",
            prompt="token=sk-abcdefghijklmnop")


def test_sandboxed_local_adapter_rejects_remote_endpoint_and_bad_output():
    with pytest.raises(ValueError, match="loopback"):
        SandboxedLocalAdapter(endpoint="https://api.example.com/api/generate",
                              allowed_models=("x",), transport=lambda *_: {})
    with pytest.raises(ValueError, match="/api/generate"):
        SandboxedLocalAdapter(
            endpoint="http://user:pass@127.0.0.1:11434/api/generate?debug=1",
            allowed_models=("x",), transport=lambda *_: {})
    with pytest.raises(ValueError, match="timeout"):
        SandboxedLocalAdapter(
            endpoint="http://127.0.0.1:11434/api/generate",
            allowed_models=("x",), transport=lambda *_: {}, timeout_seconds=0)
    adapter = SandboxedLocalAdapter(
        endpoint="http://localhost:11434/api/generate", allowed_models=("x",),
        transport=lambda *_: {"response": '{"summary":"missing fields"}'})
    with pytest.raises(ValueError, match="failed contract"):
        adapter.invoke(bot_id="quench", model="x", prompt="review")


def test_openai_compatible_adapter_supports_forge_and_tunneled_kiln_services():
    calls = []
    valid = {
        "summary": "reviewed",
        "evidence": ["fixture"],
        "uncertainty": "none",
        "next_gate": "fry_approval",
    }
    adapter = SandboxedOpenAIAdapter(
        endpoint="http://127.0.0.1:11435/v1/chat/completions",
        allowed_models=("QUENCH",),
        transport=lambda url, payload, timeout: calls.append(
            (url, payload, timeout)) or {
                "choices": [{"message": {"content": __import__("json").dumps(valid)}}]
            },
    )
    assert adapter.invoke(bot_id="quench", model="QUENCH", prompt="review") == valid
    assert calls[0][1]["stream"] is False
    assert calls[0][1]["tools"] == []
    response_format = calls[0][1]["response_format"]
    assert response_format["type"] == "json_schema"
    schema = response_format["json_schema"]["schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"summary", "evidence", "uncertainty", "next_gate"}
    assert schema["properties"]["next_gate"]["enum"] == sorted(
        OfflineEvaluator.allowed_next_gates)


def test_openai_compatible_adapter_denies_direct_remote_workers_and_bad_envelopes():
    with pytest.raises(ValueError, match="loopback"):
        SandboxedOpenAIAdapter(
            endpoint="http://100.97.193.39:11435/v1/chat/completions",
            allowed_models=("QUENCH",), transport=lambda *_: {})
    with pytest.raises(ValueError, match="/v1/chat/completions"):
        SandboxedOpenAIAdapter(
            endpoint="http://127.0.0.1:11435/v1/models",
            allowed_models=("QUENCH",), transport=lambda *_: {})
    adapter = SandboxedOpenAIAdapter(
        endpoint="http://127.0.0.1:11434/v1/chat/completions",
        allowed_models=("SMITH",), transport=lambda *_: {"choices": []})
    with pytest.raises(ValueError, match="invalid OpenAI-compatible envelope"):
        adapter.invoke(bot_id="smith", model="SMITH", prompt="implement")


def test_model_runtime_gateway_is_service_and_identity_allowlisted(monkeypatch):
    calls = []
    valid = {
        "summary": "done", "evidence": ["fixture"],
        "uncertainty": "none", "next_gate": "review",
    }
    monkeypatch.setattr(
        "orca.runtime.bounded_json_transport",
        lambda url, payload, timeout: calls.append((url, payload, timeout)) or {
            "choices": [{"message": {"content": __import__("json").dumps(valid)}}]
        },
    )
    gateway = ModelRuntimeGateway({"forge_smith", "kiln_quench"})
    assert gateway.invoke(
        service_id="forge_smith", bot_id="smith", prompt="implement"
    ) == valid
    assert calls[0][0] == "http://127.0.0.1:11434/v1/chat/completions"
    with pytest.raises(PermissionError, match="disabled"):
        gateway.invoke(service_id="forge_deepseek", bot_id="smith", prompt="reason")
    with pytest.raises(PermissionError, match="identity"):
        gateway.invoke(service_id="kiln_quench", bot_id="smith", prompt="review")
    with pytest.raises(ValueError, match="unknown enabled"):
        ModelRuntimeGateway({"cloud"})


def test_read_only_broker_executes_bounded_workspace_and_terminal_tools(tmp_path):
    (tmp_path / "notes.txt").write_text("alpha\nbeta\n")
    tools = WorkspaceReadTools(tmp_path)
    broker = ReadOnlyToolBroker(tools.handlers())
    results = broker.execute(bot_id="smith", requests=[
        ToolRequest("file.read", {"path": "notes.txt"}),
        ToolRequest("file.search", {"query": "beta", "glob": "*.txt"}),
    ])
    assert results[0].output["content"] == "alpha\nbeta\n"
    assert results[1].output["matches"][0]["line"] == 2
    with pytest.raises(PermissionError, match="escapes"):
        broker.execute(bot_id="smith", requests=[
            ToolRequest("file.read", {"path": "../outside"}),
        ])
    with pytest.raises(PermissionError, match="allowlist"):
        broker.execute(bot_id="smith", requests=[
            ToolRequest("terminal.inspect", {
                "executable": "/bin/sh", "args": ["-c", "id"],
            }),
        ])


def test_openai_adapter_runs_one_bounded_tool_round_then_returns_final(tmp_path):
    (tmp_path / "fact.txt").write_text("verified fact\n")
    broker = ReadOnlyToolBroker(WorkspaceReadTools(tmp_path).handlers())
    calls = []
    first = {
        "tool_requests": [{"name": "file.read", "arguments": {"path": "fact.txt"}}],
    }
    final = {
        "summary": "The fact is verified", "evidence": ["fact.txt: verified fact"],
        "uncertainty": "none", "next_gate": "review",
    }
    responses = iter((first, final))
    adapter = SandboxedOpenAIAdapter(
        endpoint="http://127.0.0.1:11434/v1/chat/completions",
        allowed_models=("SMITH",),
        transport=lambda url, payload, timeout: calls.append(payload) or {
            "choices": [{"message": {"content": __import__("json").dumps(next(responses))}}]
        },
    )
    assert adapter.invoke(
        bot_id="smith", model="SMITH", prompt="read the fact", tool_broker=broker
    ) == final
    assert len(calls) == 2
    assert "file.read" in calls[0]["messages"][0]["content"]
    assert "verified fact" in calls[1]["messages"][1]["content"]


def test_openai_adapter_retries_one_invalid_json_response():
    final = {
        "summary": "Recovered as strict JSON",
        "evidence": ["automatic retry returned the required object"],
        "uncertainty": "none",
        "next_gate": "none",
    }
    responses = iter(("I cannot provide JSON.", __import__("json").dumps(final)))
    calls = []
    adapter = SandboxedOpenAIAdapter(
        endpoint="http://127.0.0.1:11434/v1/chat/completions",
        allowed_models=("ORCA",),
        transport=lambda url, payload, timeout: calls.append(payload) or {
            "choices": [{"message": {"content": next(responses)}}]
        },
    )

    assert adapter.invoke(bot_id="orca", model="ORCA", prompt="Return JSON") == final
    assert len(calls) == 2
    assert calls[0]["temperature"] == 0
    assert "previous response could not be parsed" in calls[1]["messages"][0]["content"]


def test_public_web_search_is_bounded_and_parsed_without_browser_authority():
    html = b'<a class="result-link" href="https://example.com/a">Example result</a>'
    web = PublicWebReadTools(
        transport=lambda url, headers, limit: (url, html.decode()))
    result = web.search(query="orca tools")
    assert result == {
        "query": "orca tools",
        "results": [{"title": "Example result", "url": "https://example.com/a"}],
    }
    with pytest.raises(ValueError, match="bounded"):
        web.search(query="")


def test_google_drive_tools_are_read_only_and_require_owner_only_token(tmp_path):
    token = tmp_path / "drive.token"
    token.write_text("test-token")
    token.chmod(0o600)
    calls = []

    def transport(url, supplied_token, limit):
        calls.append((url, supplied_token, limit))
        if "fields=id" in url:
            return "application/json", __import__("json").dumps({
                "id": "abc", "name": "Note", "mimeType": "text/plain"
            }).encode()
        if "alt=media" in url:
            return "text/plain", b"drive fact"
        return "application/json", b'{"files":[{"id":"abc","name":"Note"}]}'

    drive = GoogleDriveReadTools(token, transport=transport)
    assert drive.search(query="Note")["files"][0]["id"] == "abc"
    assert drive.read(file_id="abc")["text"] == "drive fact"
    assert all(call[1] == "test-token" for call in calls)
    token.chmod(0o644)
    with pytest.raises(PermissionError, match="owner-only"):
        GoogleDriveReadTools(token, transport=transport)


def test_rclone_drive_tools_use_only_query_and_cat_with_owner_only_config(tmp_path):
    config = tmp_path / "rclone.conf"
    config.write_text("[gdrive]\ntype = drive\n")
    config.chmod(0o600)
    calls = []

    def runner(arguments, limit=512_000):
        calls.append((arguments, limit))
        if arguments[:2] == ["backend", "query"]:
            return '[{"id":"abc","name":"CC_note.md"}]'
        return "handoff text"

    drive = RcloneDriveReadTools(config, runner=runner)
    assert drive.search(query="CC_note")["results"][0]["id"] == "abc"
    assert drive.read(path="cc-bridge/CC_note.md")["text"] == "handoff text"
    assert calls[0][0][:3] == ["backend", "query", "gdrive:"]
    assert calls[1] == (["cat", "gdrive:cc-bridge/CC_note.md"], 256_000)
    with pytest.raises(ValueError, match="relative"):
        drive.read(path="../secret")
    config.chmod(0o644)
    with pytest.raises(PermissionError, match="owner-only"):
        RcloneDriveReadTools(config, runner=runner)


def test_local_adapters_accept_only_one_empty_json_fence():
    valid = {
        "summary": "done", "evidence": ["fixture"],
        "uncertainty": "none", "next_gate": "review",
    }
    adapter = SandboxedOpenAIAdapter(
        endpoint="http://127.0.0.1:11434/v1/chat/completions",
        allowed_models=("SMITH",),
        transport=lambda *_: {"choices": [{"message": {
            "content": "```json\n" + __import__("json").dumps(valid) + "\n```"
        }}]},
    )
    assert adapter.invoke(bot_id="smith", model="SMITH", prompt="implement") == valid
    adapter.transport = lambda *_: {"choices": [{"message": {
        "content": "preface\n```json\n" + __import__("json").dumps(valid) + "\n```"
    }}]}
    with pytest.raises(ValueError, match="not valid JSON"):
        adapter.invoke(bot_id="smith", model="SMITH", prompt="implement")
