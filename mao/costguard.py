"""CostGuard protocol adapter for Orchestrator.

Thin surface that forces real estimate_cost billing.
record() returns the billed float so StepResult can see it (R11-F5).
Pricing errors (UnknownModelError, PriceTableStaleError) propagate (R11-F9).
"""

from __future__ import annotations

from typing import Callable, Optional, Protocol

from .errors import CostCapExceeded, OrcaConfigError
from .pricing import estimate_cost as default_estimate_cost


class CostGuard(Protocol):
    def preflight(self, model: str, prompt: str, **meta) -> None: ...
    def record(
        self,
        model: str,
        tokens_in: Optional[int],
        tokens_out: Optional[int],
        **meta,
    ) -> float: ...
    def reset_run(self) -> None: ...


class UsageTrackerCostGuard:
    """Adapts UsageTracker / free functions to the CostGuard protocol.

    Required:
      estimate_cost: (model, input_tokens, output_tokens) -> float
      record_usage: (agent, model, input_tokens=0, output_tokens=0, cost_usd=0.0) -> None

    hard_ceiling_usd is optional but recommended. When None, per-run ceiling
    checks are skipped (documented fail-open for test profiles only).
    """

    def __init__(
        self,
        *,
        estimate_cost: Callable[[str, int, int], float] = default_estimate_cost,
        record_usage: Callable[..., None],
        hard_ceiling_usd: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
    ):
        self.estimate_cost = estimate_cost
        self.record_usage = record_usage
        self.hard_ceiling_usd = hard_ceiling_usd
        self.max_output_tokens = max_output_tokens
        self.total_usd: float = 0.0
        self._run_usd: float = 0.0

    def preflight(self, model: str, prompt: str, **meta) -> None:
        est = meta.get("estimated_cost_usd")
        if est is None:
            approx_in = max(1, len(prompt) // 4)
            approx_out = meta.get("max_output_tokens") or self.max_output_tokens or 512
            # Do NOT swallow UnknownModelError / PriceTableStaleError (R11-F9)
            est = float(self.estimate_cost(model, approx_in, int(approx_out)))
        if self.hard_ceiling_usd is not None and (self._run_usd + float(est)) > self.hard_ceiling_usd:
            raise CostCapExceeded(
                f"CostGuard preflight would exceed hard_ceiling_usd={self.hard_ceiling_usd} "
                f"(spent ${self._run_usd:.4f} + est ${float(est):.4f})"
            )

    def record(
        self,
        model: str,
        tokens_in: Optional[int],
        tokens_out: Optional[int],
        **meta,
    ) -> float:
        """Record usage and return the actual billed cost (R11-F5)."""
        agent = meta.get("agent", "unknown")
        tin = 0 if tokens_in is None else int(tokens_in)
        tout = 0 if tokens_out is None else int(tokens_out)

        cost = meta.get("cost_usd")
        if cost is None:
            if tin == 0 and tout == 0:
                cost = 0.0
            else:
                cost = float(self.estimate_cost(model, tin, tout))
        else:
            cost = float(cost)
            if cost < 0:
                raise OrcaConfigError(
                    f"cost_usd must be >= 0 (got {cost}). Refusing negative billing."
                )
            # If caller reported 0.0 but we have tokens, still derive (avoid undercount)
            if cost <= 0.0 and (tin > 0 or tout > 0):
                cost = float(self.estimate_cost(model, tin, tout))

        self.record_usage(
            agent=agent,
            model=model,
            input_tokens=tin,
            output_tokens=tout,
            cost_usd=cost,
        )
        self._run_usd += cost
        self.total_usd += cost

        if self.hard_ceiling_usd is not None and self._run_usd > self.hard_ceiling_usd:
            raise CostCapExceeded(
                f"CostGuard hard_ceiling_usd={self.hard_ceiling_usd} exceeded "
                f"(${self._run_usd:.4f})"
            )
        return cost

    def reset_run(self) -> None:
        self._run_usd = 0.0
