"""Deterministic, read-only communications intelligence for ORCA."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable


_NO_ACTION = {"", "none", "no follow-up", "no action", "n/a"}
_RISK_TERMS = (
    "suspicious", "phishing", "spoof", "malware", "credential", "password",
    "unexpected attachment", "unknown link", "impersonation", "fraud",
)
_ROUTES = {
    "order": ("inventory", "channel_operator"),
    "invoice": ("accounting", "budget_officer"),
    "lead": ("business", "channel_operator"),
    "support": ("operations", "daily_briefing_officer"),
    "compliance": ("legal", "legal_compliance_clerk"),
    "vendor": ("business", "connector_steward"),
    "spam": ("security", "security_watch"),
    "other": ("inbox", "daily_briefing_officer"),
}


def _needs_follow_up(message: dict[str, Any]) -> bool:
    return str(message.get("follow_up", "")).strip().lower() not in _NO_ACTION


def _is_quarantined(message: dict[str, Any]) -> bool:
    text = " ".join(str(message.get(field, "")).lower() for field in (
        "category", "subject", "summary", "follow_up", "uncertainty"))
    return message.get("category") == "spam" or any(term in text for term in _RISK_TERMS)


def build_communications_snapshot(messages: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Build timelines, tasks, calendar candidates, quarantine, and a short brief.

    The result deliberately contains no action executor. It is an owner-facing
    operating picture derived from already minimized Inbox records.
    """
    rows = [dict(message) for message in messages]
    rows.sort(key=lambda item: (str(item.get("received_at", "")),
                                str(item.get("message_reference", ""))), reverse=True)
    quarantined = [message for message in rows if _is_quarantined(message)]
    safe_rows = [message for message in rows if message not in quarantined]
    tasks = [{
        "message_reference": message["message_reference"],
        "association": message["project_or_customer"],
        "subject": message["subject"],
        "action": message["follow_up"],
        "deadline": message.get("deadline"),
        "priority": message["priority"],
        "draft_available": bool(message.get("draft_reply")),
        "state": "owner_review_required",
        "proposed_workspace": _ROUTES[message["category"]][0],
        "proposed_owner": _ROUTES[message["category"]][1],
        "source_reference": message["message_reference"],
    } for message in safe_rows if _needs_follow_up(message)]
    calendar = [{
        "message_reference": task["message_reference"],
        "title": task["subject"],
        "association": task["association"],
        "when": task["deadline"],
        "state": "candidate_only",
    } for task in tasks if task.get("deadline")]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for message in safe_rows:
        grouped[message["project_or_customer"]].append(message)
    timelines = [{
        "association": association,
        "message_count": len(items),
        "last_received_at": items[0]["received_at"],
        "open_follow_ups": sum(_needs_follow_up(item) for item in items),
        "high_or_urgent": sum(item["priority"] in {"high", "urgent"} for item in items),
        "recent_subjects": [item["subject"] for item in items[:5]],
    } for association, items in grouped.items()]
    timelines.sort(key=lambda item: (item["last_received_at"], item["association"]),
                   reverse=True)
    urgent = sum(message["priority"] == "urgent" for message in safe_rows)
    briefing = {
        "headline": (
            f"{len(tasks)} follow-up(s), {len(calendar)} deadline(s), "
            f"{len(quarantined)} quarantined item(s)."
        ),
        "urgent": urgent,
        "top_actions": tasks[:5],
        "generated_from": "privacy_minimized_inbox_summaries",
        "proposed_handoffs": [{
            "message_reference": task["message_reference"],
            "workspace": task["proposed_workspace"],
            "owner": task["proposed_owner"],
            "state": "proposal_only",
        } for task in tasks[:5]],
        "external_actions": 0,
    }
    return {
        "status": "ready" if rows else "waiting_for_authorized_mail_summary",
        "mode": "read_only_owner_review",
        "messages": rows,
        "tasks": tasks,
        "calendar_candidates": calendar,
        "timelines": timelines,
        "quarantine": quarantined,
        "daily_brief": briefing,
        "counts": {
            "messages": len(rows), "follow_ups": len(tasks),
            "deadlines": len(calendar), "relationships": len(timelines),
            "quarantined": len(quarantined), "urgent": urgent,
        },
        "controls": {
            "mailbox_mutations": 0, "messages_sent": 0,
            "calendar_writes": 0, "contacts_written": 0,
            "links_opened": 0, "attachments_opened": 0,
            "approval_required_for_external_action": True,
        },
    }
