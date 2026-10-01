"""Solo-operator control rooms and deterministic Action Center planning."""

from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Any

from .security import redact_text


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$")
_PRIORITY = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
_KINDS = frozenset({
    "approval", "deadline", "exception", "follow_up", "blocked_work",
    "security", "finance", "inventory", "customer", "vendor", "system",
})

SOLO_OPERATOR_MODULES = (
    {
        "id": "action_center", "name": "Action Center",
        "purpose": "One deduplicated, prioritized queue for approvals, deadlines, exceptions, follow-ups and blocked work.",
        "owners": ["orca", "daily_briefing_officer", "evidence_auditor"],
        "state": "implemented_candidate", "mode": "proposal_only",
    },
    {
        "id": "relationship_master", "name": "Customer & Vendor Master",
        "purpose": "Canonical identities, relationships, orders, invoices, contracts, cases, consent and suppression.",
        "owners": ["connector_steward", "channel_operator"],
        "state": "staged", "mode": "awaiting_canonical_data_source",
    },
    {
        "id": "knowledge_center", "name": "Knowledge Center",
        "purpose": "Approved product facts, policies, prices, manuals, compatibility data and response templates.",
        "owners": ["orca", "evidence_auditor", "legal_compliance_clerk"],
        "state": "staged", "mode": "awaiting_approved_sources",
    },
    {
        "id": "case_manager", "name": "Ticket & Case Manager",
        "purpose": "Owned, deadline-bound customer, supplier, quality, legal, return and incident cases.",
        "owners": ["orca", "daily_briefing_officer"],
        "state": "staged", "mode": "awaiting_case_store",
    },
    {
        "id": "attachment_quarantine", "name": "Attachment Quarantine",
        "purpose": "Isolate and scan untrusted links and files before downstream document or business use.",
        "owners": ["security_watch", "evidence_auditor"],
        "state": "staged", "mode": "links_and_files_blocked",
    },
    {
        "id": "commitment_manager", "name": "Calendar & Commitment Manager",
        "purpose": "Callbacks, renewals, filings, bills, launches, maintenance and promised follow-ups.",
        "owners": ["orca", "daily_briefing_officer"],
        "state": "candidate", "mode": "calendar_candidates_only",
    },
    {
        "id": "identity_consent", "name": "Identity & Consent Gate",
        "purpose": "Verify correspondents and enforce consent, suppression, privacy and authorization rules globally.",
        "owners": ["legal_compliance_clerk", "security_watch"],
        "state": "staged", "mode": "deny_external_contact_until_accepted",
    },
    {
        "id": "dead_letter", "name": "Dead-Letter & Recovery Queue",
        "purpose": "Preserve failed messages, syncs, orders, jobs and automations for safe replay and review.",
        "owners": ["recovery_marshal", "connector_steward"],
        "state": "staged", "mode": "no_automatic_replay",
    },
    {
        "id": "business_memory", "name": "Business Memory Graph",
        "purpose": "Connect people, companies, products, projects, orders, documents, conversations and decisions.",
        "owners": ["orca", "continuity_keeper"],
        "state": "staged", "mode": "awaiting_entity_resolution",
    },
    {
        "id": "decision_journal", "name": "Decision Journal",
        "purpose": "Record recommendations, approvals, rationale, evidence, outcomes and later review.",
        "owners": ["continuity_keeper", "evidence_auditor"],
        "state": "candidate", "mode": "append_only_proposal",
    },
    {
        "id": "performance_optimizer", "name": "Performance Optimizer",
        "purpose": "Compare bot, model, node and workflow reliability, latency and resource cost before proposing routes.",
        "owners": ["reliability_sentinel", "evidence_auditor"],
        "state": "staged", "mode": "recommendations_only",
    },
    {
        "id": "executive_brief", "name": "Executive Morning Brief",
        "purpose": "One quiet report for money, orders, inventory, communications, deadlines, health, risk and top actions.",
        "owners": ["daily_briefing_officer"],
        "state": "integrated_candidate", "mode": "exception_only",
    },
)


def solo_operator_blueprint() -> dict[str, Any]:
    return {
        "name": "ORCA Solo Operator System", "version": 1,
        "modules": [dict(module) for module in SOLO_OPERATOR_MODULES],
        "module_count": len(SOLO_OPERATOR_MODULES),
        "agent_loop": ["observe", "plan", "route", "verify", "record", "monitor"],
        "current_front_door": "action_center",
        "external_actions": 0,
        "boundaries": [
            "no purchase or money movement", "no external communication",
            "no publication", "no mailbox or calendar mutation",
            "no secret disclosure", "no silent consent change",
            "no automatic replay", "no core modification",
        ],
    }


def _text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError(f"Action Center {field} is invalid")
    result = value.strip()
    if redact_text(result) != result:
        raise ValueError(f"Action Center {field} contains secret-shaped content")
    return result


def build_action_plan(signals: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a stable review queue without creating or executing downstream work."""
    if not isinstance(signals, list) or len(signals) > 500:
        raise ValueError("Action Center signals must be a list of at most 500 items")
    prepared: dict[str, dict[str, Any]] = {}
    required = {"source_id", "source", "kind", "summary", "priority", "due_at",
                "workspace", "owner", "evidence", "approval_required"}
    for raw in signals:
        if not isinstance(raw, dict) or set(raw) != required:
            raise ValueError("Action Center signal has an invalid schema")
        source_id = _text(raw["source_id"], "source ID", 160)
        if not _ID.fullmatch(source_id):
            raise ValueError("Action Center source ID is invalid")
        kind = _text(raw["kind"], "kind", 32)
        priority = _text(raw["priority"], "priority", 16)
        if kind not in _KINDS or priority not in _PRIORITY:
            raise ValueError("Action Center kind or priority is invalid")
        due_at = None if raw["due_at"] is None else _text(
            raw["due_at"], "due time", 64,
        )
        if not isinstance(raw["approval_required"], bool):
            raise ValueError("Action Center approval flag is invalid")
        item = {
            "source_id": source_id,
            "source": _text(raw["source"], "source", 80),
            "kind": kind,
            "summary": _text(raw["summary"], "summary", 1_000),
            "priority": priority,
            "due_at": due_at,
            "workspace": _text(raw["workspace"], "workspace", 80),
            "owner": _text(raw["owner"], "owner", 80),
            "evidence": _text(raw["evidence"], "evidence", 500),
            "approval_required": raw["approval_required"],
            "state": "waiting_for_owner_review" if raw["approval_required"] else "proposed",
        }
        previous = prepared.get(source_id)
        if previous and previous != item:
            raise ValueError("Action Center source ID was reused with conflicting content")
        prepared[source_id] = item
    queue = sorted(prepared.values(), key=lambda item: (
        _PRIORITY[item["priority"]], item["due_at"] is None,
        item["due_at"] or "9999", item["source_id"]))
    encoded = json.dumps(queue, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return {
        "plan_id": f"action-plan-{sha256(encoded.encode()).hexdigest()[:20]}",
        "items": queue, "count": len(queue),
        "approvals": sum(item["approval_required"] for item in queue),
        "duplicates_removed": len(signals) - len(queue),
        "external_actions": 0, "jobs_created": 0, "records_mutated": 0,
        "state": "owner_review_required" if queue else "clear",
    }
