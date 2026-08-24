"""R11-F59: an adapter that returns a bare string (neither a dict nor a
ModelResponse) previously left tin=tout=0 in Orchestrator._invoke's `else`
branch. CostGuard.record() reads tin==0 and tout==0 as "genuinely free" and
never calls estimate_cost, so a string-returning adapter billed $0 forever
regardless of how much text was actually exchanged. _invoke now derives an
approximate token count so the existing estimate_cost fallback engages."""

from mao.agent import Agent, Role
from mao.cost_store import DayCostStore
from mao.costguard import UsageTrackerCostGuard
from mao.orchestrator import Orchestrator
from mao.roles import PrivilegeBroker
from mao.tracking import UsageTracker


class _StringAdapter:
    """Model adapter that returns a bare string — no dict, no ModelResponse,
    no usage metadata at all. The exact shape F59 is about."""

    name = "string-adapter"

    def __init__(self, response_text):
        self._response_text = response_text

    def complete(self, system, user, tools=None):
        return self._response_text


def _agent(model):
    a = Agent(Role("claude", "claude"), system_prompt="you are claude")
    a.bind_model(model)
    return a


def _cost_guard(tmp_path, estimate_cost):
    tracker = UsageTracker(
        per_run_ceiling_usd=100.0,
        per_day_ceiling_usd=200.0,
        day_store=DayCostStore(tmp_path / "c.json"),
    )
    return UsageTrackerCostGuard(
        record_usage=tracker.record, hard_ceiling_usd=100.0, estimate_cost=estimate_cost
    )


def test_string_returning_adapter_bills_nonzero(tmp_path):
    """The exact F59 bug: previously cost_usd was always 0.0 here."""
    cg = _cost_guard(tmp_path, estimate_cost=lambda model, tin, tout: 0.01 * (tin + tout))
    broker = PrivilegeBroker(enforce=True)
    orch = Orchestrator(
        agents=[_agent(_StringAdapter("a real response with real content in it"))],
        broker=broker,
        cost_guard=cg,
        human_gate=None,
    )
    results = list(orch.run_sequential("a real objective prompt with real content in it"))
    assert results[0].tokens_in > 0
    assert results[0].tokens_out > 0
    assert results[0].cost_usd > 0.0


def test_string_returning_adapter_token_estimate_scales_with_text(tmp_path):
    """A longer response should estimate to more tokens than a short one —
    guards against a fixed/constant stub that happens to be nonzero."""
    cg_short = _cost_guard(tmp_path, estimate_cost=lambda model, tin, tout: 0.01 * (tin + tout))
    cg_long = _cost_guard(tmp_path, estimate_cost=lambda model, tin, tout: 0.01 * (tin + tout))
    broker1 = PrivilegeBroker(enforce=True)
    broker2 = PrivilegeBroker(enforce=True)

    orch_short = Orchestrator(
        agents=[_agent(_StringAdapter("short"))],
        broker=broker1, cost_guard=cg_short, human_gate=None,
    )
    orch_long = Orchestrator(
        agents=[_agent(_StringAdapter("a much longer response " * 20))],
        broker=broker2, cost_guard=cg_long, human_gate=None,
    )
    r_short = list(orch_short.run_sequential("objective"))[0]
    r_long = list(orch_long.run_sequential("objective"))[0]
    assert r_long.cost_usd > r_short.cost_usd


def test_dict_and_modelresponse_adapters_unaffected(tmp_path):
    """This fix only touches the no-structured-usage `else` branch — an
    adapter that DOES report real usage must keep using that, not the
    length-based approximation."""
    from mao.models import ModelResponse

    class _StructuredAdapter:
        name = "structured-adapter"

        def complete(self, system, user, tools=None):
            return ModelResponse(text="hi", input_tokens=7, output_tokens=3)

    cg = _cost_guard(tmp_path, estimate_cost=lambda model, tin, tout: 0.01 * (tin + tout))
    broker = PrivilegeBroker(enforce=True)
    orch = Orchestrator(
        agents=[_agent(_StructuredAdapter())], broker=broker, cost_guard=cg, human_gate=None
    )
    r = list(orch.run_sequential("objective"))[0]
    assert r.tokens_in == 7
    assert r.tokens_out == 3
