"""R11-F67 ("debate slice").

run_debate()'s moderator exclusion only applied when agents= was omitted
(defaulting to self.agents, filtered with `a is not moderator`). A caller
who passed agents= explicitly and happened to include the same Agent
object as moderator got that agent invoked twice per round — once as a
roster debater, once as moderator — silently, no error. The exclusion now
applies consistently regardless of where the agent list came from."""

from mao.agent import Agent, Role
from mao.cost_store import DayCostStore
from mao.costguard import UsageTrackerCostGuard
from mao.models import EchoModel
from mao.orchestrator import Orchestrator
from mao.roles import PrivilegeBroker
from mao.tracking import UsageTracker


def _agent(name):
    a = Agent(Role(name, name), system_prompt=name)
    a.bind_model(EchoModel())
    return a


def _cost_guard(tmp_path):
    return UsageTrackerCostGuard(
        record_usage=UsageTracker(day_store=DayCostStore(tmp_path / "c.json")).record,
        hard_ceiling_usd=100.0,
        estimate_cost=lambda model, tin, tout: 0.001 * (tin + tout),
    )


def _orch(tmp_path, agents):
    return Orchestrator(
        agents=agents,
        broker=PrivilegeBroker(enforce=True),
        cost_guard=_cost_guard(tmp_path),
        human_gate=None,
    )


def test_explicit_agents_still_excludes_moderator_from_roster(tmp_path):
    """The exact F67 bug: moderator used to speak twice per round when
    included in an explicit agents= list."""
    grok, claude = _agent("grok"), _agent("claude")
    orch = _orch(tmp_path, [grok, claude])
    speakers = [
        r.agent
        for r in orch.run_debate("topic", rounds=1, moderator=grok, agents=[grok, claude])
    ]
    assert speakers.count("grok") == 1
    assert speakers == ["claude", "grok"]


def test_default_agents_still_excludes_moderator_as_before(tmp_path):
    """Regression guard: the pre-existing implicit-default path must be
    completely unaffected by this fix."""
    grok, claude = _agent("grok"), _agent("claude")
    orch = _orch(tmp_path, [grok, claude])
    speakers = [r.agent for r in orch.run_debate("topic", rounds=1, moderator=grok)]
    assert speakers.count("grok") == 1
    assert speakers == ["claude", "grok"]


def test_debate_with_no_moderator_is_unaffected(tmp_path):
    grok, claude = _agent("grok"), _agent("claude")
    orch = _orch(tmp_path, [grok, claude])
    speakers = [r.agent for r in orch.run_debate("topic", rounds=1)]
    assert set(speakers) == {"grok", "claude"}


def test_debate_refuses_when_explicit_agents_is_only_the_moderator(tmp_path):
    """If excluding the moderator leaves nobody to debate, this must raise
    the existing 'needs at least one debating agent' error, not silently
    run a zero-agent debate."""
    import pytest
    from mao.errors import OrcaConfigError

    grok = _agent("grok")
    orch = _orch(tmp_path, [grok])
    with pytest.raises(OrcaConfigError, match="needs at least one debating agent"):
        list(orch.run_debate("topic", rounds=1, moderator=grok, agents=[grok]))
