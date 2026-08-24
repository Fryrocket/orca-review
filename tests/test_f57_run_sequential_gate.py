"""R11-F57: run_sequential(human_approved=True) must not silently proceed
when no HumanGate is configured. Previously it only asked the gate `if
human_approved and self.human_gate is not None` — meaning a caller (or a
bug upstream) passing human_approved=True with no real gate wired in got
the run executed as if a human had approved it, with no human ever asked
and no error raised. begin_task already got this right (raises
OrcaConfigError); run_sequential now matches."""

from pathlib import Path

import pytest

from mao.agent import Agent, Role
from mao.cost_store import DayCostStore
from mao.errors import HardPrivilegeError, OrcaConfigError
from mao.human import GateDecision, GateResult
from mao.models import EchoModel
from mao.orchestrator import Orchestrator
from mao.roles import PrivilegeBroker
from mao.costguard import UsageTrackerCostGuard
from mao.tracking import UsageTracker


class _ApproveGate:
    def ask(self, payload, context=""):
        return GateResult(GateDecision.APPROVE, content=payload)


class _RejectGate:
    def ask(self, payload, context=""):
        return GateResult(GateDecision.REJECT, note="no")


def _agent(name="claude"):
    a = Agent(Role(name, name), system_prompt=f"you are {name}")
    a.bind_model(EchoModel())
    return a


def _cost_guard(tmp_path):
    return UsageTrackerCostGuard(
        record_usage=UsageTracker(day_store=DayCostStore(tmp_path / "c.json")).record,
        hard_ceiling_usd=100.0,
    )


def test_run_sequential_refuses_human_approved_with_no_gate(tmp_path):
    """The F57 scenario: human_approved=True but human_gate=None must not
    silently run — previously this executed with results returned."""
    broker = PrivilegeBroker(enforce=True)
    orch = Orchestrator(
        agents=[_agent()], broker=broker, cost_guard=_cost_guard(tmp_path), human_gate=None
    )
    with pytest.raises(OrcaConfigError, match=r"requires a HumanGate"):
        list(orch.run_sequential("do something", human_approved=True))


def test_run_sequential_with_real_gate_approving_still_works(tmp_path):
    broker = PrivilegeBroker(enforce=True)
    orch = Orchestrator(
        agents=[_agent()],
        broker=broker,
        cost_guard=_cost_guard(tmp_path),
        human_gate=_ApproveGate(),
    )
    results = list(orch.run_sequential("do something", human_approved=True))
    assert len(results) == 1


def test_run_sequential_with_real_gate_rejecting_still_denies(tmp_path):
    broker = PrivilegeBroker(enforce=True)
    orch = Orchestrator(
        agents=[_agent()],
        broker=broker,
        cost_guard=_cost_guard(tmp_path),
        human_gate=_RejectGate(),
    )
    with pytest.raises(HardPrivilegeError, match=r"Human gate denied"):
        list(orch.run_sequential("do something", human_approved=True))


def test_run_sequential_without_claiming_approval_is_unaffected(tmp_path):
    """human_approved=False (the default) must keep working with no gate —
    this fix must not require a gate for runs that never claim approval."""
    broker = PrivilegeBroker(enforce=True)
    orch = Orchestrator(
        agents=[_agent()], broker=broker, cost_guard=_cost_guard(tmp_path), human_gate=None
    )
    results = list(orch.run_sequential("do something"))
    assert len(results) == 1
