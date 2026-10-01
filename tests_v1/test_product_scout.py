import sys
from pathlib import Path

import pytest

repository = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repository / "deploy" / "forge"))
from orca_product_scout import evaluate, waiting_report


def candidate(candidate_id="C-1", demand=75, competition=40):
    return {
        "id": candidate_id,
        "name": f"Candidate {candidate_id}",
        "sale_price": "40.00",
        "landed_cost": "12.00",
        "fulfillment_cost": "5.00",
        "marketplace_fee_percent": "15",
        "demand_score": demand,
        "competition_score": competition,
        "supplier_fit_score": 80,
        "compliance_risk_score": 20,
        "return_risk_score": 25,
        "evidence": [{
            "label": "Observed listing price",
            "url": "https://example.com/listing",
            "signal_type": "price_observation",
            "observed_fact": "The observed listing price was USD 40 on the cited page.",
        }],
    }


def payload(*candidates):
    return {"allow_external_actions": False, "candidates": list(candidates)}


def test_candidates_are_ranked_with_exact_economics_and_zero_actions():
    report = evaluate(payload(candidate("C-1", demand=60), candidate("C-2", demand=90)), now=1000)
    assert report["state"] == "healthy"
    assert [row["id"] for row in report["ranked_candidates"]] == ["C-2", "C-1"]
    assert report["ranked_candidates"][0]["gross_profit"] == 17.0
    assert report["ranked_candidates"][0]["margin_percent"] == 42.5
    assert report["sales_estimates_created"] == 0
    assert report["purchases"] == report["vendor_contacts"] == 0
    assert report["publications"] == report["external_actions"] == 0


def test_uncited_or_non_https_evidence_fails_closed():
    value = candidate()
    value["evidence"][0]["url"] = "http://example.com/listing"
    with pytest.raises(ValueError, match="HTTPS"):
        evaluate(payload(value), now=1000)


def test_unsupported_sales_estimate_fails_closed():
    value = candidate()
    value["estimated_sales"] = 1000
    with pytest.raises(ValueError, match="sales estimate"):
        evaluate(payload(value), now=1000)


def test_external_action_boundary_is_mandatory():
    with pytest.raises(ValueError, match="external-action boundary"):
        evaluate({"candidates": [candidate()]}, now=1000)


def test_invalid_numbers_and_duplicate_ids_fail_closed():
    bad = candidate()
    bad["sale_price"] = float("nan")
    with pytest.raises(ValueError, match="sale_price"):
        evaluate(payload(bad), now=1000)
    with pytest.raises(ValueError, match="duplicate"):
        evaluate(payload(candidate(), candidate()), now=1000)


def test_waiting_state_is_truthful_and_inert():
    report = waiting_report(now=1000)
    assert report["state"] == "healthy"
    assert report["mode"] == "waiting_for_approved_candidate_pack"
    assert report["ranked_candidates"] == []
    assert report["external_actions"] == 0


def test_role_contract_is_active_but_cannot_take_consequential_actions():
    from orca.roles import ROLE_CATALOG

    role = ROLE_CATALOG["product_scout"]
    assert role.active
    assert role.node_id == "forge"
    assert set(role.authority) == {
        "research_product", "compare_supplier", "score_candidate", "cite_evidence"
    }
    assert {"invent_sales_data", "purchase", "contact_vendor", "publish", "approve"} <= set(role.prohibited)
    assert role.activation_gate == "cited_synthetic_product_research_accepted_20261001"
