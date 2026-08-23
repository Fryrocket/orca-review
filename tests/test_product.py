"""Product-layer tests: orchestrator, dashboard auth, models, scheduler, ledger."""

from pathlib import Path

import pytest

from mao.agent import Agent, Role
from mao.cost_store import DayCostStore
from mao.costguard import UsageTrackerCostGuard
from mao.errors import (
    CostCapExceeded,
    GateTimeoutError,
    HardPrivilegeError,
    NTPNotSyncedError,
    OrcaConfigError,
)
from mao.human import GateDecision, GateResult
from mao.models import EchoModel, OpenAICompatibleModel, get_default_model
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


def _cost_guard(env):
    return UsageTrackerCostGuard(
        record_usage=UsageTracker(day_store=DayCostStore(env / "c.json")).record,
        hard_ceiling_usd=100.0,
    )


class _ApproveGate:
    """Test double for HumanGate — always approves."""

    def ask(self, payload, context=""):
        return GateResult(GateDecision.APPROVE, content=payload)


def test_orchestrator_write_raises_not_soft_dict(env):
    broker = PrivilegeBroker(enforce=True)
    tools = ToolRegistry(broker=broker, repo_root_path=env)
    tools.register_function(
        "write_file", "w", lambda path, content="": "ok", write_class=Privilege.CODE_EDIT
    )
    agent = _agent()
    agent.allow_tools(["write_file"])
    agent.bind_model(EchoModel())
    orch = Orchestrator(
        agents=[agent],
        tools=tools,
        broker=broker,
        cost_guard=_cost_guard(env),
    )
    # Echo emits a write_file tool call because the objective mentions it;
    # claude has no CODE_EDIT grant, so the registry must raise, not return
    # a soft denial dict.
    with pytest.raises(HardPrivilegeError, match=r"claude lacks code_edit"):
        list(orch.run_sequential("write_file please"))


def test_orchestrator_passes_agent_to_registry(env):
    broker = PrivilegeBroker(enforce=True)
    broker.grant("grok", "claude", {Privilege.CODE_EDIT}, human_approved=True)
    seen = {}

    def wf(path="runs/x.py", content="", **kw):
        seen["path"] = path
        return "ok"

    tools = ToolRegistry(broker=broker, repo_root_path=env)
    tools.register_function("write_file", "w", wf, write_class=Privilege.CODE_EDIT)
    agent = _agent()
    agent.allow_tools(["write_file"])
    agent.bind_model(EchoModel())
    orch = Orchestrator(
        agents=[agent],
        tools=tools,
        broker=broker,
        cost_guard=_cost_guard(env),
    )
    list(orch.run_sequential("please write_file a helper"))
    assert seen.get("path") is not None


def test_begin_task_sensitive_requires_fry(env):
    broker = PrivilegeBroker(enforce=True)
    orch = Orchestrator(agents=[_agent()], broker=broker, cost_guard=_cost_guard(env))
    with pytest.raises(HardPrivilegeError, match=r"HumanGate APPROVE"):
        orch.begin_task("edit code", grant={"claude": {Privilege.CODE_EDIT}})


def test_begin_task_with_human_approved(env):
    broker = PrivilegeBroker(enforce=True)
    orch = Orchestrator(
        agents=[_agent()],
        broker=broker,
        cost_guard=_cost_guard(env),
        human_gate=_ApproveGate(),
    )
    orch.begin_task(
        "edit code", human_approved=True, grant={"claude": {Privilege.CODE_EDIT}}
    )
    assert orch.broker.can("claude", Privilege.CODE_EDIT)
    orch.end_task()
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
    a.bind_model(EchoModel())
    orch = Orchestrator(
        agents=[a],
        tools=tools,
        broker=broker,
        cost_guard=_cost_guard(env),
    )
    # R11-F18: parallel mode refuses tool-declaring agents outright rather
    # than silently stripping their tools.
    with pytest.raises(OrcaConfigError, match=r"Parallel mode refuses tool-declaring agent"):
        list(orch.run_parallel("call mystery_tool now"))
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


def test_scheduler_clamps_clock_jump_backlog(monkeypatch, tmp_path):
    """R11-F42: a job wildly overdue (clock jump / long downtime) must be
    re-anchored, not fired — prevents a whole-table catch-up storm."""
    import mao.scheduler as sched_mod

    monkeypatch.setattr(sched_mod, "require_ntp_or_refuse", lambda stage="arm": None)
    s = SessionScheduler(tmp_path / "jobs.json", max_catch_up_sec=300.0)
    fired = {"n": 0}
    s.set_handler(lambda job: fired.__setitem__("n", fired["n"] + 1))

    job = s.add("t", interval_sec=60)
    from datetime import datetime, timedelta, timezone

    with s._lock:
        job.next_run = (datetime.now(timezone.utc) - timedelta(seconds=10_000)).isoformat()

    fired_count = s.tick()
    assert fired_count == 0
    assert fired["n"] == 0
    assert job.last_status.startswith("clock_jump_reanchored")
    new_next = datetime.fromisoformat(job.next_run)
    assert (new_next - datetime.now(timezone.utc)).total_seconds() < job.interval_sec + 5


def test_scheduler_fires_normal_catch_up_within_clamp(monkeypatch, tmp_path):
    """A job only briefly overdue (well under the clamp) still fires normally."""
    import mao.scheduler as sched_mod

    monkeypatch.setattr(sched_mod, "require_ntp_or_refuse", lambda stage="arm": None)
    s = SessionScheduler(tmp_path / "jobs.json", max_catch_up_sec=300.0)
    fired = {"n": 0}
    s.set_handler(lambda job: fired.__setitem__("n", fired["n"] + 1))

    job = s.add("t", interval_sec=60)
    from datetime import datetime, timedelta, timezone

    with s._lock:
        job.next_run = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()

    fired_count = s.tick()
    assert fired_count == 1
    assert fired["n"] == 1
    assert job.last_status == "ok"


def test_check_clock_jump_detects_wall_monotonic_divergence(tmp_path):
    """R11-F42 monotonic detector: observability only, does not alter firing."""
    s = SessionScheduler(tmp_path / "jobs.json", clock_jump_threshold_sec=5.0)
    assert s.last_clock_jump is None

    import time

    s._last_wall = time.time() - 100
    s._last_mono = time.monotonic() - 1.0  # real time barely moved
    s._check_clock_jump()

    assert s.last_clock_jump is not None
    assert "divergence=" in s.last_clock_jump


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
