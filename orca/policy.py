from __future__ import annotations

from dataclasses import dataclass

from .domain import Action, AgentIdentity, PermissionLevel


class PolicyViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class PolicyDecision:
    level: PermissionLevel
    requires_approval: bool
    approver: str | None
    rationale: tuple[str, ...]


class PolicyEngine:
    """Classify actions using the adopted R0-R3 permission ladder."""

    R0_KINDS = {"read", "observe", "analyze"}
    R1_KINDS = {"create", "edit", "update", "change", "configure"}
    R2_KINDS = {
        "restore", "grant", "revoke", "connector_write", "commit", "open_pr",
        "restart", "reboot", "shutdown", "migrate", "failover",
    }
    R3_KINDS = {
        "merge", "push", "deploy", "remote_execute", "delete", "remove",
        "destroy", "erase", "wipe", "drop", "truncate", "format", "publish",
        "release", "spend", "cutover", "archive_legacy", "secret_access",
        "credential_change",
    }

    @staticmethod
    def normalize_kind(kind: str) -> str:
        if not isinstance(kind, str) or not kind.strip():
            raise ValueError("action kind must be non-empty text")
        return kind.strip().lower().replace("-", "_").replace(" ", "_")

    def classify(self, action: Action) -> PolicyDecision:
        kind = self.normalize_kind(action.kind)
        if (not isinstance(action.resource, str) or not action.resource.strip()
                or (action.connector is not None and not isinstance(action.connector, str))
                or not isinstance(action.rollback, str) or not isinstance(action.metadata, dict)):
            raise ValueError("action fields have invalid types")
        flags = (
            action.reversible, action.touches_secrets, action.spends_money,
            action.publishes, action.physical, action.body_impact,
            action.destructive, action.production,
        )
        if any(type(flag) is not bool for flag in flags):
            raise ValueError("action impact flags must be booleans")
        requested_level = None
        if action.requested_level is not None:
            if type(action.requested_level) not in {int, PermissionLevel}:
                raise ValueError("requested permission level is invalid")
            try:
                requested_level = PermissionLevel(action.requested_level)
            except (TypeError, ValueError) as exc:
                raise ValueError("requested permission level is invalid") from exc
        reasons: list[str] = []
        level = PermissionLevel.R0

        changes_state = kind not in self.R0_KINDS
        if changes_state:
            level = PermissionLevel.R1
            reasons.append("action changes state")
        if changes_state and (not action.reversible or not action.rollback):
            level = max(level, PermissionLevel.R2)
            reasons.append("rollback is absent or action is not readily reversible")
        if kind in self.R2_KINDS:
            level = max(level, PermissionLevel.R2)
            reasons.append("material operational action")
        if kind not in self.R0_KINDS | self.R1_KINDS | self.R2_KINDS | self.R3_KINDS:
            level = max(level, PermissionLevel.R2)
            reasons.append("unknown action kind requires human classification")
        if kind in self.R3_KINDS or action.production:
            level = PermissionLevel.R3
            reasons.append("Fry-only R3 action or production impact")
        if any((action.touches_secrets, action.spends_money, action.publishes,
                action.physical, action.body_impact, action.destructive)):
            level = PermissionLevel.R3
            reasons.append("R3 impact flag present")
        if requested_level is not None:
            level = max(level, requested_level)
            reasons.append("caller requested a higher classification")

        return PolicyDecision(
            level=level,
            requires_approval=level >= PermissionLevel.R2,
            approver="fry" if level >= PermissionLevel.R2 else None,
            rationale=tuple(reasons or ["read-only observation or analysis"]),
        )

    def enforce_separation(
        self,
        *,
        author: AgentIdentity,
        reviewer: AgentIdentity | None,
        deployer: AgentIdentity | None,
        action: Action | None = None,
    ) -> None:
        identities = [x.id for x in (author, reviewer, deployer) if x is not None]
        if len(identities) != len(set(identities)):
            raise PolicyViolation("no identity may author, approve/review, and deploy the same change")
        writes = action is None or self.normalize_kind(action.kind) not in self.R0_KINDS
        if writes and not author.may_author:
            raise PolicyViolation(f"{author.name} is not an author/implementer")
        if reviewer is not None and not reviewer.may_review:
            raise PolicyViolation(f"{reviewer.name} is not an independent reviewer")
        if deployer is not None and not deployer.may_deploy:
            raise PolicyViolation(f"{deployer.name} may not deploy")
