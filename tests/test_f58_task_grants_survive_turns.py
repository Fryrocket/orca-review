"""R11-F58: "_turn blanket revoke vs task grants".

PrivilegeBroker.end_turn() intentionally revokes ALL of the turn-ending
agent's grants (D3 — see test_end_turn_revokes_grant /
test_turn_switch_does_not_orphan_grant in test_round6.py, which lock this
in as correct: nothing should carry over between turns implicitly). That
part is not a bug and is untouched here.

The actual bug: Orchestrator._turn()'s `finally: self.broker.end_turn(...)`
called that same blanket revoke after EVERY turn, including turns run
inside a begin_task(grant=...) task — but task-level grants are documented
to last until end_task(), not one turn. A task granting Privilege.CODE_EDIT
to an agent lost that grant the instant the agent's first turn ended, long
before end_task() ever ran, with no error and no signal.

Fix: _turn() now re-establishes the ending agent's task-level grant (if
the task is still active) immediately after end_turn()'s blanket revoke,
via the same broker.grant() path (so SENSITIVE_GRANTS / human_approved
rules still apply — no bypass). This keeps D3's "explicit re-authorization
every turn" spirit while honoring begin_task's "lasts the whole task"
contract: the Orchestrator does the re-authorizing each turn instead of
letting it silently vanish."""

from mao.agent import Agent, Role
from mao.cost_store import DayCostStore
from mao.costguard import UsageTrackerCostGuard
from mao.human import GateDecision, GateResult
from mao.models import EchoModel
from mao.orchestrator import Orchestrator
from mao.roles import Privilege, PrivilegeBroker
from mao.tracking import UsageTracker


class _ApproveGate:
    def ask(self, payload, context=""):
        return GateResult(GateDecision.APPROVE, content=payload)


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
    broker = PrivilegeBroker(enforce=True)
    orch = Orchestrator(
        agents=[_agent()],
        broker=broker,
        cost_guard=_cost_guard(tmp_path),
        human_gate=_ApproveGate(),
    )
    return orch, broker


def test_task_grant_survives_a_turn(tmp_path):
    """The exact F58 bug: this used to be False after just one turn."""
    orch, broker = _orch(tmp_path)
    orch.begin_task("do a task", human_approved=True, grant={"claude": {Privilege.CODE_EDIT}})
    assert broker.can("claude", Privilege.CODE_EDIT) is True
    list(orch.run_sequential("first turn"))
    assert broker.can("claude", Privilege.CODE_EDIT) is True


def test_task_grant_survives_multiple_turns(tmp_path):
    orch, broker = _orch(tmp_path)
    orch.begin_task("do a task", human_approved=True, grant={"claude": {Privilege.CODE_EDIT}})
    list(orch.run_sequential("turn 1"))
    list(orch.run_sequential("turn 2"))
    list(orch.run_sequential("turn 3"))
    assert broker.can("claude", Privilege.CODE_EDIT) is True


def test_task_grant_revoked_by_end_task_not_before(tmp_path):
    orch, broker = _orch(tmp_path)
    orch.begin_task("do a task", human_approved=True, grant={"claude": {Privilege.CODE_EDIT}})
    list(orch.run_sequential("turn 1"))
    assert broker.can("claude", Privilege.CODE_EDIT) is True
    orch.end_task()
    assert broker.can("claude", Privilege.CODE_EDIT) is False


def test_turn_without_active_task_does_not_regrant_anything(tmp_path):
    """No begin_task at all — _turn()'s new re-grant step must be a no-op,
    not accidentally grant something out of nowhere."""
    orch, broker = _orch(tmp_path)
    assert broker.can("claude", Privilege.CODE_EDIT) is False
    list(orch.run_sequential("a turn with no task"))
    assert broker.can("claude", Privilege.CODE_EDIT) is False


def test_non_task_grant_still_dies_at_end_of_turn():
    """D3 regression guard: a grant made OUTSIDE begin_task (e.g. directly
    on the broker) must still be revoked at end_turn — this fix only
    special-cases grants tracked in Orchestrator._task_grants."""
    broker = PrivilegeBroker(enforce=True)
    broker.grant("grok", "claude", {Privilege.CODE_EDIT}, human_approved=True)
    broker.start_turn("claude")
    assert broker.can("claude", Privilege.CODE_EDIT) is True
    broker.end_turn()
    assert broker.can("claude", Privilege.CODE_EDIT) is False
