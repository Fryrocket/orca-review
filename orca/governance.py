from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from .domain import PermissionLevel


@dataclass(frozen=True)
class RetentionPolicy:
    artifact: str
    minimum_days: int | None
    deletion_authority: str
    notes: str


RETENTION_POLICIES = (
    RetentionPolicy("evidence", None, "fry-r3", "append-only; no automatic deletion"),
    RetentionPolicy("incidents", 2555, "fry-r3", "retain closure evidence for at least seven years"),
    RetentionPolicy("jobs-and-approvals", 365, "fry-r3", "retain decision history"),
    RetentionPolicy("cost-records", 2555, "fry-r3", "retain usage and budget evidence"),
)


ACCESS_POLICY = {
    "read_state": ("orca", "gemini", "quench", "fry"),
    "mutate_jobs": ("orca", "fry"),
    "decide_r2_r3": ("fry",),
    "close_incident": ("quench", "fry"),
    "change_emergency_stop": ("fry",),
    "delete_evidence": (),
}


@dataclass(frozen=True)
class RetentionRecord:
    artifact: str
    record_id: str
    created_at: str


@dataclass(frozen=True)
class RetentionAssessment:
    artifact: str
    record_id: str
    status: str
    age_days: int
    minimum_days: int | None


class RetentionGuard:
    """Dry-run retention enforcement. It never deletes records."""

    def __init__(self) -> None:
        self.policies = {policy.artifact: policy for policy in RETENTION_POLICIES}

    @staticmethod
    def _timestamp(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("retention timestamps must include a timezone")
        return parsed.astimezone(timezone.utc)

    def assess(self, record: RetentionRecord, *, now: str) -> RetentionAssessment:
        try:
            policy = self.policies[record.artifact]
        except KeyError as exc:
            raise ValueError(f"no retention policy for artifact: {record.artifact}") from exc
        current = self._timestamp(now)
        created = self._timestamp(record.created_at)
        if created > current:
            raise ValueError("retention record timestamp is in the future")
        age_days = (current - created).days
        if policy.minimum_days is None:
            status = "indefinite"
        elif age_days < policy.minimum_days:
            status = "retained"
        else:
            status = "eligible_for_fry_r3_review"
        return RetentionAssessment(
            record.artifact, record.record_id, status, age_days, policy.minimum_days)

    def assert_deletion_allowed(self, record: RetentionRecord, *, now: str,
                                actor: str, approved_level: PermissionLevel) -> RetentionAssessment:
        assessment = self.assess(record, now=now)
        if record.artifact == "evidence":
            raise PermissionError("evidence deletion is prohibited")
        if actor != "fry" or approved_level is not PermissionLevel.R3:
            raise PermissionError("retention disposal requires Fry R3 approval")
        if assessment.status != "eligible_for_fry_r3_review":
            raise PermissionError("record has not reached its minimum retention period")
        return assessment

    def audit(self, records: list[RetentionRecord], *, now: str) -> dict:
        assessments = [asdict(self.assess(record, now=now)) for record in records]
        counts = {status: sum(row["status"] == status for row in assessments) for status in (
            "indefinite", "retained", "eligible_for_fry_r3_review")}
        return {
            "mode": "dry_run",
            "automatic_deletions": 0,
            "record_count": len(assessments),
            "counts": counts,
            "assessments": assessments,
        }


def governance_snapshot() -> dict:
    return {"retention": [asdict(policy) for policy in RETENTION_POLICIES],
            "access": ACCESS_POLICY,
            "retention_enforcement": {
                "mode": "deny-by-default",
                "automatic_deletion": False,
                "evidence_deletion": False,
                "expired_records_require": "Fry R3 review",
            }}
