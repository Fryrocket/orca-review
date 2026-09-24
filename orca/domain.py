from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
try:
    from enum import IntEnum, StrEnum
except ImportError:  # Python 3.10 compatibility for KILN.
    from enum import Enum, IntEnum

    class StrEnum(str, Enum):
        def __str__(self) -> str:
            return str(self.value)
from typing import Any
import uuid


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class PermissionLevel(IntEnum):
    R0 = 0
    R1 = 1
    R2 = 2
    R3 = 3


class JobStatus(StrEnum):
    DRAFT = "draft"
    WAITING_APPROVAL = "waiting_approval"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    REVIEW = "review"
    COMPLETE = "complete"
    FAILED = "failed"
    DENIED = "denied"


class IncidentStatus(StrEnum):
    OPEN = "open"
    CONTAINED = "contained"
    CLOSED = "closed"


@dataclass
class Incident:
    severity: str
    title: str
    lane: str
    owner: str
    correlation_id: str
    id: str = field(default_factory=lambda: new_id("incident"))
    status: IncidentStatus = IncidentStatus.OPEN
    detail: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class AgentIdentity:
    id: str
    name: str
    duty: str
    may_author: bool = False
    may_review: bool = False
    may_deploy: bool = False
    enabled: bool = True


@dataclass(frozen=True)
class Action:
    kind: str
    resource: str
    connector: str | None = None
    requested_level: PermissionLevel | None = None
    reversible: bool = True
    rollback: str = ""
    touches_secrets: bool = False
    spends_money: bool = False
    publishes: bool = False
    physical: bool = False
    body_impact: bool = False
    destructive: bool = False
    production: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Job:
    title: str
    lane: str
    requested_by: str
    assigned_to: str
    action: Action
    target_node: str | None = None
    id: str = field(default_factory=lambda: new_id("job"))
    correlation_id: str = field(default_factory=lambda: new_id("corr"))
    level: PermissionLevel = PermissionLevel.R0
    status: JobStatus = JobStatus.DRAFT
    approval_id: str | None = None
    reviewer: str | None = None
    task_type: str | None = None
    model_route: str | None = None
    stop_condition: str = "independent_review_complete"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
