"""Product-layer tests: orchestrator, dashboard auth, models, scheduler, ledger."""

import os
from pathlib import Path

import pytest

from mao.agent import Agent, Role
from mao.cost_store import DayCostStore
from mao.errors import (
    CostCapExceeded,
    GateTimeoutError,
    HardPrivilegeError,
    NTPNotSyncedError,
    OrcaConfigError,
)
from mao.models import OpenAICompatibleModel, get_default_model
from mao.orchestrator import Orchestrator
from mao.pricing import DEFAULT_MODEL
from mao.roles import Privilege, PrivilegeBroker
from mao.scheduler import SessionScheduler
from mao.tools import ToolRegistry
from mao.tracking import UsageTracker
from mao.web_ui.auth import authorized, validate_bind


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCA_PROFILE", "test")
    monkeypatch.setenv("ORCA_REPO_ROOT", str(tmp_path))
    monkeypatch.delenv("ORCA_API_KEY", raising=False)
    monkeypatch.delenv("MAO_API_KEY", raising=False)
    for d in ("runs", "mao", "orca-out", "examples"):
        (tmp_path / d).mkdir(exist_ok=True)
    return tmp_path


def _agent(name="claude"):
    return Agent(Role(name, name), system_prompt=f"you are {name}")


def test_orchestrator_write_raises_not_soft_dict(env):
    broker = PrivilegeBroker(enforce=True)
    tools = ToolRegistry(broker=broker, repo_root_path=env)
    tools.register_function(
        "write_file", "w", lambda path, content="": "ok", write_class=Privilege.CODE_EDIT
    )
    orch = Orchestrator(
        agents=[_agent()],
        tools=tools,
        broker=broker,
        tracker=UsageTracker(day_store=DayCostStore(env / "c.json")),
    )
    broker.start_turn("claude")
    with pytest.raises(HardPrivilegeError, match=r"claude lacks code_edit"):
        orch.run_turn(orch.agents[0], "write_file please", touching_code=True)


def test_orchestrator_passes_agent_to_registry(env):
    broker = PrivilegeBroker(enforce=True)
    broker.grant("grok", "claude", {Privilege.CODE_EDIT}, human_approved=True)
    broker.start_turn("claude")
    seen = {}

    def wf(path="runs/x.py", content="", **kw):
        seen["path"] = path
        return "ok"

    tools = ToolRegistry(broker=broker, repo_root_path=env)
    tools.register_function("write_file", "w", wf, write_class=Privilege.CODE_EDIT)
    agent = _agent()
    agent.allow_tools(["write_file"])
    orch = Orchestrator(
        agents=[agent],
        tools=tools,
        broker=broker,
        tracker=UsageTracker(day_store=DayCostStore(env / "c.json")),
    )
    # Echo will call write_file if the user text mentions it.
    orch.run_turn(agent, "please write_file a helper")
    assert seen.get("path") is not None


def test_begin_task_sensitive_requires_fry(env):
    orch = Orchestrator(
        agents=[_agent()],
        tracker=UsageTracker(day_store=DayCostStore(env / "c.json")),
    )
    with pytest.raises(HardPrivilegeError, match=r"HumanGate APPROVE"):
        orch.begin_task("claude", privs={Privilege.CODE_EDIT})


def test_begin_task_with_human_approved(env):
    orch = Orchestrator(
        agents=[_agent()],
        tracker=UsageTracker(day_store=DayCostStore(env / "c.json")),
    )
    orch.begin_task(
        "claude", privs={Privilege.CODE_EDIT}, human_approved=True, note="ok"
    )
    assert orch.broker.can("claude", Privilege.CODE_EDIT)
    orch.end_task("claude")
    assert not orch.broker.can("claude", Privilege.CODE_EDIT)


def test_parallel_does_not_invoke_tools(env):
    broker = PrivilegeBroker(enforce=True)
    called = {"n": 0}

    def boom():
        called["n"] += 1
        return "nope"

    tools = ToolRegistry(broker=broker, repo_root_path=env)
    tools.register_function("mystery_tool", "u", boom)
    a = _agent("grok")
    a.allow_tools(["mystery_tool"])
    orch = Orchestrator(
        agents=[a],
        tools=tools,
        broker=broker,
        tracker=UsageTracker(day_store=DayCostStore(env / "c.json")),
    )
    orch.run_parallel("call mystery_tool now")
    assert called["n"] == 0


def test_lan_bind_requires_flag_and_token(monkeypatch):
    monkeypatch.delenv("ORCA_DASHBOARD_LAN", raising=False)
    monkeypatch.delenv("ORCA_DASHBOARD_TOKEN", raising=False)
    with pytest.raises(OrcaConfigError, match=r"ORCA_DASHBOARD_LAN"):
        validate_bind("0.0.0.0")
    monkeypatch.setenv("ORCA_DASHBOARD_LAN", "1")
    with pytest.raises(OrcaConfigError, match=r"ORCA_DASHBOARD_TOKEN"):
        validate_bind("0.0.0.0")
    monkeypatch.setenv("ORCA_DASHBOARD_TOKEN", "s3cret")
    validate_bind("0.0.0.0")
    validate_bind("127.0.0.1")


def test_bearer_compare(monkeypatch):
    monkeypatch.setenv("ORCA_DASHBOARD_TOKEN", "s3cret")
    assert authorized("Bearer s3cret") is True
    assert authorized("Bearer nope") is False
    assert authorized(None) is False
    monkeypatch.delenv("ORCA_DASHBOARD_TOKEN")
    assert authorized(None) is True


def test_client_cannot_toggle_enforce_is_documented():
    src = Path("mao/web_ui/server.py").read_text()
    assert "client cannot toggle enforce_privileges" in src


def test_default_model_is_pinned(monkeypatch):
    monkeypatch.setenv("ORCA_PROFILE", "test")
    monkeypatch.setenv("ORCA_API_KEY", "x")
    monkeypatch.delenv("ORCA_MODEL", raising=False)
    monkeypatch.delenv("MAO_MODEL", raising=False)
    m = OpenAICompatibleModel()
    assert m.model == DEFAULT_MODEL
    assert m.model != "grok-2-latest"


def test_pi5_missing_key_refuses_echo(monkeypatch):
    monkeypatch.setenv("ORCA_PROFILE", "pi5")
    monkeypatch.delenv("ORCA_API_KEY", raising=False)
    monkeypatch.delenv("MAO_API_KEY", raising=False)
    with pytest.raises(OrcaConfigError, match=r"ORCA_API_KEY"):
        get_default_model()


def test_scheduler_arm_requires_ntp(monkeypatch, tmp_path):
    import mao.scheduler as sched_mod

    monkeypatch.setattr(sched_mod, "require_ntp_or_refuse", lambda stage="arm": (_ for _ in ()).throw(
        NTPNotSyncedError(f"stage={stage!r}")
    ))
    s = SessionScheduler(tmp_path / "jobs.json")
    with pytest.raises(NTPNotSyncedError, match=r"stage='arm'"):
        s.start()


def test_scheduler_fire_records_ntp_refuse(monkeypatch, tmp_path):
    import mao.scheduler as sched_mod

    def refuse(stage="arm"):
        raise NTPNotSyncedError(f"stage={stage!r}")

    monkeypatch.setattr(sched_mod, "require_ntp_or_refuse", refuse)
    s = SessionScheduler(tmp_path / "jobs.json")
    job = s.add("t", interval_sec=1, run_immediately=True)
    s._fire(job)
    assert job.last_status == "refused_ntp"


def test_negative_cost_refused(tmp_path):
    store = DayCostStore(tmp_path / "c.json")
    with pytest.raises(OrcaConfigError, match=r"amount must be >= 0"):
        store.add(-1.0)


def test_kill_switch_keeps_record(tmp_path, env):
    tracker = UsageTracker(
        kill_switch=True,
        per_run_ceiling_usd=10.0,
        per_day_ceiling_usd=10.0,
        day_store=DayCostStore(tmp_path / "c.json"),
    )
    with pytest.raises(CostCapExceeded, match=r"kill_switch ON"):
        tracker.record("claude", "echo", cost_usd=0.1)
    assert len(tracker.records) == 1
    assert tracker.records[0].posted is True


def test_read_tool_outside_catalog_denied(env):
    broker = PrivilegeBroker(enforce=True)
    reg = ToolRegistry(broker=broker, repo_root_path=env)
    reg.register_function("dump_secrets", "r", lambda: "x", is_read_only=True)
    with pytest.raises(HardPrivilegeError, match=r"tools_allowed does not include"):
        reg.call("dump_secrets", agent="claude")


def test_gate_timeout_is_orca_error():
    assert issubclass(GateTimeoutError, Exception)
    from mao.errors import OrcaError

    assert issubclass(GateTimeoutError, OrcaError)
