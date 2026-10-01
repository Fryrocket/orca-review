#!/usr/bin/env python3
"""Deterministic, read-only owner briefing compiler for ORCA."""

import argparse
import json
import os
import re
import time
from pathlib import Path


REQUIRED_SOURCES = {
    "reliability_sentinel", "recovery_marshal", "connector_steward",
    "budget_officer", "inventory_steward", "evidence_auditor",
}
SOURCE_STATES = {"healthy", "degraded", "critical", "unavailable"}
SEVERITIES = {"critical": 0, "high": 1, "medium": 2, "low": 3}
MAX_AGE_SECONDS = 86_400
MAX_INPUT_BYTES = 256_000
SECRET_PATTERN = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|password|passwd|secret)\s*[:=]\s*\S+"
)


def _text(value, name, maximum=2_000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"invalid {name}")
    cleaned = value.strip()
    if SECRET_PATTERN.search(cleaned):
        raise ValueError(f"{name} contains secret-shaped data")
    return cleaned


def _text_list(value, name, maximum=100):
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"invalid {name}")
    return [_text(item, name) for item in value]


def _summary(value, name, states):
    if not isinstance(value, dict) or set(value) != {"state", "summary"}:
        raise ValueError(f"invalid {name}")
    state = value.get("state")
    if state not in states:
        raise ValueError(f"invalid {name} state")
    return {"state": state, "summary": _text(value.get("summary"), f"{name} summary")}


def evaluate(data, now=None):
    now = int(time.time() if now is None else now)
    expected = {
        "allow_external_actions", "report_date", "sources", "completed",
        "failures", "approvals", "money", "inventory", "fleet", "priorities",
    }
    if not isinstance(data, dict) or set(data) != expected:
        raise ValueError("invalid briefing pack schema")
    if data.get("allow_external_actions") is not False:
        raise ValueError("external-action boundary missing")
    report_date = _text(data.get("report_date"), "report date", 10)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", report_date):
        raise ValueError("invalid report date")

    sources = data.get("sources")
    if not isinstance(sources, list) or len(sources) != len(REQUIRED_SOURCES):
        raise ValueError("required sources missing")
    normalized_sources = []
    seen = set()
    for row in sources:
        if not isinstance(row, dict) or set(row) != {
                "bot_id", "observed_epoch", "state", "evidence_path"}:
            raise ValueError("invalid source schema")
        bot_id = _text(row.get("bot_id"), "source bot id", 80)
        if bot_id in seen:
            raise ValueError("duplicate source")
        seen.add(bot_id)
        observed = row.get("observed_epoch")
        if type(observed) is not int or observed > now or now - observed > MAX_AGE_SECONDS:
            raise ValueError("stale or future source")
        state = row.get("state")
        if state not in SOURCE_STATES:
            raise ValueError("invalid source state")
        evidence_path = _text(row.get("evidence_path"), "evidence path", 500)
        if not evidence_path.startswith("/var/lib/") or ".." in evidence_path:
            raise ValueError("invalid evidence path")
        normalized_sources.append({
            "bot_id": bot_id, "observed_epoch": observed, "state": state,
            "evidence_path": evidence_path, "age_seconds": now - observed,
        })
    if seen != REQUIRED_SOURCES:
        raise ValueError("required sources missing")

    completed = _text_list(data.get("completed"), "completed item")
    failures = data.get("failures")
    if not isinstance(failures, list) or len(failures) > 100:
        raise ValueError("invalid failures")
    normalized_failures = []
    for row in failures:
        if not isinstance(row, dict) or set(row) != {"severity", "summary", "evidence_source"}:
            raise ValueError("invalid failure")
        severity = row.get("severity")
        source = row.get("evidence_source")
        if severity not in SEVERITIES or source not in REQUIRED_SOURCES:
            raise ValueError("invalid failure severity or source")
        normalized_failures.append({
            "severity": severity,
            "summary": _text(row.get("summary"), "failure summary"),
            "evidence_source": source,
        })
    failed_sources = {row["evidence_source"] for row in normalized_failures}
    unhealthy_sources = {row["bot_id"] for row in normalized_sources if row["state"] != "healthy"}
    if not unhealthy_sources <= failed_sources:
        raise ValueError("source failure was hidden")
    normalized_failures.sort(key=lambda row: (SEVERITIES[row["severity"]], row["evidence_source"], row["summary"]))

    approvals = data.get("approvals")
    if not isinstance(approvals, list) or len(approvals) > 100:
        raise ValueError("invalid approvals")
    normalized_approvals = []
    for row in approvals:
        if not isinstance(row, dict) or set(row) != {"priority", "summary", "owner", "evidence_source"}:
            raise ValueError("invalid approval")
        priority = row.get("priority")
        if type(priority) is not int or not 1 <= priority <= 5:
            raise ValueError("invalid approval priority")
        source = row.get("evidence_source")
        if source not in REQUIRED_SOURCES or row.get("owner") != "fry":
            raise ValueError("invalid approval owner or source")
        normalized_approvals.append({
            "priority": priority, "summary": _text(row.get("summary"), "approval summary"),
            "owner": "fry", "evidence_source": source,
        })
    normalized_approvals.sort(key=lambda row: (row["priority"], row["evidence_source"]))

    money = data.get("money")
    if not isinstance(money, dict) or set(money) != {"currency", "budget_status", "summary"}:
        raise ValueError("invalid money summary")
    currency = _text(money.get("currency"), "currency", 3).upper()
    if len(currency) != 3 or not currency.isalpha() or money.get("budget_status") not in {
            "within", "attention", "over", "unavailable"}:
        raise ValueError("invalid money state")
    normalized_money = {
        "currency": currency, "budget_status": money["budget_status"],
        "summary": _text(money.get("summary"), "money summary"),
    }
    inventory = _summary(data.get("inventory"), "inventory", {"healthy", "attention", "unavailable"})
    fleet = _summary(data.get("fleet"), "fleet", {"healthy", "degraded", "critical", "unavailable"})

    priorities = data.get("priorities")
    if not isinstance(priorities, list) or len(priorities) > 100:
        raise ValueError("invalid priorities")
    normalized_priorities = []
    expected_rank = 1
    for row in priorities:
        if not isinstance(row, dict) or set(row) != {"rank", "summary", "owner_set"}:
            raise ValueError("invalid priority")
        if row.get("owner_set") is not True or row.get("rank") != expected_rank:
            raise ValueError("priorities must preserve owner-set contiguous order")
        normalized_priorities.append({
            "rank": expected_rank, "summary": _text(row.get("summary"), "priority summary"),
            "owner_set": True,
        })
        expected_rank += 1

    action_required = any(row["severity"] in {"critical", "high"} for row in normalized_failures)
    return {
        "schema_version": 1,
        "bot_id": "daily_briefing_officer",
        "state": "healthy",
        "mode": "approved_summary_pack",
        "observed_epoch": now,
        "authority": "read_only_truthful_owner_briefing",
        "briefing": {
            "report_date": report_date,
            "headline": "Owner action required" if action_required else "No critical owner action required",
            "completed": completed,
            "failures": normalized_failures,
            "pending_approvals": normalized_approvals,
            "money": normalized_money,
            "inventory": inventory,
            "fleet": fleet,
            "priorities": normalized_priorities,
            "source_freshness": sorted(normalized_sources, key=lambda row: row["bot_id"]),
        },
        "failures_hidden": 0,
        "priorities_changed": 0,
        "approvals_granted": 0,
        "notifications_sent": 0,
        "external_actions": 0,
    }


def waiting_report(now=None):
    return {
        "schema_version": 1,
        "bot_id": "daily_briefing_officer",
        "state": "healthy",
        "mode": "waiting_for_approved_summary_pack",
        "observed_epoch": int(time.time() if now is None else now),
        "authority": "read_only_truthful_owner_briefing",
        "briefing": None,
        "failures_hidden": 0,
        "priorities_changed": 0,
        "approvals_granted": 0,
        "notifications_sent": 0,
        "external_actions": 0,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="/var/lib/orca-daily-briefing-input/approved-summary.json")
    parser.add_argument("--output", default="/var/lib/orca-daily-briefing-officer/status.json")
    args = parser.parse_args()
    try:
        source = Path(args.input)
        if source.exists() and source.stat().st_size > MAX_INPUT_BYTES:
            raise ValueError("briefing pack oversized")
        report = evaluate(json.loads(source.read_text(encoding="utf-8"))) if source.exists() else waiting_report()
    except (OSError, ValueError, json.JSONDecodeError, TypeError) as exc:
        report = waiting_report()
        report.update({"state": "degraded", "mode": "invalid_summary_pack", "error": type(exc).__name__})
    target = Path(args.output)
    target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o640)
    os.replace(temporary, target)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["state"] == "healthy" else 1


if __name__ == "__main__":
    raise SystemExit(main())
