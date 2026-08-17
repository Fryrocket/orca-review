"""Usage tracking with preflight + ordered record-then-raise."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .cost_store import DayCostStore
from .errors import CostCapExceeded, HardPrivilegeError, OrcaConfigError


@dataclass
class UsageRecord:
    agent: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    posted: bool = False  # True once the day ledger accepted the charge


@dataclass
class UsageTracker:
    records: List[UsageRecord] = field(default_factory=list)
    per_run_ceiling_usd: Optional[float] = None
    per_day_ceiling_usd: Optional[float] = None
    kill_switch: bool = False
    _run_cost: float = 0.0
    day_store: Optional[DayCostStore] = None

    def __post_init__(self):
        profile = (os.environ.get("ORCA_PROFILE") or "").lower()
        if profile in {"pi5", "pi", "power"}:
            if self.per_run_ceiling_usd is None or self.per_day_ceiling_usd is None:
                raise HardPrivilegeError(
                    "PI5 profile requires per_run_ceiling_usd and per_day_ceiling_usd"
                )
        if self.day_store is None:
            # D1: never swallow. A missing ORCA_REPO_ROOT must not silently
            # turn the per-day cap into a no-op; it must stop construction.
            self.day_store = DayCostStore()

    def reset_run(self) -> None:
        self._run_cost = 0.0

    def preflight(self, estimated_cost_usd: float) -> None:
        if self.kill_switch:
            raise CostCapExceeded("kill_switch ON")
        if self.per_run_ceiling_usd is not None:
            if self._run_cost + estimated_cost_usd > self.per_run_ceiling_usd:
                raise CostCapExceeded(
                    f"preflight per-run exceeded "
                    f"(spent ${self._run_cost:.4f} + est ${estimated_cost_usd:.4f} "
                    f"> ${self.per_run_ceiling_usd})"
                )
        if self.per_day_ceiling_usd is not None:
            rem = self.day_store.remaining(self.per_day_ceiling_usd)
            if estimated_cost_usd > rem:
                raise CostCapExceeded(
                    f"preflight per-day exceeded (est ${estimated_cost_usd:.4f} "
                    f"> remaining ${rem:.4f})"
                )

    def record(self, agent, model, input_tokens=0, output_tokens=0, cost_usd=0.0) -> None:
        if self.kill_switch:
            raise CostCapExceeded("kill_switch ON")
        # N5: the transaction is recorded BEFORE any ceiling can raise, so a
        # breach never loses the usage. `posted` distinguishes "in our tally"
        # from "in the durable ledger" when the ledger refuses the charge.
        rec = UsageRecord(agent, model, input_tokens, output_tokens, cost_usd)
        self.records.append(rec)
        self._run_cost += cost_usd
        self.day_store.add(cost_usd, ceiling=self.per_day_ceiling_usd)
        rec.posted = True
        if self.per_run_ceiling_usd is not None and self._run_cost > self.per_run_ceiling_usd:
            raise CostCapExceeded(f"per-run ceiling exceeded (${self._run_cost:.4f})")

    def unposted(self) -> List[UsageRecord]:
        """Charges counted locally that the day ledger never accepted."""
        return [r for r in self.records if not r.posted]

    def total_tokens(self) -> int:
        return sum(r.input_tokens + r.output_tokens for r in self.records)

    def total_cost(self, posted_only: bool = False) -> float:
        return sum(r.cost_usd for r in self.records if r.posted or not posted_only)

    def by_agent(self) -> Dict[str, dict]:
        out: Dict[str, dict] = {}
        for r in self.records:
            slot = out.setdefault(r.agent, {"input": 0, "output": 0, "cost": 0.0})
            slot["input"] += r.input_tokens
            slot["output"] += r.output_tokens
            slot["cost"] += r.cost_usd
        return out


# Re-exported so callers can catch config failures without importing errors.
__all__ = ["UsageRecord", "UsageTracker", "OrcaConfigError"]
