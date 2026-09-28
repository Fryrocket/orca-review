from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import wraps
from copy import deepcopy
import threading
import json
import math
import time
from datetime import datetime, timedelta, timezone

from .domain import Action, Incident, IncidentStatus, Job, JobStatus, PermissionLevel, new_id, utc_now
from .security import redact, redact_text
from .bots import BOT_BUILD_QUEUE, BotRegistry, MIGRATION_CANDIDATES
from .evidence import EvidenceStore
from .policy import PolicyEngine, PolicyViolation
from .registry import AGENTS, CONNECTORS, LANES, NODES
from .roles import role_snapshot
from .state import StateStore, job_from_dict, job_to_dict
from .costs import CostLedger
from .runtime import PROMPT_CONTRACTS
from .tools import BOT_TOOL_MANIFESTS, TOOL_CATALOG
from .connectors import ConnectorGateway
from .fleet import FleetAuthenticator, Heartbeat
from .governance import RetentionGuard, RetentionRecord, governance_snapshot
from .security_gate import IndependentSecurityGate
from .idempotency import IdempotencyStore, StateRevisionConflict
from .notifications import (
    Alert,
    DeliveryOutcome,
    NotificationClaimBatch,
    NotificationConflict,
    NotificationOutbox,
)
from .placement import placement_snapshot
from .ai_stack import ladder_snapshot
from .business import BusinessStore
from .product_development import build_product_development_plan
from .inventory_workflows import (
    calculate_inventory_changes,
    validate_inventory_operation,
)
from .inventory_count import build_count_reconciliation
from hashlib import sha256
from typing import Callable, Any


def _parse_epoch(value: object) -> float:
    """Strictly convert a legacy alert timestamp during one-time restoration."""

    if (not isinstance(value, str) or not value
            or len(value) > 64):
        raise ValueError("legacy alert timestamp is invalid")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("legacy alert timestamp is invalid")
    epoch = parsed.timestamp()
    if not math.isfinite(epoch):
        raise ValueError("legacy alert timestamp is invalid")
    return epoch


def synchronized(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._mutation_lock:
            outermost = self._transaction_depth == 0
            previous = self._capture_mutable_state() if outermost else None
            self._transaction_depth += 1
            try:
                if outermost:
                    with self.evidence.transaction():
                        return method(self, *args, **kwargs)
                return method(self, *args, **kwargs)
            except BaseException:
                if outermost and previous is not None:
                    self._restore_mutable_state(previous)
                raise
            finally:
                self._transaction_depth -= 1
    return wrapper


def read_synchronized(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._mutation_lock:
            return method(self, *args, **kwargs)
    return wrapper


@dataclass
class Approval:
    job_id: str
    level: PermissionLevel
    requested_from: str = "fry"
    id: str = ""
    status: str = "pending"
    decided_by: str | None = None
    note: str = ""
    rationale: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id:
            self.id = new_id("approval")


class ControlPlane:
    def __init__(self, evidence: EvidenceStore | None = None) -> None:
        self._mutation_lock = threading.RLock()
        self._transaction_depth = 0
        self.evidence = evidence or EvidenceStore()
        self.state_store = StateStore(
            self.evidence.db, connection_lock=self.evidence._lock)
        if not self.evidence.verify():
            raise RuntimeError("evidence chain integrity check failed")
        self.state_store.verify_integrity()
        self.costs = CostLedger(self.evidence.db, connection_lock=self.evidence._lock)
        self.idempotency = IdempotencyStore(
            self.evidence.db, connection_lock=self.evidence._lock)
        self.idempotency.verify()
        self.business = BusinessStore(
            self.evidence.db, connection_lock=self.evidence._lock)
        self.policy = PolicyEngine()
        self.connector_gateway = ConnectorGateway()
        self.bots = BotRegistry()
        self.jobs: dict[str, Job] = {}
        self.approvals: dict[str, Approval] = {}
        self.incidents: dict[str, Incident] = {}
        self.security_reports: list[dict] = []
        self.security_adjudications: list[dict] = []
        self.security_exceptions: list[dict] = []
        self.retention_audits: list[dict] = []
        self.notifications = NotificationOutbox()
        self.paused_lanes: set[str] = set()
        self.paused_nodes: set[str] = set()
        self.node_health: dict[str, dict] = {
            node_id: {"state": "unproven", "last_verified": None, "detail": "no runtime probe"}
            for node_id in NODES
        }
        self.node_enrollments: dict[str, dict] = {}
        self.fleet_auth = FleetAuthenticator(self.node_enrollments)
        self.emergency_stop = False
        self.state_revision = 0
        self._restore_state()

    def _capture_mutable_state(self) -> dict:
        return {
            "jobs": deepcopy(self.jobs),
            "approvals": deepcopy(self.approvals),
            "incidents": deepcopy(self.incidents),
            "security_reports": deepcopy(self.security_reports),
            "security_adjudications": deepcopy(self.security_adjudications),
            "security_exceptions": deepcopy(self.security_exceptions),
            "retention_audits": deepcopy(self.retention_audits),
            "notification_state": self.notifications.to_dict(),
            "paused_lanes": set(self.paused_lanes),
            "paused_nodes": set(self.paused_nodes),
            "paused_bots": set(self.bots.paused),
            "node_health": deepcopy(self.node_health),
            "node_enrollments": deepcopy(self.node_enrollments),
            "emergency_stop": self.emergency_stop,
            "state_revision": self.state_revision,
        }

    def _restore_mutable_state(self, saved: dict) -> None:
        for current, previous in (
            (self.jobs, saved["jobs"]),
            (self.approvals, saved["approvals"]),
            (self.incidents, saved["incidents"]),
        ):
            for key in set(current) - set(previous):
                del current[key]
            for key, previous_value in previous.items():
                if key in current:
                    current[key].__dict__.clear()
                    current[key].__dict__.update(deepcopy(previous_value.__dict__))
                else:
                    current[key] = deepcopy(previous_value)
        self.security_reports[:] = deepcopy(saved["security_reports"])
        self.security_adjudications[:] = deepcopy(saved["security_adjudications"])
        self.security_exceptions[:] = deepcopy(saved["security_exceptions"])
        self.retention_audits[:] = deepcopy(saved["retention_audits"])
        self.notifications = NotificationOutbox.from_dict(saved["notification_state"])
        self.paused_lanes.clear()
        self.paused_lanes.update(saved["paused_lanes"])
        self.paused_nodes.clear()
        self.paused_nodes.update(saved["paused_nodes"])
        self.bots.paused.clear()
        self.bots.paused.update(saved["paused_bots"])
        self.node_health.clear()
        self.node_health.update(deepcopy(saved["node_health"]))
        self.node_enrollments.clear()
        self.node_enrollments.update(deepcopy(saved["node_enrollments"]))
        self.emergency_stop = saved["emergency_stop"]
        self.state_revision = saved["state_revision"]

    def _restore_state(self) -> None:
        self.state_revision, saved = self.state_store.load()
        if not saved:
            return
        saved = redact(saved)
        self.jobs = {row["id"]: job_from_dict(row) for row in saved.get("jobs", [])}
        self.approvals = {
            row["id"]: Approval(
                job_id=row["job_id"], level=PermissionLevel(row["level"]),
                requested_from=row.get("requested_from", "fry"), id=row["id"],
                status=row["status"], decided_by=row.get("decided_by"),
                note=row.get("note", ""), rationale=tuple(row.get("rationale", ())))
            for row in saved.get("approvals", [])
        }
        self.incidents = {
            row["id"]: Incident(**{**row, "status": IncidentStatus(row["status"])})
            for row in saved.get("incidents", [])
        }
        self.security_reports = list(saved.get("security_reports", []))
        self.security_adjudications = list(saved.get("security_adjudications", []))
        self.security_exceptions = list(saved.get("security_exceptions", []))
        self.retention_audits = list(saved.get("retention_audits", []))
        notification_state = saved.get("notification_state")
        if notification_state is not None:
            self.notifications = NotificationOutbox.from_dict(notification_state)
        else:
            # One-time compatibility import for pre-notification snapshots.
            self.notifications = NotificationOutbox()
            for legacy in saved.get("alert_outbox", []):
                self.notifications.enqueue(
                    alert_id=str(legacy["id"]),
                    idempotency_key=str(legacy.get("incident_id", legacy["id"])),
                    payload={
                        "connector": legacy.get("connector", "slack"),
                        "incident_id": legacy.get("incident_id"),
                        "severity": legacy.get("severity"),
                    },
                    now=_parse_epoch(legacy.get("created_at")),
                )
        self.paused_lanes = set(saved.get("paused_lanes", []))
        self.paused_nodes = set(saved.get("paused_nodes", []))
        self.bots.paused = set(saved.get("paused_bots", []))
        self.emergency_stop = bool(saved.get("emergency_stop", False))
        self.node_enrollments.update(saved.get("node_enrollments", {}))
        for node_id, health in saved.get("node_health", {}).items():
            if node_id in self.node_health:
                self.node_health[node_id] = health

    def _persist(self) -> None:
        self.state_revision = self.state_store.save({
            "jobs": [job_to_dict(job) for job in self.jobs.values()],
            "approvals": [{**asdict(approval), "level": int(approval.level)}
                          for approval in self.approvals.values()],
            "incidents": [{**asdict(incident), "status": incident.status.value}
                          for incident in self.incidents.values()],
            "security_reports": self.security_reports,
            "security_adjudications": self.security_adjudications,
            "security_exceptions": self.security_exceptions,
            "retention_audits": self.retention_audits,
            "notification_state": self.notifications.to_dict(),
            "paused_lanes": sorted(self.paused_lanes),
            "paused_nodes": sorted(self.paused_nodes),
            "paused_bots": sorted(self.bots.paused),
            "node_health": self.node_health,
            "node_enrollments": self.node_enrollments,
            "emergency_stop": self.emergency_stop,
        }, expected_revision=self.state_revision)

    def _assert_integrity(self) -> None:
        if not self.evidence.verify():
            raise RuntimeError("evidence chain integrity check failed")
        self.state_store.verify_integrity()
        self.idempotency.verify()
        if not self.business.verify():
            raise RuntimeError("business ledger integrity check failed")

    def _assert_fresh(self) -> None:
        self._assert_integrity()
        if self.state_store.current_revision() != self.state_revision:
            raise RuntimeError("stale control-plane instance; reload before mutation")

    @read_synchronized
    def assert_fresh(self) -> None:
        """Public read boundary for threaded health and subsystem endpoints."""
        self._assert_fresh()

    @synchronized
    def execute_idempotent(
            self, *, key: str, actor: str, operation: str,
            request_hash: str, expected_revision: int,
            mutation: Callable[[], tuple[dict[str, Any], int]],
    ) -> tuple[dict[str, Any], int, bool, int]:
        """Run one mutation and persist its replay receipt in the same transaction."""

        # Replays may legitimately carry an old expected revision, but they may
        # never bypass evidence, state, or receipt-integrity verification.
        self._assert_integrity()
        receipt = self.idempotency.lookup(
            key=key, actor=actor, operation=operation, request_hash=request_hash)
        if receipt is not None:
            return (
                receipt.response, receipt.http_status, True,
                receipt.state_revision,
            )
        if self.state_store.current_revision() != self.state_revision:
            raise RuntimeError("stale control-plane instance; reload before mutation")
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("expected state revision must be a nonnegative integer")
        if expected_revision != self.state_revision:
            raise StateRevisionConflict("expected state revision is stale")
        response, http_status = mutation()
        receipt = self.idempotency.record(
            key=key, actor=actor, operation=operation,
            request_hash=request_hash, response=response,
            http_status=http_status, state_revision=self.state_revision,
        )
        return (
            receipt.response, receipt.http_status, False,
            receipt.state_revision,
        )

    @staticmethod
    def _require_actor(actor: str, allowed: set[str], action: str) -> None:
        if actor not in AGENTS:
            raise ValueError(f"{action} requires a registered identity")
        if actor not in allowed:
            raise PermissionError(f"{actor} may not {action}")

    @staticmethod
    def _safe_action(action: Action) -> Action:
        return Action(
            kind=PolicyEngine.normalize_kind(action.kind),
            resource=redact_text(action.resource),
            connector=redact_text(action.connector) if action.connector else None,
            requested_level=(PermissionLevel(action.requested_level)
                             if action.requested_level is not None else None),
            reversible=action.reversible,
            rollback=redact_text(action.rollback),
            touches_secrets=action.touches_secrets,
            spends_money=action.spends_money,
            publishes=action.publishes,
            physical=action.physical,
            body_impact=action.body_impact,
            destructive=action.destructive,
            production=action.production,
            metadata=redact(action.metadata),
        )

    @synchronized
    def submit(self, *, title: str, lane: str, requested_by: str,
               assigned_to: str, action: Action, target_node: str | None = None,
               task_type: str | None = None, model_route: str | None = None,
               stop_condition: str = "independent_review_complete") -> Job:
        self._assert_fresh()
        if lane not in LANES:
            raise ValueError(f"unknown project lane: {lane}")
        if requested_by not in AGENTS or assigned_to not in AGENTS:
            raise ValueError("every action must have registered identities")
        self._require_actor(requested_by, {"orca", "fry"}, "submit work")
        if not title.strip() or len(title) > 500:
            raise ValueError("job title must be concise and non-empty")
        if not stop_condition.strip() or len(stop_condition) > 240:
            raise ValueError("job stop condition must be concise and non-empty")
        if task_type is not None and len(task_type) > 120:
            raise ValueError("job task type is too long")
        if model_route is not None and len(model_route) > 120:
            raise ValueError("job model route is too long")
        if target_node is not None:
            if target_node not in NODES:
                raise ValueError(f"unknown fleet node: {target_node}")
            if NODES[target_node].lane != lane:
                raise ValueError("target node must belong to the job lane")
        decision = self.policy.classify(action)
        action_kind = self.policy.normalize_kind(action.kind)
        if action_kind not in self.policy.R0_KINDS and not AGENTS[assigned_to].may_author:
            raise PolicyViolation("state-changing work requires an author-capable assignee")
        safe_action = self._safe_action(action)
        try:
            encoded_action = json.dumps(
                asdict(safe_action), sort_keys=True, separators=(",", ":"),
                allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("job action must be JSON serializable") from exc
        if len(encoded_action.encode("utf-8")) > 64_000:
            raise ValueError("job action exceeds the size limit")
        job = Job(redact_text(title.strip()), lane, requested_by, assigned_to,
                  safe_action,
                  target_node=target_node, level=decision.level,
                  task_type=redact_text(task_type) if task_type else None,
                  model_route=redact_text(model_route) if model_route else None,
                  stop_condition=redact_text(stop_condition))
        if decision.requires_approval:
            approval = Approval(job.id, decision.level, rationale=decision.rationale)
            self.approvals[approval.id] = approval
            job.approval_id = approval.id
            job.status = JobStatus.WAITING_APPROVAL
        else:
            job.status = JobStatus.READY
        if (self.emergency_stop or lane in self.paused_lanes
                or target_node in self.paused_nodes or assigned_to in self.bots.paused
                or (target_node is not None
                    and self.node_health[target_node]["state"] != "healthy")):
            job.status = JobStatus.PAUSED
        self.jobs[job.id] = job
        self.evidence.append(
            correlation_id=job.correlation_id, actor=requested_by, lane=lane,
            kind="job.submitted",
            payload={"job_id": job.id, "level": job.level.name,
                     "status": job.status, "rationale": decision.rationale,
                     "task_type": task_type, "model_route": model_route,
                     "stop_condition": stop_condition},
        )
        self._persist()
        return job

    @synchronized
    def queue(self, *, title: str, lane: str, requested_by: str,
              task_type: str, action: Action, target_node: str | None = None) -> Job:
        bot = self.bots.route(task_type, lane)
        job = self.submit(title=title, lane=lane, requested_by=requested_by,
                          assigned_to=bot.id, action=action, target_node=target_node,
                          task_type=task_type, model_route=bot.model_route)
        self.evidence.append(
            correlation_id=job.correlation_id, actor="orca", lane=lane,
            kind="job.routed",
            payload={"job_id": job.id, "bot_id": bot.id, "task_type": task_type,
                     "model_route": bot.model_route, "runtime_enabled": bot.runtime_enabled},
        )
        self._persist()
        return job

    @synchronized
    def start_business_workflow(self, *, workflow_id: str, title: str,
                                requested_by: str) -> Job:
        """Create and start one bounded Business workspace analysis job.

        The browser may select the workflow, but it cannot choose the actor,
        permission level, impact flags, lane, assignee, or rollback contract.
        Those security-relevant fields are fixed here.
        """

        self._assert_fresh()
        if (not isinstance(workflow_id, str) or not workflow_id.strip()
                or len(workflow_id) > 120
                or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-_"
                       for character in workflow_id)):
            raise ValueError("business workflow id is invalid")
        if not isinstance(title, str) or not title.strip() or len(title) > 160:
            raise ValueError("business workflow title is invalid")
        job = self.submit(
            title=f"Business · {title.strip()}",
            lane="orca",
            requested_by=requested_by,
            assigned_to="orca",
            action=Action(
                kind="analyze",
                resource=f"business-workflow:{workflow_id}",
                reversible=True,
                rollback="Stop the job; no external state was changed.",
                metadata={
                    "workflow_id": workflow_id,
                    "source": "studio_business_workspace",
                    "execution_scope": "read_analyze_draft_verify_record",
                },
            ),
            task_type="business_workflow",
            model_route="orchestration",
            stop_condition="result_recorded_and_independent_review_complete",
        )
        if job.status is JobStatus.READY:
            self.start_job(job.id, actor="orca")
        return job

    @read_synchronized
    def require_running_business_workflow(self, job_id: str) -> Job:
        """Validate a workflow lease before performing model work."""

        self._assert_fresh()
        if not isinstance(job_id, str) or job_id not in self.jobs:
            raise ValueError("business workflow job is unknown")
        job = self.jobs[job_id]
        if (job.task_type != "business_workflow" or job.assigned_to != "orca"
                or job.status is not JobStatus.RUNNING):
            raise ValueError("business workflow job is not running")
        return deepcopy(job)

    @synchronized
    def record_business_workflow_result(
            self, job_id: str, *, success: bool, result_sha256: str,
            result_bytes: int, routed_mode: str = "") -> Job:
        """Attach model-result evidence without storing the conversation body."""

        self._assert_fresh()
        if not isinstance(job_id, str) or job_id not in self.jobs:
            raise ValueError("business workflow job is unknown")
        job = self.jobs[job_id]
        if (job.task_type != "business_workflow" or job.assigned_to != "orca"
                or job.status is not JobStatus.RUNNING):
            raise ValueError("business workflow job is not running")
        if type(success) is not bool:
            raise ValueError("business workflow result state is invalid")
        if (not isinstance(result_sha256, str) or len(result_sha256) != 64
                or any(character not in "0123456789abcdef" for character in result_sha256)):
            raise ValueError("business workflow result digest is invalid")
        if type(result_bytes) is not int or not 0 <= result_bytes <= 1_000_000:
            raise ValueError("business workflow result size is invalid")
        if not isinstance(routed_mode, str) or len(routed_mode) > 80:
            raise ValueError("business workflow route is invalid")
        self.evidence.append(
            correlation_id=job.correlation_id,
            actor="orca",
            lane=job.lane,
            kind="business.workflow.result" if success else "business.workflow.failed",
            payload={
                "job_id": job.id,
                "result_sha256": result_sha256,
                "result_bytes": result_bytes,
                "routed_mode": redact_text(routed_mode),
            },
        )
        if success:
            self.policy.enforce_separation(
                author=AGENTS["orca"], reviewer=AGENTS["quench"],
                deployer=None, action=job.action)
            job.reviewer = "quench"
            job.status = JobStatus.REVIEW
            job.updated_at = utc_now()
            self.evidence.append(
                correlation_id=job.correlation_id,
                actor="orca",
                lane=job.lane,
                kind="job.review_requested",
                payload={"job_id": job.id, "reviewer": "quench"},
            )
            self._persist()
            return job
        job.status = JobStatus.FAILED
        job.updated_at = utc_now()
        self._persist()
        return job

    @synchronized
    def upsert_business_record(
            self, *, record_type: str, record_id: str, source_system: str,
            source_revision: int, status: str, data: dict,
            provenance: dict, confidence: float, requested_by: str,
            occurred_at: str | None = None) -> dict:
        """Record one source observation without granting connector authority."""

        self._assert_fresh()
        self._require_actor(requested_by, {"orca", "fry"}, "record business facts")
        correlation_id = new_id("business_corr")
        written = self.business.upsert(
            record_type=record_type, record_id=record_id,
            source_system=source_system, source_revision=source_revision,
            status=status, data=data, provenance=provenance,
            confidence=confidence, actor=requested_by,
            correlation_id=correlation_id, occurred_at=occurred_at,
        )
        if not written.replayed:
            self.evidence.append(
                correlation_id=correlation_id, actor=requested_by, lane="orca",
                kind="business.record.observed",
                payload={
                    "event_id": written.event["event_id"],
                    "record_type": record_type,
                    "record_id": record_id,
                    "source_system": source_system,
                    "source_revision": source_revision,
                    "record_hash": written.record["record_hash"],
                },
            )
            self._persist()
        return {
            "record": written.record,
            "event": written.event,
            "replayed": written.replayed,
        }

    @synchronized
    def create_product_development_plan(
            self, *, prompt: str, inventory: dict | None,
            requested_by: str) -> dict:
        """Create one governed, canonical product-development concept record."""

        self._assert_fresh()
        self._require_actor(requested_by, {"orca", "fry"}, "create product plans")
        plan = build_product_development_plan(prompt, inventory)
        job = self.submit(
            title=f"Product development · {plan['product_name']}",
            lane="orca", requested_by=requested_by, assigned_to="orca",
            action=Action(
                kind="analyze",
                resource=f"product-development:{plan['product_id']}",
                reversible=True,
                rollback="Archive the draft concept record; no external system was changed.",
                metadata={
                    "product_id": plan["product_id"],
                    "maturity": plan["maturity"],
                    "release_state": plan["release_state"],
                    "execution_scope": "plan_record_verify_review",
                },
            ),
            task_type="product_development",
            model_route="deterministic_product_planner",
            stop_condition="concept_recorded_and_independent_review_complete",
        )
        if job.status is JobStatus.READY:
            self.start_job(job.id, actor="orca")
        try:
            existing = self.business.get("product", plan["product_id"])
        except KeyError:
            existing = None
        source_revision = (
            int(existing["source_revision"]) + 1
            if existing and existing["source_system"] == "orca_product_development"
            else 1
        )
        encoded = json.dumps(
            plan, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        written = self.business.upsert(
            record_type="product", record_id=plan["product_id"],
            source_system="orca_product_development",
            source_revision=source_revision, status="draft",
            data={
                "name": plan["product_name"],
                "maturity": plan["maturity"],
                "release_state": plan["release_state"],
                "tracks": [track["id"] for track in plan["tracks"]],
                "phase": "discovery",
                "requirements_open": len(plan["requirements"]),
                "risks_open": len(plan["risks"]),
                "plan_sha256": sha256(encoded).hexdigest(),
            },
            provenance={
                "kind": "operator_requested_plan",
                "job_id": job.id,
                "generator": "deterministic_product_planner",
            },
            confidence=0.5,
            actor="orca",
            correlation_id=job.correlation_id,
        )
        self.evidence.append(
            correlation_id=job.correlation_id, actor="orca", lane="orca",
            kind="product.development.plan_created",
            payload={
                "job_id": job.id,
                "product_id": plan["product_id"],
                "record_hash": written.record["record_hash"],
                "plan_sha256": sha256(encoded).hexdigest(),
                "tracks": len(plan["tracks"]),
                "requirements": len(plan["requirements"]),
                "risks": len(plan["risks"]),
                "deliverables": len(plan["deliverables"]),
                "release_state": "not_released",
            },
        )
        self.policy.enforce_separation(
            author=AGENTS["orca"], reviewer=AGENTS["quench"],
            deployer=None, action=job.action)
        job.reviewer = "quench"
        job.status = JobStatus.REVIEW
        job.updated_at = utc_now()
        self.evidence.append(
            correlation_id=job.correlation_id, actor="orca", lane="orca",
            kind="job.review_requested",
            payload={"job_id": job.id, "reviewer": "quench"},
        )
        self._persist()
        return {
            "plan": plan,
            "job": self._job_dict(job),
            "record": written.record,
        }

    def _inventory_workflow_position(
            self, *, sku: str, location: str, allow_missing: bool) -> dict:
        record_id = f"{sku}:{location}"
        try:
            record = self.business.get("inventory_position", record_id)
        except KeyError:
            if not allow_missing:
                raise ValueError(
                    f"inventory position {record_id} is not recorded") from None
            return {
                "record_id": record_id, "record_hash": None, "version": 0,
                "data": {"sku": sku, "location": location,
                         "on_hand": 0.0, "reserved": 0.0, "available": 0.0},
            }
        data = record["data"]
        if data.get("sku") != sku or data.get("location") != location:
            raise ValueError("inventory canonical position identity is inconsistent")
        return {
            "record_id": record_id, "record_hash": record["record_hash"],
            "version": record["version"], "data": data,
        }

    @synchronized
    def propose_inventory_workflow(
            self, *, operation: dict, requested_by: str) -> dict:
        """Create an approval-gated canonical inventory change proposal."""

        self._assert_fresh()
        self._require_actor(
            requested_by, {"orca", "fry"}, "propose inventory workflows")
        operation = validate_inventory_operation(operation)
        kind = operation["operation_type"]
        source = self._inventory_workflow_position(
            sku=operation["sku"], location=operation["location"],
            allow_missing=kind == "receive")
        baselines = {operation["location"]: source}
        if kind == "transfer":
            target = self._inventory_workflow_position(
                sku=operation["sku"], location=operation["target_location"],
                allow_missing=True)
            baselines[operation["target_location"]] = target
        positions = {
            location: {
                "on_hand": item["data"]["on_hand"],
                "reserved": item["data"]["reserved"],
            }
            for location, item in baselines.items()
        }
        preview = calculate_inventory_changes(operation, positions)
        job = self.submit(
            title=f"Inventory {kind.replace('_', ' ')} · {operation['sku']}",
            lane="inventory", requested_by=requested_by, assigned_to="smith",
            action=Action(
                kind="commit", resource=f"inventory:{operation['sku']}",
                requested_level=PermissionLevel.R2,
                reversible=True,
                rollback="Create and approve a compensating inventory operation.",
                metadata={
                    "operation": operation,
                    "baselines": baselines,
                    "preview": preview,
                    "external_inventory_write": False,
                },
            ),
            task_type="inventory_workflow",
            model_route="deterministic_inventory_engine",
            stop_condition="canonical_positions_updated_and_quench_review_complete",
        )
        self.evidence.append(
            correlation_id=job.correlation_id, actor=requested_by, lane="inventory",
            kind="inventory.workflow.proposed",
            payload={
                "job_id": job.id, "operation_type": kind,
                "sku": operation["sku"], "locations": sorted(baselines),
                "quantity": operation["quantity"],
                "approval_id": job.approval_id,
                "external_inventory_write": False,
            },
        )
        self._persist()
        return {"job": self._job_dict(job), "operation": operation,
                "baselines": baselines, "preview": preview}

    @synchronized
    def execute_inventory_workflow(
            self, job_id: str, *, actor: str) -> dict:
        """Apply one approved proposal to the canonical ledger, then request review."""

        self._assert_fresh()
        if actor != "smith":
            raise PermissionError("only SMITH may execute an approved inventory workflow")
        job = self.jobs.get(job_id)
        if job is None or job.task_type != "inventory_workflow":
            raise ValueError("inventory workflow job is unknown")
        if job.status is not JobStatus.RUNNING:
            raise ValueError("inventory workflow must be approved and running")
        approval = self.approvals.get(job.approval_id)
        if approval is None or approval.status != "approved":
            raise PermissionError("inventory workflow requires Fry approval")
        metadata = job.action.metadata
        operation = validate_inventory_operation({
            key: value for key, value in metadata.get("operation", {}).items()
            if key != "schema"})
        baselines = metadata.get("baselines")
        if not isinstance(baselines, dict) or not baselines:
            raise ValueError("inventory workflow baseline is invalid")

        current: dict[str, dict] = {}
        for location, baseline in baselines.items():
            if not isinstance(baseline, dict):
                raise ValueError("inventory workflow baseline is invalid")
            try:
                record = self.business.get(
                    "inventory_position", baseline.get("record_id", ""))
            except KeyError:
                if baseline.get("record_hash") is not None:
                    raise ValueError("inventory position changed after proposal") from None
                record = None
            if record is not None and record["record_hash"] != baseline.get("record_hash"):
                raise ValueError("inventory position changed after proposal")
            if record is None:
                current[location] = {
                    "record_id": baseline["record_id"], "record": None,
                    "data": {"sku": operation["sku"], "location": location,
                             "on_hand": 0.0, "reserved": 0.0},
                }
            else:
                current[location] = {
                    "record_id": record["record_id"], "record": record,
                    "data": record["data"],
                }
        after = calculate_inventory_changes(operation, {
            location: {"on_hand": item["data"]["on_hand"],
                       "reserved": item["data"]["reserved"]}
            for location, item in current.items()
        })
        written = []
        for location, quantities in after.items():
            item = current[location]
            prior = item["record"]
            data = dict(item["data"])
            data.update({
                "sku": operation["sku"], "location": location,
                "on_hand": quantities["on_hand"],
                "reserved": quantities["reserved"],
                "available": quantities["available"],
            })
            result = self.business.upsert(
                record_type="inventory_position", record_id=item["record_id"],
                source_system="orca_inventory_workflow",
                source_revision=(prior["version"] + 1 if prior else 1),
                status="active", data=data,
                provenance={
                    "kind": "approved_inventory_workflow", "job_id": job.id,
                    "operation_type": operation["operation_type"],
                    "reason": operation["reason"], "evidence": operation["evidence"],
                    "approval_id": approval.id,
                },
                confidence=1.0, actor="smith", correlation_id=job.correlation_id,
            )
            written.append(result.record)
        self.evidence.append(
            correlation_id=job.correlation_id, actor="smith", lane="inventory",
            kind="inventory.workflow.applied",
            payload={
                "job_id": job.id, "operation_type": operation["operation_type"],
                "sku": operation["sku"],
                "record_hashes": [item["record_hash"] for item in written],
                "external_inventory_write": False,
            },
        )
        self.policy.enforce_separation(
            author=AGENTS["smith"], reviewer=AGENTS["quench"],
            deployer=None, action=job.action)
        job.reviewer = "quench"
        job.status = JobStatus.REVIEW
        job.updated_at = utc_now()
        self.evidence.append(
            correlation_id=job.correlation_id, actor="smith", lane="inventory",
            kind="job.review_requested",
            payload={"job_id": job.id, "reviewer": "quench"},
        )
        self._persist()
        return {"job": self._job_dict(job), "operation": operation,
                "records": written}

    @synchronized
    def run_approved_inventory_workflow(
            self, job_id: str, *, requested_by: str) -> dict:
        """Let Fry trigger ORCA execution after the separate approval decision."""

        self._assert_fresh()
        self._require_actor(
            requested_by, {"fry"}, "trigger approved inventory workflows")
        job = self.jobs.get(job_id)
        if job is None or job.task_type != "inventory_workflow":
            raise ValueError("inventory workflow job is unknown")
        approval = self.approvals.get(job.approval_id)
        if approval is None or approval.status != "approved":
            raise PermissionError("inventory workflow requires Fry approval")
        if job.status is not JobStatus.READY:
            raise ValueError("approved inventory workflow is not ready")
        self.start_job(job.id, actor="smith")
        result = self.execute_inventory_workflow(job.id, actor="smith")
        self.evidence.append(
            correlation_id=job.correlation_id, actor=requested_by, lane="inventory",
            kind="inventory.workflow.execution_triggered",
            payload={"job_id": job.id, "assigned_to": "smith"},
        )
        self._persist()
        return result

    def _inventory_count_inputs(self, observations: list[dict]) -> tuple[dict, dict]:
        baselines = {}
        positions = {}
        for observation in observations:
            sku = observation.get("sku") or observation.get("barcode")
            location = observation.get("location")
            if not isinstance(sku, str) or not isinstance(location, str):
                continue
            position = self._inventory_workflow_position(
                sku=sku, location=location, allow_missing=True)
            baselines[position["record_id"]] = position
            positions[position["record_id"]] = {
                "on_hand": position["data"]["on_hand"],
                "reserved": position["data"]["reserved"],
            }
        return baselines, positions

    @read_synchronized
    def preview_inventory_count_session(
            self, *, observations: list[dict], reason: str, evidence: str,
            requested_by: str) -> dict:
        self._assert_fresh()
        self._require_actor(
            requested_by, {"orca", "fry"}, "preview inventory counts")
        _, positions = self._inventory_count_inputs(observations)
        return build_count_reconciliation(
            observations, positions, reason=reason, evidence=evidence)

    @synchronized
    def propose_inventory_count_session(
            self, *, observations: list[dict], reason: str, evidence: str,
            requested_by: str) -> dict:
        self._assert_fresh()
        self._require_actor(
            requested_by, {"orca", "fry"}, "propose inventory counts")
        baselines, positions = self._inventory_count_inputs(observations)
        session = build_count_reconciliation(
            observations, positions, reason=reason, evidence=evidence)
        if session["release_state"] == "blocked":
            raise ValueError("inventory count session has unresolved reservation blockers")
        job = self.submit(
            title=f"Inventory count · {session['session_id']}",
            lane="inventory", requested_by=requested_by, assigned_to="smith",
            action=Action(
                kind="commit", resource=f"inventory-count:{session['session_id']}",
                requested_level=PermissionLevel.R2, reversible=True,
                rollback="Create and approve a compensating count or adjustment session.",
                metadata={
                    "count_session": session, "baselines": baselines,
                    "external_inventory_write": False,
                },
            ),
            task_type="inventory_count_session",
            model_route="deterministic_inventory_count_engine",
            stop_condition="count_reconciled_and_quench_review_complete",
        )
        self.evidence.append(
            correlation_id=job.correlation_id, actor=requested_by, lane="inventory",
            kind="inventory.count.proposed",
            payload={
                "job_id": job.id, "session_id": session["session_id"],
                "metrics": session["metrics"], "approval_id": job.approval_id,
                "external_inventory_write": False,
            },
        )
        self._persist()
        return {"job": self._job_dict(job), "session": session}

    @synchronized
    def execute_inventory_count_session(self, job_id: str, *, actor: str) -> dict:
        self._assert_fresh()
        if actor != "smith":
            raise PermissionError("only SMITH may execute an approved count session")
        job = self.jobs.get(job_id)
        if job is None or job.task_type != "inventory_count_session":
            raise ValueError("inventory count session job is unknown")
        if job.status is not JobStatus.RUNNING:
            raise ValueError("inventory count session must be approved and running")
        approval = self.approvals.get(job.approval_id)
        if approval is None or approval.status != "approved":
            raise PermissionError("inventory count session requires Fry approval")
        session = job.action.metadata.get("count_session")
        baselines = job.action.metadata.get("baselines")
        if not isinstance(session, dict) or not isinstance(baselines, dict):
            raise ValueError("inventory count session metadata is invalid")
        current_positions = {}
        current_records = {}
        for record_id, baseline in baselines.items():
            try:
                record = self.business.get("inventory_position", record_id)
            except KeyError:
                if baseline.get("record_hash") is not None:
                    raise ValueError("inventory position changed after count") from None
                record = None
            if record is not None and record["record_hash"] != baseline.get("record_hash"):
                raise ValueError("inventory position changed after count")
            current_records[record_id] = record
            current_positions[record_id] = (
                {"on_hand": record["data"]["on_hand"],
                 "reserved": record["data"]["reserved"]}
                if record else {"on_hand": 0.0, "reserved": 0.0})
        verified = build_count_reconciliation(
            [{key: row[key] for key in (
                "sku", "barcode", "location", "counted_quantity", "unit",
                "lot", "serial", "condition", "notes")}
             for row in session.get("rows", [])],
            current_positions, reason=session.get("reason", ""),
            evidence=session.get("evidence", ""))
        if verified["session_id"] != session.get("session_id"):
            raise ValueError("inventory count session changed after approval")
        if verified["release_state"] == "blocked":
            raise ValueError("inventory count session has unresolved reservation blockers")
        written = []
        for row in verified["rows"]:
            prior = current_records[row["record_id"]]
            data = dict(prior["data"]) if prior else {}
            data.update({
                "sku": row["sku"], "location": row["location"],
                "on_hand": row["counted_quantity"],
                "reserved": row["recorded_reserved"],
                "available": row["counted_quantity"] - row["recorded_reserved"],
                "unit": row["unit"], "barcode": row["barcode"],
                "lot": row["lot"], "serial": row["serial"],
                "condition": row["condition"], "count_notes": row["notes"],
            })
            result = self.business.upsert(
                record_type="inventory_position", record_id=row["record_id"],
                source_system="orca_inventory_count",
                source_revision=(prior["version"] + 1 if prior else 1),
                status="active", data=data,
                provenance={
                    "kind": "approved_inventory_count", "job_id": job.id,
                    "session_id": verified["session_id"],
                    "reason": verified["reason"], "evidence": verified["evidence"],
                    "approval_id": approval.id,
                },
                confidence=1.0, actor="smith", correlation_id=job.correlation_id,
            )
            written.append(result.record)
        self.evidence.append(
            correlation_id=job.correlation_id, actor="smith", lane="inventory",
            kind="inventory.count.applied",
            payload={
                "job_id": job.id, "session_id": verified["session_id"],
                "metrics": verified["metrics"],
                "record_hashes": [row["record_hash"] for row in written],
                "external_inventory_write": False,
            },
        )
        self.policy.enforce_separation(
            author=AGENTS["smith"], reviewer=AGENTS["quench"],
            deployer=None, action=job.action)
        job.reviewer = "quench"
        job.status = JobStatus.REVIEW
        job.updated_at = utc_now()
        self.evidence.append(
            correlation_id=job.correlation_id, actor="smith", lane="inventory",
            kind="job.review_requested",
            payload={"job_id": job.id, "reviewer": "quench"},
        )
        self._persist()
        return {"job": self._job_dict(job), "session": verified,
                "records": written}

    @synchronized
    def run_approved_inventory_count_session(
            self, job_id: str, *, requested_by: str) -> dict:
        self._assert_fresh()
        self._require_actor(
            requested_by, {"fry"}, "trigger approved inventory counts")
        job = self.jobs.get(job_id)
        if job is None or job.task_type != "inventory_count_session":
            raise ValueError("inventory count session job is unknown")
        approval = self.approvals.get(job.approval_id)
        if approval is None or approval.status != "approved":
            raise PermissionError("inventory count session requires Fry approval")
        if job.status is not JobStatus.READY:
            raise ValueError("approved inventory count session is not ready")
        self.start_job(job.id, actor="smith")
        result = self.execute_inventory_count_session(job.id, actor="smith")
        self.evidence.append(
            correlation_id=job.correlation_id, actor=requested_by, lane="inventory",
            kind="inventory.count.execution_triggered",
            payload={"job_id": job.id, "assigned_to": "smith"},
        )
        self._persist()
        return result

    @synchronized
    def set_bot_pause(self, bot_id: str, *, actor: str, paused: bool, reason: str) -> None:
        self._assert_fresh()
        self._require_actor(actor, {"orca", "fry"}, "change bot pause state")
        if type(paused) is not bool:
            raise ValueError("pause state must be a boolean")
        if bot_id not in self.bots.bots:
            raise ValueError(f"unknown bot: {bot_id}")
        if paused:
            self.bots.paused.add(bot_id)
            for job in self.jobs.values():
                if job.assigned_to == bot_id and job.status in {JobStatus.READY, JobStatus.RUNNING}:
                    job.status = JobStatus.PAUSED
                    job.updated_at = utc_now()
        else:
            self.bots.paused.discard(bot_id)
        self.evidence.append(
            correlation_id=new_id("corr"), actor=actor, lane="orca",
            kind="bot.paused" if paused else "bot.resumed",
            payload={"bot_id": bot_id, "reason": reason},
        )
        self._persist()

    @synchronized
    def set_node_pause(self, node_id: str, *, actor: str, paused: bool, reason: str) -> None:
        self._assert_fresh()
        self._require_actor(actor, {"orca", "fry"}, "change node pause state")
        if type(paused) is not bool:
            raise ValueError("pause state must be a boolean")
        if node_id not in NODES:
            raise ValueError(f"unknown fleet node: {node_id}")
        if paused:
            self.paused_nodes.add(node_id)
            for job in self.jobs.values():
                if (job.target_node == node_id
                        and job.status in {JobStatus.READY, JobStatus.RUNNING}):
                    job.status = JobStatus.PAUSED
                    job.updated_at = utc_now()
        else:
            if self.node_health[node_id]["state"] != "healthy":
                raise PermissionError(
                    "a node requires a fresh authenticated healthy heartbeat before resume")
            self.paused_nodes.discard(node_id)
        self.evidence.append(
            correlation_id=new_id("corr"), actor=actor, lane=NODES[node_id].lane,
            kind="node.paused" if paused else "node.resumed",
            payload={"node_id": node_id, "reason": reason},
        )
        self._persist()

    @synchronized
    def report_node_health(self, node_id: str, *, actor: str, state: str, detail: str = "") -> None:
        self._assert_fresh()
        self._require_actor(actor, {"orca", "fry"}, "report manual node health")
        if node_id not in NODES:
            raise ValueError(f"unknown fleet node: {node_id}")
        if state not in {"healthy", "degraded", "offline", "unproven"}:
            raise ValueError("invalid node health state")
        if state == "healthy":
            raise PermissionError("healthy state requires an authenticated heartbeat")
        if len(detail) > 4_000:
            raise ValueError("node health detail exceeds the size limit")
        verified = utc_now()
        self.node_health[node_id] = {
            "state": state, "last_verified": verified, "detail": redact_text(detail)}
        if state in {"degraded", "offline"}:
            self.paused_nodes.add(node_id)
            for job in self.jobs.values():
                if (job.target_node == node_id
                        and job.status in {JobStatus.READY, JobStatus.RUNNING}):
                    job.status = JobStatus.PAUSED
                    job.updated_at = utc_now()
        self.evidence.append(
            correlation_id=new_id("corr"), actor=actor, lane=NODES[node_id].lane,
            kind="node.health_reported",
            payload={"node_id": node_id, "state": state, "detail": detail},
        )
        self._persist()

    @synchronized
    def enroll_node(self, node_id: str, *, actor: str, key: bytes) -> dict:
        self._assert_fresh()
        if actor != "fry":
            raise PermissionError("only Fry may enroll a fleet node")
        if node_id not in NODES:
            raise ValueError(f"unknown fleet node: {node_id}")
        previous = self.node_enrollments.get(node_id)
        previous_fingerprint = (
            previous.get("key_fingerprint") if previous is not None else None)
        record = self.fleet_auth.enroll(node_id, key)
        rotated = (
            previous_fingerprint is not None
            and previous_fingerprint != record["key_fingerprint"]
        )
        if rotated:
            self.node_health[node_id] = {
                "state": "unproven",
                "last_verified": None,
                "detail": "enrollment key rotated; awaiting authenticated heartbeat",
            }
            self.paused_nodes.add(node_id)
            for job in self.jobs.values():
                if (job.target_node == node_id
                        and job.status in {JobStatus.READY, JobStatus.RUNNING}):
                    job.status = JobStatus.PAUSED
                    job.updated_at = utc_now()
        self.evidence.append(
            correlation_id=new_id("corr"), actor=actor, lane=NODES[node_id].lane,
            kind="node.key_rotated" if rotated else "node.enrolled",
            payload={"node_id": node_id, "key_fingerprint": record["key_fingerprint"],
                     "prior_key_invalidated": rotated},
        )
        self._persist()
        return dict(record)

    @synchronized
    def accept_heartbeat(self, heartbeat: Heartbeat, *, signature: str, key: bytes,
                         now: int | None = None) -> None:
        self._assert_fresh()
        if heartbeat.node_id not in NODES:
            raise ValueError(f"unknown fleet node: {heartbeat.node_id}")
        if heartbeat.state not in {"healthy", "degraded", "offline"}:
            raise ValueError("authenticated heartbeat has invalid state")
        if len(heartbeat.detail) > 4_000:
            raise ValueError("heartbeat detail exceeds the size limit")
        accepted_at = self.fleet_auth.verify(heartbeat, signature, key, now=now)
        self.node_health[heartbeat.node_id] = {
            "state": heartbeat.state,
            "last_verified": datetime.fromtimestamp(
                accepted_at, timezone.utc).isoformat(),
            "detail": redact_text(heartbeat.detail),
        }
        if heartbeat.state in {"degraded", "offline"}:
            self.paused_nodes.add(heartbeat.node_id)
            for job in self.jobs.values():
                if (job.target_node == heartbeat.node_id
                        and job.status in {JobStatus.READY, JobStatus.RUNNING}):
                    job.status = JobStatus.PAUSED
                    job.updated_at = utc_now()
        self.evidence.append(
            correlation_id=new_id("corr"), actor=heartbeat.node_id,
            lane=NODES[heartbeat.node_id].lane, kind="node.heartbeat_verified",
            payload={"node_id": heartbeat.node_id, "state": heartbeat.state,
                     "nonce": heartbeat.nonce, "detail": heartbeat.detail},
        )
        self._persist()

    @synchronized
    def expire_stale_nodes(self, *, now: int, degraded_after: int = 180,
                           offline_after: int = 600) -> list[str]:
        self._assert_fresh()
        if (type(now) is not int or now < 0
                or type(degraded_after) is not int
                or type(offline_after) is not int
                or degraded_after <= 0 or offline_after <= degraded_after):
            raise ValueError("staleness thresholds must be positive and ordered")
        changed: list[str] = []
        for node_id, enrollment in self.node_enrollments.items():
            last_seen = enrollment.get("last_seen_epoch")
            if last_seen is None:
                target = "unproven"
            else:
                if type(last_seen) is not int or last_seen < 0:
                    raise RuntimeError("fleet enrollment contains an invalid acceptance time")
                age = now - last_seen
                if age < 0:
                    raise ValueError("staleness time precedes the last accepted heartbeat")
                target = "offline" if age >= offline_after else "degraded" if age >= degraded_after else None
            current_state = self.node_health[node_id]["state"]
            should_decay = (
                (target == "degraded" and current_state == "healthy")
                or (target == "offline" and current_state in {"healthy", "degraded"})
            )
            if should_decay:
                self.node_health[node_id] = {
                    "state": target, "last_verified": self.node_health[node_id]["last_verified"],
                    "detail": "authenticated heartbeat stale" if target != "unproven" else "awaiting first heartbeat",
                }
                self.paused_nodes.add(node_id)
                for job in self.jobs.values():
                    if (job.target_node == node_id
                            and job.status in {JobStatus.READY, JobStatus.RUNNING}):
                        job.status = JobStatus.PAUSED
                        job.updated_at = utc_now()
                changed.append(node_id)
                self.evidence.append(
                    correlation_id=new_id("corr"), actor="orca", lane=NODES[node_id].lane,
                    kind="node.contact_lost",
                    payload={"node_id": node_id, "state": target},
                )
        if changed:
            self._persist()
        return changed

    @synchronized
    def prepare_connector_read(self, *, actor: str, connector: str,
                               operation: str, resource: str) -> dict:
        self._assert_fresh()
        if actor not in AGENTS:
            raise ValueError("connector request requires a registered identity")
        if actor == "security_gate":
            raise PermissionError("the security gate has no connector authority")
        request = self.connector_gateway.prepare(
            connector=connector, operation=operation, resource=resource)
        self.evidence.append(
            correlation_id=new_id("corr"), actor=actor, lane="orca",
            kind="connector.read_prepared",
            payload={"request_id": request.id, "connector": connector,
                     "operation": operation, "resource": resource},
        )
        self._persist()
        return asdict(request)

    @synchronized
    def record_advisory_read_completion(
            self, *, correlation_id: str, results: list[dict]) -> None:
        """Checkpoint the evidence-only completion of the advisory read workflow."""
        self._assert_fresh()
        if not isinstance(correlation_id, str) or not correlation_id.strip():
            raise ValueError("advisory workflow requires a correlation id")
        if not isinstance(results, list) or not all(isinstance(row, dict) for row in results):
            raise ValueError("advisory workflow results must be a list of records")
        self.evidence.append(
            correlation_id=correlation_id, actor="orca", lane="orca",
            kind="workflow.advisory_read_completed",
            payload={"connectors": [row.get("connector") for row in results],
                     "write_count": 0, "results": results},
        )
        self._persist()

    @synchronized
    def set_lane_pause(self, lane: str, *, actor: str, paused: bool, reason: str) -> None:
        self._assert_fresh()
        self._require_actor(actor, {"orca", "fry"}, "change lane pause state")
        if type(paused) is not bool:
            raise ValueError("pause state must be a boolean")
        if lane not in LANES:
            raise ValueError(f"unknown project lane: {lane}")
        if paused:
            self.paused_lanes.add(lane)
            for job in self.jobs.values():
                if (job.lane == lane
                        and job.status in {JobStatus.READY, JobStatus.RUNNING}):
                    job.status = JobStatus.PAUSED
                    job.updated_at = utc_now()
        else:
            self.paused_lanes.discard(lane)
        self.evidence.append(
            correlation_id=new_id("corr"), actor=actor, lane=lane,
            kind="lane.paused" if paused else "lane.resumed",
            payload={"lane": lane, "reason": reason},
        )
        self._persist()

    @synchronized
    def set_emergency_stop(self, *, actor: str, active: bool, reason: str) -> None:
        self._assert_fresh()
        if actor != "fry":
            raise PermissionError("only Fry may change the global emergency stop")
        if type(active) is not bool:
            raise ValueError("emergency-stop state must be a boolean")
        self.emergency_stop = active
        if active:
            for job in self.jobs.values():
                if job.status in {JobStatus.READY, JobStatus.RUNNING}:
                    job.status = JobStatus.PAUSED
                    job.updated_at = utc_now()
        self.evidence.append(
            correlation_id=new_id("corr"), actor=actor, lane="orca",
            kind="control.emergency_stop" if active else "control.emergency_resumed",
            payload={"active": active, "reason": reason},
        )
        self._persist()

    @synchronized
    def open_incident(self, *, severity: str, title: str, lane: str,
                      owner: str, detail: str = "", actor: str = "orca") -> Incident:
        self._assert_fresh()
        self._require_actor(actor, {"orca", "fry"}, "open incidents")
        if severity not in {"S0", "S1", "S2", "S3"}:
            raise ValueError("incident severity must be S0-S3")
        if lane not in LANES or owner not in AGENTS:
            raise ValueError("incident requires a registered lane and owner")
        if not title.strip() or len(title) > 500 or len(detail) > 4_000:
            raise ValueError("incident text exceeds the size limit or is empty")
        safe_title = redact_text(title).strip()
        fingerprint = sha256(f"{lane}|{safe_title.lower()}".encode()).hexdigest()
        for existing in self.incidents.values():
            existing_fingerprint = sha256(
                f"{existing.lane}|{existing.title.strip().lower()}".encode()).hexdigest()
            if existing_fingerprint == fingerprint and existing.status is not IncidentStatus.CLOSED:
                self.evidence.append(
                    correlation_id=existing.correlation_id, actor=actor, lane=lane,
                    kind="incident.deduplicated",
                    payload={"incident_id": existing.id, "fingerprint": fingerprint},
                )
                self._persist()
                return existing
        incident = Incident(severity, safe_title, lane, owner, new_id("corr"),
                            detail=redact_text(detail))
        self.incidents[incident.id] = incident
        self.evidence.append(
            correlation_id=incident.correlation_id, actor=actor, lane=lane,
            kind="incident.opened", payload={"incident_id": incident.id,
            "severity": severity, "title": incident.title, "owner": owner},
        )
        if severity in {"S2", "S3"}:
            alert_id = new_id("alert")
            self.notifications.enqueue(
                alert_id=alert_id,
                idempotency_key=incident.id,
                payload={
                    "incident_id": incident.id,
                    "connector": "slack",
                    "severity": severity,
                    "title": incident.title,
                    "lane": incident.lane,
                    "status": incident.status.value,
                },
                now=time.time(),
            )
        self._persist()
        return incident

    @synchronized
    def _claim_notification_batch(
        self,
        *,
        actor: str,
        now: float,
        claim_id: str,
        max_batch: int,
        lease_seconds: float,
    ) -> NotificationClaimBatch:
        self._assert_fresh()
        self._require_actor(actor, {"orca", "fry"}, "process notifications")
        batch = self.notifications.claim_due(
            now=now,
            claim_id=claim_id,
            limit=max_batch,
            lease_seconds=lease_seconds,
        )
        for alert in batch.expired:
            self.evidence.append(
                correlation_id=str(alert.payload.get("incident_id", alert.id)),
                actor=actor,
                lane=str(alert.payload.get("lane", "orca")),
                kind="notification.delivery_unconfirmed",
                payload={
                    "alert_id": alert.id,
                    "attempts": alert.attempts,
                    "last_error": alert.last_error,
                    "status": alert.status.value,
                },
            )
        for alert in batch.claimed:
            self.evidence.append(
                correlation_id=str(alert.payload.get("incident_id", alert.id)),
                actor=actor,
                lane=str(alert.payload.get("lane", "orca")),
                kind="notification.delivery_reserved",
                payload={
                    "alert_id": alert.id,
                    "attempts": alert.attempts,
                    "claim_started_at": alert.claim_started_at,
                    "claim_until": alert.claim_until,
                    "status": alert.status.value,
                },
            )
        if batch.claimed or batch.expired:
            self._persist()
        return batch

    @synchronized
    def _finish_notification_claim(
        self,
        *,
        actor: str,
        now: float,
        claim_id: str,
        alert_id: str,
        outcome: DeliveryOutcome,
    ) -> Alert:
        self._assert_fresh()
        self._require_actor(actor, {"orca", "fry"}, "process notifications")
        alert = self.notifications.finish_claim(
            alert_id,
            claim_id=claim_id,
            outcome=outcome,
            now=now,
        )
        self.evidence.append(
            correlation_id=str(alert.payload.get("incident_id", alert.id)),
            actor=actor,
            lane=str(alert.payload.get("lane", "orca")),
            kind="notification.delivery_attempted",
            payload={
                "alert_id": alert.id,
                "attempts": alert.attempts,
                "last_error": alert.last_error,
                "status": alert.status.value,
            },
        )
        self._persist()
        return alert

    def process_notifications(
        self,
        *,
        actor: str,
        now: float,
        transport: Callable[..., object],
        max_batch: int = NotificationOutbox.DEFAULT_BATCH_SIZE,
        lease_seconds: float = NotificationOutbox.DEFAULT_LEASE_SECONDS,
        clock: Callable[[], float] | None = None,
    ) -> list[dict]:
        """Deliver bounded notifications using one durable reservation at a time.

        ORCA provides no built-in network transport. Providers must honor the
        supplied hashed idempotency key because a crash after provider receipt
        but before the local commit creates an explicitly unconfirmed attempt.
        Transport calls happen outside the control-plane and SQLite locks, so a
        slow provider cannot block unrelated reads or mutations.
        """

        if not callable(transport):
            raise TypeError("transport must be callable")
        if type(max_batch) is not int or not 1 <= max_batch <= NotificationOutbox.MAX_BATCH_SIZE:
            raise ValueError("notification batch limit is invalid")
        finish_clock = time.time if clock is None else clock
        if not callable(finish_clock):
            raise TypeError("notification clock must be callable")

        claim_time = now
        completed: list[dict] = []
        for _ in range(max_batch):
            claim_id = new_id("notification_claim")
            batch = self._claim_notification_batch(
                actor=actor,
                now=claim_time,
                claim_id=claim_id,
                max_batch=1,
                lease_seconds=lease_seconds,
            )
            completed.extend(alert.to_dict() for alert in batch.expired)
            if not batch.claimed:
                if not batch.expired:
                    break
                continue
            alert = batch.claimed[0]
            outcome = self.notifications.delivery_outcome(
                alert, transport=transport)
            finish_time = finish_clock()
            try:
                finalized = self._finish_notification_claim(
                    actor=actor,
                    now=finish_time,
                    claim_id=claim_id,
                    alert_id=alert.id,
                    outcome=outcome,
                )
            except NotificationConflict:
                current = self.notifications.get(alert.id)
                completed.append({
                    "id": alert.id,
                    "status": current.status.value,
                    "attempts": current.attempts,
                    "last_error": current.last_error,
                    "delivery_result": "lease_lost",
                })
            else:
                completed.append(finalized.to_dict())
            claim_time = finish_time
        return completed

    @synchronized
    def run_security_gate(self, *, author: str, lane: str,
                          artifacts: dict[str, str],
                          requested_by: str) -> dict:
        self._assert_fresh()
        self._require_actor(
            requested_by, {"security_gate", "orca", "fry"},
            "run the security gate",
        )
        report = IndependentSecurityGate().scan(
            author=author, lane=lane, artifacts=artifacts).snapshot()
        report["id"] = new_id("security")
        report["correlation_id"] = new_id("corr")
        report["created_at"] = utc_now()
        report["requested_by"] = requested_by
        self.security_reports.append(report)
        self.evidence.append(
            correlation_id=report["correlation_id"], actor=requested_by, lane=lane,
            kind="security.reported", payload={"report": report},
        )
        self._persist()
        return report

    def _security_finding(self, report_id: str, fingerprint: str) -> tuple[dict, dict]:
        try:
            report = next(row for row in self.security_reports if row["id"] == report_id)
        except StopIteration as exc:
            raise KeyError(f"unknown security report: {report_id}") from exc
        try:
            finding = next(row for row in report["findings"] if row["fingerprint"] == fingerprint)
        except StopIteration as exc:
            raise KeyError(f"unknown security finding: {fingerprint}") from exc
        return report, finding

    @synchronized
    def review_security_finding(self, *, report_id: str, fingerprint: str,
                                actor: str, verdict: str, note: str) -> dict:
        self._assert_fresh()
        self._require_actor(actor, {"quench", "fry"}, "review a security finding")
        report, finding = self._security_finding(report_id, fingerprint)
        if actor == report["author"]:
            raise PermissionError("a security finding requires an independent reviewer")
        if verdict not in {"confirmed", "false_positive"}:
            raise ValueError("security verdict must be confirmed or false_positive")
        if not note.strip():
            raise ValueError("security review requires an evidence note")
        if len(note) > 4_000:
            raise ValueError("security review note exceeds the size limit")
        adjudication = {
            "id": new_id("security_review"), "report_id": report_id,
            "fingerprint": fingerprint, "severity": finding["severity"],
            "actor": actor, "verdict": verdict, "note": redact_text(note),
            "created_at": utc_now(),
        }
        self.security_adjudications.append(adjudication)
        self.evidence.append(
            correlation_id=report["correlation_id"], actor=actor, lane=report["lane"],
            kind="security.finding_reviewed", payload={"adjudication": adjudication},
        )
        self._persist()
        return adjudication

    @synchronized
    def record_security_exception(self, *, report_id: str, fingerprint: str,
                                  actor: str, reason: str,
                                  duration_minutes: int) -> dict:
        self._assert_fresh()
        self._require_actor(actor, {"fry"}, "record a security break-glass exception")
        report, finding = self._security_finding(report_id, fingerprint)
        if finding["severity"] == "S3":
            raise PermissionError("S3 findings cannot receive a break-glass exception")
        limit = 60 if finding["severity"] == "S2" else 1440
        if duration_minutes <= 0 or duration_minutes > limit:
            raise ValueError(f"security exception duration must be 1-{limit} minutes")
        if not reason.strip():
            raise ValueError("security exception requires a reason")
        if len(reason) > 4_000:
            raise ValueError("security exception reason exceeds the size limit")
        reviews = [row for row in self.security_adjudications
                   if row["report_id"] == report_id and row["fingerprint"] == fingerprint]
        if not reviews or reviews[-1]["actor"] != "quench" or reviews[-1]["verdict"] != "confirmed":
            raise PermissionError("break-glass requires a current confirmed QUENCH review")
        created = datetime.now(timezone.utc)
        exception = {
            "id": new_id("security_exception"), "report_id": report_id,
            "fingerprint": fingerprint, "severity": finding["severity"],
            "actor": actor, "reason": redact_text(reason),
            "created_at": created.isoformat(),
            "expires_at": (created + timedelta(minutes=duration_minutes)).isoformat(),
            "authority": "fry_r3", "record_only": True,
            "enforcement_effect": False,
        }
        self.security_exceptions.append(exception)
        self.evidence.append(
            correlation_id=report["correlation_id"], actor=actor, lane=report["lane"],
            kind="security.exception_recorded", payload={"exception": exception},
        )
        self._persist()
        return exception

    @synchronized
    def run_retention_audit(self, *, actor: str, now: str | None = None) -> dict:
        self._assert_fresh()
        self._require_actor(actor, {"orca", "quench", "fry"}, "run a retention audit")
        evaluated_at = now or utc_now()
        records = [
            RetentionRecord("evidence", event["id"], event["timestamp"])
            for event in self.evidence.list(limit=100_000)
        ]
        records.extend(
            RetentionRecord("incidents", incident.id, incident.created_at)
            for incident in self.incidents.values())
        records.extend(
            RetentionRecord("jobs-and-approvals", job.id, job.created_at)
            for job in self.jobs.values())
        records.extend(
            RetentionRecord("cost-records", row["id"], row["timestamp"])
            for row in self.costs.retention_records())
        report = RetentionGuard().audit(records, now=evaluated_at)
        report.update({
            "id": new_id("retention"), "actor": actor,
            "created_at": utc_now(), "evaluated_at": evaluated_at,
        })
        self.retention_audits.append(report)
        self.evidence.append(
            correlation_id=new_id("corr"), actor=actor, lane="orca",
            kind="retention.audit_completed",
            payload={key: value for key, value in report.items() if key != "assessments"},
        )
        self._persist()
        return report

    @synchronized
    def update_incident(self, incident_id: str, *, actor: str,
                        status: str, detail: str = "") -> Incident:
        self._assert_fresh()
        if actor not in AGENTS:
            raise ValueError("incident updates require a registered identity")
        incident = self.incidents[incident_id]
        target = IncidentStatus(status)
        allowed = {
            IncidentStatus.OPEN: {IncidentStatus.CONTAINED},
            IncidentStatus.CONTAINED: {IncidentStatus.CLOSED},
            IncidentStatus.CLOSED: set(),
        }
        if target not in allowed[incident.status]:
            raise ValueError("invalid incident status transition")
        if target is IncidentStatus.CLOSED and actor not in {"fry", "quench"}:
            raise PermissionError("only Fry or QUENCH may close an incident")
        if target is IncidentStatus.CLOSED and actor == incident.owner:
            raise PermissionError("incident closure requires an identity other than the owner")
        incident.status = target
        incident.detail = redact_text(detail or incident.detail)
        incident.updated_at = utc_now()
        self.evidence.append(
            correlation_id=incident.correlation_id, actor=actor, lane=incident.lane,
            kind=f"incident.{target.value}",
            payload={"incident_id": incident.id, "detail": incident.detail},
        )
        self._persist()
        return incident

    @synchronized
    def decide(self, approval_id: str, *, actor: str, approve: bool, note: str = "") -> Job:
        self._assert_fresh()
        if type(approve) is not bool:
            raise ValueError("approval decision must be a boolean")
        approval = self.approvals[approval_id]
        if actor != "fry":
            raise PermissionError("only Fry may decide R2/R3 approvals")
        job = self.jobs[approval.job_id]
        if actor == job.assigned_to:
            raise PermissionError("the assigned worker cannot approve its own job")
        if approval.status != "pending":
            raise ValueError("approval already decided")
        if len(note) > 4_000:
            raise ValueError("approval note exceeds the size limit")
        approval.status = "approved" if approve else "denied"
        approval.decided_by = actor
        approval.note = redact_text(note)[:4_000]
        blocked = (self.emergency_stop or job.lane in self.paused_lanes or
                   job.target_node in self.paused_nodes or job.assigned_to in self.bots.paused)
        job.status = JobStatus.PAUSED if approve and blocked else JobStatus.READY if approve else JobStatus.DENIED
        job.updated_at = utc_now()
        self.evidence.append(
            correlation_id=job.correlation_id, actor=actor, lane=job.lane,
            kind=f"approval.{approval.status}",
            payload={"job_id": job.id, "approval_id": approval.id, "note": note},
        )
        self._persist()
        return job

    @synchronized
    def start_job(self, job_id: str, *, actor: str) -> Job:
        self._assert_fresh()
        job = self.jobs[job_id]
        if actor == "security_gate":
            raise PermissionError("the security gate cannot author or execute jobs")
        if actor != job.assigned_to:
            raise PermissionError("only the assigned bot may start the job")
        if job.status is not JobStatus.READY:
            raise ValueError("job is not ready to start")
        if (self.emergency_stop or actor in self.bots.paused or
                job.lane in self.paused_lanes or job.target_node in self.paused_nodes
                or (job.target_node is not None
                    and self.node_health[job.target_node]["state"] != "healthy")):
            raise PermissionError("job execution is paused by a control boundary")
        job.status = JobStatus.RUNNING
        job.updated_at = utc_now()
        self.evidence.append(
            correlation_id=job.correlation_id, actor=actor, lane=job.lane,
            kind="job.started", payload={"job_id": job.id},
        )
        self._persist()
        return job

    @synchronized
    def submit_job_review(self, job_id: str, *, actor: str, reviewer: str = "quench") -> Job:
        self._assert_fresh()
        job = self.jobs[job_id]
        if actor != job.assigned_to or job.status is not JobStatus.RUNNING:
            raise PermissionError("only the running job author may submit review")
        if reviewer not in AGENTS or not AGENTS[reviewer].may_review:
            raise ValueError("reviewer must be a registered review identity")
        if job.approval_id:
            approver = self.approvals[job.approval_id].decided_by
            if approver and reviewer == approver:
                raise PolicyViolation("approval and independent review require different identities")
        self.policy.enforce_separation(author=AGENTS[actor], reviewer=AGENTS[reviewer],
                                       deployer=None, action=job.action)
        job.reviewer = reviewer
        job.status = JobStatus.REVIEW
        job.updated_at = utc_now()
        self.evidence.append(
            correlation_id=job.correlation_id, actor=actor, lane=job.lane,
            kind="job.review_requested", payload={"job_id": job.id, "reviewer": reviewer},
        )
        self._persist()
        return job

    @synchronized
    def complete_job(self, job_id: str, *, actor: str, note: str) -> Job:
        self._assert_fresh()
        job = self.jobs[job_id]
        if job.status is not JobStatus.REVIEW or actor != job.reviewer:
            raise PermissionError("only the assigned independent reviewer may complete the job")
        self.policy.enforce_separation(
            author=AGENTS[job.assigned_to], reviewer=AGENTS[actor], deployer=None,
            action=job.action)
        if job.approval_id and actor == self.approvals[job.approval_id].decided_by:
            raise PolicyViolation("approval and independent review require different identities")
        if not note.strip():
            raise ValueError("review completion requires an evidence note")
        job.status = JobStatus.COMPLETE
        job.updated_at = utc_now()
        self.evidence.append(
            correlation_id=job.correlation_id, actor=actor, lane=job.lane,
            kind="job.completed", payload={"job_id": job.id, "note": note},
        )
        self._persist()
        return job

    @synchronized
    def pause(self, job_id: str, *, actor: str, reason: str) -> Job:
        self._assert_fresh()
        job = self.jobs[job_id]
        allowed = {"orca", "fry", job.assigned_to}
        if job.reviewer:
            allowed.add(job.reviewer)
        self._require_actor(actor, allowed, "pause this job")
        if job.status in {JobStatus.COMPLETE, JobStatus.FAILED, JobStatus.DENIED}:
            raise ValueError("terminal jobs cannot be paused or reopened")
        job.status = JobStatus.PAUSED
        job.updated_at = utc_now()
        self.evidence.append(correlation_id=job.correlation_id, actor=actor,
                             lane=job.lane, kind="job.paused",
                             payload={"job_id": job.id, "reason": reason})
        self._persist()
        return job

    @synchronized
    def resume(self, job_id: str, *, actor: str, reason: str) -> Job:
        self._assert_fresh()
        self._require_actor(actor, {"orca", "fry"}, "resume a job")
        job = self.jobs[job_id]
        if job.status is not JobStatus.PAUSED:
            raise ValueError("only paused jobs can be resumed")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 4000:
            raise ValueError("resume requires a concise, non-empty reason")
        if (self.emergency_stop or job.assigned_to in self.bots.paused
                or job.lane in self.paused_lanes or job.target_node in self.paused_nodes
                or (job.target_node is not None
                    and self.node_health[job.target_node]["state"] != "healthy")):
            raise PermissionError("job remains paused by a control boundary")
        if job.level >= PermissionLevel.R2 and not job.approval_id:
            decision = self.policy.classify(job.action)
            approval = Approval(job.id, job.level, rationale=decision.rationale)
            self.approvals[approval.id] = approval
            job.approval_id = approval.id
        approval = self.approvals.get(job.approval_id)
        if approval and approval.status == "denied":
            raise PermissionError("a denied approval cannot be resumed")
        if approval and approval.status != "approved":
            job.status = JobStatus.WAITING_APPROVAL
        else:
            job.status = JobStatus.REVIEW if job.reviewer else JobStatus.READY
        job.updated_at = utc_now()
        self.evidence.append(
            correlation_id=job.correlation_id, actor=actor, lane=job.lane,
            kind="job.resumed", payload={"job_id": job.id, "status": job.status.value,
                                         "reason": reason})
        self._persist()
        return job

    @read_synchronized
    def snapshot(self) -> dict:
        self._assert_fresh()
        ai_stack = ladder_snapshot(self.node_health)
        enabled_services = {
            service_id for service_id, service in ai_stack["services"].items()
            if service["runtime_enabled"]
        }
        runtime_services_by_bot = {
            "orca": {"kiln_codex", "forge_qwen"},
            "smith": {"kiln_codex", "forge_qwen"},
            "quench": {"kiln_quench"},
            "security_gate": {"kiln_quench"},
        }
        bots = self.bots.snapshot()
        for bot in bots:
            bot["runtime_enabled"] = bool(
                runtime_services_by_bot.get(bot["id"], set()) & enabled_services
            )
        return {
            "agents": [asdict(x) for x in AGENTS.values()],
            "role_catalog": role_snapshot(),
            "bots": bots,
            "migration_candidates": MIGRATION_CANDIDATES,
            "bot_build_queue": BOT_BUILD_QUEUE,
            "prompt_contracts": {key: asdict(value) for key, value in PROMPT_CONTRACTS.items()},
            "tool_manifests": {key: sorted(value) for key, value in BOT_TOOL_MANIFESTS.items()},
            "tool_catalog": {
                name: {
                    "family": capability.family,
                    "description": capability.description,
                    "connector": capability.connector,
                    "level": capability.level.name,
                    "mutates": capability.mutates,
                }
                for name, capability in TOOL_CATALOG.items()
            },
            "connectors": [asdict(x) for x in CONNECTORS.values()],
            "connector_capabilities": self.connector_gateway.snapshot(),
            "nodes": [self._node_dict(node_id) for node_id in NODES],
            "placement": placement_snapshot(self.node_health),
            "ai_stack": ai_stack,
            "jobs": [self._job_dict(x) for x in self.jobs.values()],
            "approvals": [asdict(x) for x in self.approvals.values()],
            "incidents": [{**asdict(x), "status": x.status.value} for x in self.incidents.values()],
            "security_reports": list(self.security_reports),
            "security_adjudications": list(self.security_adjudications),
            "security_exceptions": list(self.security_exceptions),
            "retention_audits": list(self.retention_audits),
            "alert_outbox": self.alert_outbox,
            "notification_outbox": self.notifications.to_dict(),
            "paused_lanes": sorted(self.paused_lanes),
            "paused_nodes": sorted(self.paused_nodes),
            "node_enrollments": {node_id: dict(record) for node_id, record in self.node_enrollments.items()},
            "emergency_stop": self.emergency_stop,
            "state_revision": self.state_revision,
            "evidence_chain_valid": True,
            "schema_version": self.evidence.schema_version,
            "idempotency_receipt_count": self.idempotency.count(),
            "business": self.business.snapshot(event_limit=25),
            "costs": self.costs.summary(),
            "governance": governance_snapshot(),
        }

    @property
    def alert_outbox(self) -> list[dict]:
        """Compatibility projection of the canonical notification outbox."""

        return [
            {
                "id": alert.id,
                "incident_id": alert.payload.get("incident_id"),
                "connector": alert.payload.get("connector", "slack"),
                "status": alert.status.value,
                "severity": alert.payload.get("severity"),
                "created_at": alert.created_at,
            }
            for alert in self.notifications.alerts()
        ]

    def _node_dict(self, node_id: str) -> dict:
        data = asdict(NODES[node_id])
        data.update(self.node_health[node_id])
        data["paused"] = node_id in self.paused_nodes
        from .telemetry import decode_detail
        reading = decode_detail(data.get("detail"))
        data["telemetry"] = reading['metrics'] if reading else None
        if reading:
            data['detail'] = reading.get('summary', '')
        return data

    @staticmethod
    def _job_dict(job: Job) -> dict:
        data = asdict(job)
        data["level"] = job.level.name
        data["status"] = job.status.value
        return data
