"""Real-wiring tests for Round-7 (Claude W5).

These tests exercise the actual pricing.estimate_cost, tracking.UsageTracker.record
signature, and roles.PrivilegeBroker.require adapter. They are deliberately
separate from test_round7.py (which uses fakes) so that a green count on the
fakes suite cannot mask a broken real wiring.

Run:
    pytest -q tests/test_wiring_round7.py
"""

from __future__ import annotations

import pytest

from mao.blackboard import Blackboard
from mao.costguard import UsageTrackerCostGuard
from mao.errors import HardPrivilegeError, OrcaConfigError, UnknownModelError
from mao.pricing import estimate_cost
from mao.roles import Privilege, PrivilegeBroker
from mao.tracking import UsageTracker


# ---------------------------------------------------------------------------
# 1. Real estimate_cost produces a non-zero price for a known model
# ---------------------------------------------------------------------------

def test_real_estimate_cost_returns_nonzero_for_known_model():
    """W5.1 — construct against the live pricing table and demand a real number."""
    cost = estimate_cost("grok-2-1212", 1000, 500)
    assert isinstance(cost, float)
    assert cost > 0.0, "known model must produce a positive price"


def test_real_estimate_cost_raises_on_unknown_model():
    """Companion: unknown model must fail closed, never return 0.0."""
    with pytest.raises(UnknownModelError, match="not in PRICE_TABLE"):
        estimate_cost("this-model-does-not-exist-xyz", 100, 50)


def test_usage_tracker_cost_guard_with_real_estimator():
    """W5.1 end-to-end: guard constructed with real estimate_cost yields non-zero."""
    recorded = []

    def spy_record(agent, model, input_tokens=0, output_tokens=0, cost_usd=0.0):
        recorded.append(
            {
                "agent": agent,
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": cost_usd,
            }
        )

    guard = UsageTrackerCostGuard(
        estimate_cost=estimate_cost,          # REAL
        record_usage=spy_record,
        hard_ceiling_usd=10.0,
        max_output_tokens=2048,
    )
    # Force derivation path (caller reports 0.0)
    guard.record("grok-2-1212", 1000, 500, agent="claude", cost_usd=0.0)
    assert len(recorded) == 1
    assert recorded[0]["cost_usd"] > 0.0
    assert guard.total_usd > 0.0


# ---------------------------------------------------------------------------
# 2. record path carries every argument by the correct name
# ---------------------------------------------------------------------------

def test_record_passes_exact_tracking_signature():
    """W5.2 — spy must see agent/model/input_tokens/output_tokens/cost_usd."""
    seen = {}

    def spy(agent, model, input_tokens=0, output_tokens=0, cost_usd=0.0):
        # Capture by name so a positional-only or mis-ordered call is visible.
        seen["agent"] = agent
        seen["model"] = model
        seen["input_tokens"] = input_tokens
        seen["output_tokens"] = output_tokens
        seen["cost_usd"] = cost_usd

    guard = UsageTrackerCostGuard(
        estimate_cost=estimate_cost,
        record_usage=spy,
        hard_ceiling_usd=5.0,
    )
    guard.record("claude-3-5-sonnet", 200, 80, agent="ampere", cost_usd=0.0)

    assert seen["agent"] == "ampere"
    assert seen["model"] == "claude-3-5-sonnet"
    assert seen["input_tokens"] == 200
    assert seen["output_tokens"] == 80
    assert seen["cost_usd"] > 0.0   # derived, never left at default 0.0


def test_record_never_relies_on_default_cost_usd():
    """Even when the model reports a real cost, we still pass it explicitly."""
    seen = {}

    def spy(agent, model, input_tokens=0, output_tokens=0, cost_usd=0.0):
        seen["cost_usd"] = cost_usd

    guard = UsageTrackerCostGuard(
        estimate_cost=estimate_cost,
        record_usage=spy,
        hard_ceiling_usd=5.0,
    )
    # Caller already priced it
    guard.record("grok-2-1212", 50, 20, agent="grok", cost_usd=0.00123)
    assert seen["cost_usd"] == 0.00123


# ---------------------------------------------------------------------------
# 3. Real broker.require adapter on Blackboard
# ---------------------------------------------------------------------------

def _broker_guard(broker: PrivilegeBroker):
    """Construction-site lambda (W6). Never built inside blackboard.py."""
    def _guard(writer: str, key: str) -> None:
        # Deliberately discards `key` — every board write is one WRITE privilege.
        broker.require(writer, Privilege.WRITE)
    return _guard


def test_blackboard_with_real_broker_raises_for_non_granted_writer():
    """W5.3 — non-granted agent cannot commit; runner can."""
    broker = PrivilegeBroker(enforce=True)
    board = Blackboard(guard=_broker_guard(broker))

    # Claude holds only READ by default → must raise
    with pytest.raises(HardPrivilegeError, match="lacks write"):
        board.commit("result", 42, writer="claude")

    # Grok holds WRITE → must succeed
    entry = board.commit("result", 42, writer="grok")
    assert entry.writer == "grok"
    assert board.get("result") == 42


def test_blackboard_real_broker_denied_write_does_not_mutate():
    """Denied write must leave the board untouched (ordering: guard then mutate)."""
    broker = PrivilegeBroker(enforce=True)
    board = Blackboard(guard=_broker_guard(broker))

    with pytest.raises(HardPrivilegeError):
        board.commit("leaked", "should-not-appear", writer="ampere")

    assert len(board) == 0
    assert board.get("leaked") is None
    assert board.history() == ()


def test_blackboard_requires_explicit_guard():
    """Fail-closed construction still holds."""
    with pytest.raises(OrcaConfigError, match="requires an explicit guard"):
        Blackboard(guard=None)
