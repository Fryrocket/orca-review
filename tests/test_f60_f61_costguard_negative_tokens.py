"""R11-F60/F61 (MEDIUM, "costguard preflight") — a crisp finding.

CostGuard.record() computed tin/tout from tokens_in/tokens_out with no
non-negativity check, then (when cost wasn't explicitly supplied, or was
<=0 with nonzero tokens) derived cost via
estimate_cost(model, tin, tout) = (tin*price_in + tout*price_out)/1e6 —
no floor. A broken or adversarial model adapter reporting a large negative
tokens_in with a small positive tokens_out produces a substantially
NEGATIVE cost. Nothing re-validates a derived cost for sign (the existing
`if cost < 0: raise` only guards caller-supplied cost_usd, not values
estimate_cost() itself produces), so that negative cost gets recorded via
record_usage() AND subtracted from both _run_usd and total_usd — silently
banking negative "spend." The hard_ceiling_usd check
(`if self._run_usd > self.hard_ceiling_usd: raise`) only fires once
_run_usd climbs back above the ceiling, so a single bad report buys an
arbitrarily large window of unmetered real spend afterward — a genuine
ceiling-bypass, not just an accounting quirk.

record() now rejects negative tokens_in/tokens_out outright, before any
cost derivation or record_usage() call — real API usage can never be
negative."""

import pytest

from mao.costguard import UsageTrackerCostGuard
from mao.errors import OrcaConfigError


def _cost_guard(hard_ceiling_usd=10.0, estimate_cost=None):
    records = []

    def record_usage(**kw):
        records.append(kw)

    def default_estimate(model, tin, tout):
        return (tin * 3.0 + tout * 15.0) / 1_000_000.0

    cg = UsageTrackerCostGuard(
        record_usage=record_usage,
        hard_ceiling_usd=hard_ceiling_usd,
        estimate_cost=estimate_cost or default_estimate,
    )
    return cg, records


def test_negative_tokens_in_raises_instead_of_banking_negative_cost():
    """The exact F60/F61 bug: this used to silently record a negative
    cost and reduce _run_usd below zero."""
    cg, records = _cost_guard()
    with pytest.raises(OrcaConfigError, match="tokens_in=-5000000"):
        cg.record("echo", tokens_in=-5_000_000, tokens_out=10, agent="claude")
    assert cg._run_usd == 0.0
    assert cg.total_usd == 0.0
    assert records == []


def test_negative_tokens_out_also_rejected():
    cg, records = _cost_guard()
    with pytest.raises(OrcaConfigError, match="tokens_out=-100"):
        cg.record("echo", tokens_in=5, tokens_out=-100, agent="claude")
    assert cg._run_usd == 0.0


def test_negative_tokens_rejected_even_with_explicit_cost_usd():
    """The rejection happens before the explicit-cost_usd branch even
    runs — negative tokens are invalid regardless of what cost_usd says."""
    cg, records = _cost_guard()
    with pytest.raises(OrcaConfigError, match="tokens_in"):
        cg.record("echo", tokens_in=-1, tokens_out=1, agent="claude", cost_usd=0.05)
    assert records == []


def test_zero_tokens_still_bill_zero_as_before():
    """Regression guard: legitimate zero-token calls must be unaffected —
    this fix only rejects negative, not zero."""
    cg, records = _cost_guard()
    cost = cg.record("echo", tokens_in=0, tokens_out=0, agent="claude")
    assert cost == 0.0
    assert cg._run_usd == 0.0


def test_positive_tokens_still_bill_normally():
    """Regression guard: the normal, correct path is completely
    unaffected by this fix."""
    cg, records = _cost_guard()
    cost = cg.record("echo", tokens_in=1000, tokens_out=500, agent="claude")
    assert cost > 0
    assert cg._run_usd == cost
    assert records[0]["cost_usd"] == cost


def test_none_tokens_still_coerce_to_zero_not_rejected():
    """tokens_in=None/tokens_out=None (unknown, not negative) must keep
    coercing to 0 as before, not get caught by the new check."""
    cg, records = _cost_guard()
    cost = cg.record("echo", tokens_in=None, tokens_out=None, agent="claude")
    assert cost == 0.0
