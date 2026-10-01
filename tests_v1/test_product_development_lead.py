import sys
from pathlib import Path

import pytest


repository = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repository / "deploy" / "forge"))
from orca_product_development_lead import evaluate, waiting_report


def approved_brief():
    return {
        "allow_external_actions": False,
        "brief": (
            "Develop a Pi 5 reliability and hi-fi HAT with protected power, "
            "watchdog recovery, telemetry, a low-noise DAC, and service controls."
        ),
        "inventory": {
            "items": [
                {"sku": "R-10K", "name": "10 kOhm resistor", "quantity": 500},
                {"sku": "RP1-CONN", "name": "Pi GPIO connector", "quantity": 4},
            ]
        },
    }


def test_approved_brief_produces_unreleased_multidisciplinary_plan():
    report = evaluate(approved_brief(), now=1000)
    plan = report["plan"]
    assert report["state"] == "healthy"
    assert report["mode"] == "approved_brief_plan"
    assert plan["maturity"] == "concept"
    assert plan["release_state"] == "not_released"
    assert {"electrical", "firmware", "mechanical"} <= {
        track["id"] for track in plan["tracks"]}
    assert [phase["id"] for phase in plan["phases"]] == [
        "discovery", "requirements", "architecture", "feasibility",
        "detailed_design", "prototype", "verification", "manufacturing",
        "launch", "lifecycle",
    ]
    assert plan["inventory"]["items_seen"] == 2
    assert plan["inventory"]["matched_items"] == []


def test_consequential_actions_remain_zero_and_all_gates_are_closed():
    report = evaluate(approved_brief(), now=1000)
    assert report["purchases"] == report["supplier_contacts"] == 0
    assert report["inventory_allocations"] == report["manufacturing_releases"] == 0
    assert report["deployments"] == report["external_actions"] == 0
    assert all(gate["status"] == "required" for gate in report["plan"]["approval_gates"])


def test_missing_external_boundary_and_unexpected_fields_fail_closed():
    value = approved_brief()
    value.pop("allow_external_actions")
    with pytest.raises(ValueError, match="external-action boundary"):
        evaluate(value, now=1000)
    value = approved_brief()
    value["release"] = True
    with pytest.raises(ValueError, match="schema"):
        evaluate(value, now=1000)


def test_invalid_or_oversized_inventory_fails_closed():
    value = approved_brief()
    value["inventory"]["items"] = ["not-an-item"]
    with pytest.raises(ValueError, match="invalid item"):
        evaluate(value, now=1000)
    value = approved_brief()
    value["inventory"]["items"] = [{}] * 501
    with pytest.raises(ValueError, match="oversized"):
        evaluate(value, now=1000)


def test_secret_shaped_brief_is_rejected_by_core_planner():
    value = approved_brief()
    value["brief"] = "Build a board using password=super-secret-value"
    with pytest.raises(ValueError, match="secret-shaped"):
        evaluate(value, now=1000)


def test_waiting_state_is_truthful_and_inert():
    report = waiting_report(now=1000)
    assert report["state"] == "healthy"
    assert report["mode"] == "waiting_for_approved_product_brief"
    assert report["plan"] is None
    assert report["external_actions"] == 0


def test_role_contract_is_active_but_cannot_take_consequential_actions():
    from orca.roles import ROLE_CATALOG

    role = ROLE_CATALOG["product_development_lead"]
    assert role.active is True
    assert role.node_id == "forge"
    assert set(role.authority) == {
        "plan_product", "run_bounded_calculation", "stage_design_artifact",
        "coordinate_review",
    }
    assert {
        "physical_actuation", "order_part", "release_manufacturing", "approve",
        "deploy",
    } <= set(role.prohibited)
    assert role.activation_gate == "bounded_product_engineering_and_review_accepted_20261001"
