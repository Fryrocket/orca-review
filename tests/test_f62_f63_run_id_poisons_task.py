"""R11-F62/F63: "run_id / end_task".

_ensure_run_id() previously persisted its invented id into
self._active_run_id even when begin_task() was never called. Every other
part of the class treats self._active_run_id as "a task is active":
begin_task() refuses to start while it's set, and only end_task() clears
it. So a single bare run_sequential()/run_parallel() call — perfectly
legal, ad-hoc usage the API allows — permanently poisoned the Orchestrator:
begin_task() would refuse forever afterward with "task <id> already
active", even though no task was ever begun and nobody would think to call
end_task() for a run they never called begin_task() for.

_ensure_run_id() no longer persists an invented id. F16 ("run_* reuse
_active_run_id from begin_task when set") is unaffected — that's the
`if self._active_run_id:` branch, still reused whenever a real task is
active."""

from mao.agent import Agent, Role
from mao.cost_store import DayCostStore
from mao.costguard import UsageTrackerCostGuard
from mao.models import EchoModel
from mao.orchestrator import Orchestrator
from mao.roles import PrivilegeBroker
from mao.tracking import UsageTracker


def _agent(name="claude"):
    a = Agent(Role(name, name), system_prompt=f"you are {name}")
    a.bind_model(EchoModel())
    return a


def _cost_guard(tmp_path):
    return UsageTrackerCostGuard(
        record_usage=UsageTracker(day_store=DayCostStore(tmp_path / "c.json")).record,
        hard_ceiling_usd=100.0,
        estimate_cost=lambda model, tin, tout: 0.001 * (tin + tout),
    )


def _orch(tmp_path):
    return Orchestrator(
        agents=[_agent()],
        broker=PrivilegeBroker(enforce=True),
        cost_guard=_cost_guard(tmp_path),
        human_gate=None,
    )


def test_bare_run_sequential_does_not_poison_active_run_id(tmp_path):
    """The exact F62/F63 bug: this used to leave _active_run_id set."""
    orch = _orch(tmp_path)
    list(orch.run_sequential("a bare run, no begin_task"))
    assert orch._active_run_id is None


def test_bare_run_sequential_still_produces_a_real_run_id(tmp_path):
    """The fix must not break run_id tagging on results — only stop it
    from leaking into task-tracking state."""
    orch = _orch(tmp_path)
    results = list(orch.run_sequential("a bare run"))
    assert results[0].run_id
    assert isinstance(results[0].run_id, str)


def test_begin_task_still_works_after_a_prior_bare_run(tmp_path):
    """The actual user-facing symptom: begin_task() must not be
    permanently blocked by an earlier ad-hoc run."""
    orch = _orch(tmp_path)
    list(orch.run_sequential("bare run before any task"))
    run_id = orch.begin_task("now a real task", human_approved=False)
    assert run_id
    assert orch._active_run_id == run_id


def test_run_sequential_still_reuses_begin_task_run_id():
    """F16 regression guard: run_* must still reuse the task's run_id when
    a real task is active — this fix only affects the no-task path."""
    import tempfile
    from pathlib import Path

    tmp_path = Path(tempfile.mkdtemp())
    orch = _orch(tmp_path)
    task_run_id = orch.begin_task("a real task", human_approved=False)
    results = list(orch.run_sequential("turn inside the task"))
    assert results[0].run_id == task_run_id


def test_two_consecutive_bare_runs_each_get_independent_run_ids(tmp_path):
    orch = _orch(tmp_path)
    r1 = list(orch.run_sequential("first bare run"))
    r2 = list(orch.run_sequential("second bare run"))
    assert r1[0].run_id != r2[0].run_id
    assert orch._active_run_id is None
