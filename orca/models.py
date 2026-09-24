from __future__ import annotations

from dataclasses import dataclass
import math

from .domain import PermissionLevel


@dataclass(frozen=True)
class ModelRoute:
    job_type: str
    primary: str
    fallback: str
    local_first: bool = True
    monthly_hard_cap_usd: float = 0.0


DEFAULT_ROUTES = {
    "orchestration": ModelRoute("orchestration", "deterministic-policy", "human-runbook"),
    "coding": ModelRoute("coding", "smith-local", "approved-cloud-coder"),
    "review": ModelRoute("review", "quench-local", "human-review"),
    "monitoring": ModelRoute("monitoring", "small-local-model", "operations-runbook"),
    "documentation": ModelRoute("documentation", "local-model", "approved-cloud-synthesis"),
}


class ModelRouter:
    def __init__(self, routes: dict[str, ModelRoute] | None = None) -> None:
        self.routes = routes or dict(DEFAULT_ROUTES)

    def select(self, job_type: str, *, local_capable: bool = True,
               cloud_approved: bool = False, cloud_approved_by: str | None = None,
               approved_level: PermissionLevel | None = None,
               estimated_cost_usd: float = 0.0) -> str:
        route = self.routes[job_type]
        if type(local_capable) is not bool or type(cloud_approved) is not bool:
            raise ValueError("model route capability and approval flags must be booleans")
        if (isinstance(route.monthly_hard_cap_usd, bool)
                or not isinstance(route.monthly_hard_cap_usd, (int, float))
                or not math.isfinite(route.monthly_hard_cap_usd)
                or route.monthly_hard_cap_usd < 0):
            raise ValueError("model route cap must be finite and non-negative")
        if (isinstance(estimated_cost_usd, bool)
                or not isinstance(estimated_cost_usd, (int, float))
                or not math.isfinite(estimated_cost_usd) or estimated_cost_usd < 0):
            raise ValueError("cloud cost estimate cannot be negative")
        if local_capable:
            return route.primary
        if (not cloud_approved or cloud_approved_by != "fry"
                or approved_level is not PermissionLevel.R3):
            raise PermissionError("cloud escalation requires explicit Fry R3 approval")
        if route.monthly_hard_cap_usd <= 0 or estimated_cost_usd > route.monthly_hard_cap_usd:
            raise PermissionError("cloud escalation has no approved budget or exceeds its cap")
        return route.fallback
