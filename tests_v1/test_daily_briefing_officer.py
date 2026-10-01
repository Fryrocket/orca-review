import sys
from copy import deepcopy
from pathlib import Path

import pytest

repository = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repository / "deploy" / "forge"))
from orca_daily_briefing_officer import REQUIRED_SOURCES, evaluate, waiting_report


def payload(now=10_000):
    return {
        "allow_external_actions": False,
        "report_date": "2026-10-01",
        "sources": [
            {"bot_id": bot_id, "observed_epoch": now - 60, "state": "healthy",
             "evidence_path": f"/var/lib/orca-{bot_id.replace('_', '-')}/status.json"}
            for bot_id in sorted(REQUIRED_SOURCES)
        ],
        "completed": ["Browser Operator accepted with private-page isolation."],
        "failures": [],
        "approvals": [{"priority": 1, "summary": "Owner review remains pending.",
                       "owner": "fry", "evidence_source": "evidence_auditor"}],
        "money": {"currency": "USD", "budget_status": "within",
                  "summary": "Approved summary reports spending within budget."},
        "inventory": {"state": "healthy", "summary": "No stock exception reported."},
        "fleet": {"state": "healthy", "summary": "Approved fleet summary is healthy."},
        "priorities": [
            {"rank": 1, "summary": "Finish bot acceptance in order.", "owner_set": True},
            {"rank": 2, "summary": "Enroll TEMPER when its identity is proven.", "owner_set": True},
        ],
    }


def test_complete_pack_produces_truthful_inert_briefing():
    report = evaluate(payload(), now=10_000)
    assert report["state"] == "healthy"
    assert report["briefing"]["headline"] == "No critical owner action required"
    assert len(report["briefing"]["source_freshness"]) == 6
    assert [row["rank"] for row in report["briefing"]["priorities"]] == [1, 2]
    assert report["failures_hidden"] == report["priorities_changed"] == 0
    assert report["approvals_granted"] == report["notifications_sent"] == 0
    assert report["external_actions"] == 0


def test_unhealthy_source_must_be_exposed_and_high_failure_leads():
    value = payload()
    source = next(row for row in value["sources"] if row["bot_id"] == "connector_steward")
    source["state"] = "degraded"
    with pytest.raises(ValueError, match="hidden"):
        evaluate(value, now=10_000)
    value["failures"] = [{"severity": "high", "summary": "Drive read path is stale.",
                          "evidence_source": "connector_steward"}]
    report = evaluate(value, now=10_000)
    assert report["briefing"]["headline"] == "Owner action required"
    assert report["briefing"]["failures"][0]["evidence_source"] == "connector_steward"


def test_owner_priority_order_cannot_be_rewritten_or_skipped():
    value = payload()
    original = deepcopy(value["priorities"])
    report = evaluate(value, now=10_000)
    assert report["briefing"]["priorities"] == original
    value["priorities"][1]["rank"] = 3
    with pytest.raises(ValueError, match="owner-set contiguous order"):
        evaluate(value, now=10_000)


def test_missing_duplicate_stale_or_future_sources_fail_closed():
    value = payload()
    value["sources"].pop()
    with pytest.raises(ValueError, match="required sources"):
        evaluate(value, now=10_000)
    value = payload()
    value["sources"][-1]["bot_id"] = value["sources"][0]["bot_id"]
    with pytest.raises(ValueError, match="duplicate"):
        evaluate(value, now=10_000)
    value = payload()
    value["sources"][0]["observed_epoch"] = 10_000 - 86_401
    with pytest.raises(ValueError, match="stale or future"):
        evaluate(value, now=10_000)
    value = payload()
    value["sources"][0]["observed_epoch"] = 10_001
    with pytest.raises(ValueError, match="stale or future"):
        evaluate(value, now=10_000)


def test_secret_shaped_text_and_external_actions_fail_closed():
    value = payload()
    value["completed"] = ["api_key=do-not-log-this"]
    with pytest.raises(ValueError, match="secret-shaped"):
        evaluate(value, now=10_000)
    value = payload()
    value["allow_external_actions"] = True
    with pytest.raises(ValueError, match="external-action"):
        evaluate(value, now=10_000)


def test_waiting_state_is_truthful_and_inert():
    report = waiting_report(now=10_000)
    assert report["state"] == "healthy"
    assert report["mode"] == "waiting_for_approved_summary_pack"
    assert report["briefing"] is None
    assert report["notifications_sent"] == report["external_actions"] == 0


def test_role_contract_is_active_and_non_authoritative():
    from orca.roles import ROLE_CATALOG

    role = ROLE_CATALOG["daily_briefing_officer"]
    assert role.active
    assert role.node_id == "forge"
    assert set(role.authority) == {"read_approved_summary", "compile_briefing", "stage_report"}
    assert {"contact_outsider", "change_priority_without_owner", "hide_failure", "approve", "deploy"} <= set(role.prohibited)
    assert role.activation_gate == "cross_source_truthful_owner_briefing_accepted_20261001"
