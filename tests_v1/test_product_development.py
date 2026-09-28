from pathlib import Path
from threading import Thread
from urllib.request import Request, urlopen
import json

import pytest

from orca.control_plane import ControlPlane
from orca.domain import JobStatus
from orca.product_development import (
    build_product_development_plan,
    validate_product_development_plan,
)
from orca.product_development_simulation import run_product_development_simulation
from orca.web import OrcaHTTPServer


def inventory():
    return {"items": [
        {"sku": "R-10K", "name": "10 kOhm resistor", "quantity": 500},
        {"sku": "ESP32-S3", "name": "ESP32-S3 module", "quantity": 4},
    ]}


def test_general_electronics_plan_is_multidisciplinary_and_stage_gated():
    plan = build_product_development_plan(
        "Develop a smart electronic irrigation controller with sensors and an app",
        inventory(),
    )

    assert plan["maturity"] == "concept"
    assert plan["release_state"] == "not_released"
    assert len(plan["phases"]) == 10
    assert [phase["id"] for phase in plan["phases"]][:3] == [
        "discovery", "requirements", "architecture"]
    track_ids = {track["id"] for track in plan["tracks"]}
    assert {"product", "quality", "supply", "electrical", "firmware", "mechanical"} <= track_ids
    assert {item["id"] for item in plan["requirements"]} >= {"PRD-001", "PRD-007", "PRD-008"}
    assert any(item["id"] == "CAD-001" for item in plan["deliverables"])
    assert any(item["id"] == "SW-001" for item in plan["deliverables"])
    assert all(gate["status"] == "required" for gate in plan["approval_gates"])


def test_wireless_battery_product_adds_safety_security_and_specialist_tracks():
    plan = build_product_development_plan(
        "Build a portable rechargeable lithium battery Wi-Fi sensor with AI vision")
    track_ids = {track["id"] for track in plan["tracks"]}
    risk_ids = {risk["id"] for risk in plan["risks"]}

    assert {"rf", "battery", "ai"} <= track_ids
    assert {"RISK-005", "RISK-006"} <= risk_ids
    assert plan["inventory"]["state"] == "unavailable"
    assert plan["inventory"]["matched_items"] == []


def test_inventory_is_inspected_but_never_allocated_from_vague_prompt():
    plan = build_product_development_plan("Create a sensor control board", inventory())
    assert plan["inventory"]["state"] == "available"
    assert plan["inventory"]["items_seen"] == 2
    assert plan["inventory"]["matched_items"] == []
    assert "no part is allocated" in plan["inventory"]["warning"]


def test_plan_validation_rejects_forged_risk_score_and_release_claim():
    plan = build_product_development_plan("Create a mechanical desktop organizer")
    plan["risks"][0]["rpn"] += 1
    with pytest.raises(ValueError, match="priority number"):
        validate_product_development_plan(plan)

    plan = build_product_development_plan("Create a mechanical desktop organizer")
    plan["release_state"] = "manufacturing_ready"
    with pytest.raises(ValueError, match="unreleased concepts"):
        validate_product_development_plan(plan)


def test_legacy_kicad_generator_is_explicitly_bounded():
    supported = build_product_development_plan("Create an AI-powered dog feeder")
    unsupported = build_product_development_plan("Create a laboratory power supply")
    assert supported["legacy_pcb_draft_supported"] is True
    assert unsupported["legacy_pcb_draft_supported"] is False


def test_control_plane_records_product_and_routes_plan_to_quench():
    control = ControlPlane()
    result = control.create_product_development_plan(
        prompt="Develop a smart electronic irrigation controller with sensors",
        inventory=inventory(), requested_by="fry")

    assert result["job"]["status"] == "review"
    assert result["job"]["reviewer"] == "quench"
    assert result["job"]["task_type"] == "product_development"
    assert result["record"]["record_type"] == "product"
    assert result["record"]["data"]["release_state"] == "not_released"
    assert control.jobs[result["job"]["id"]].status is JobStatus.REVIEW
    kinds = {event["kind"] for event in control.evidence.list(limit=30)}
    assert "product.development.plan_created" in kinds
    assert "job.review_requested" in kinds

    revised = control.create_product_development_plan(
        prompt="Develop a smart electronic irrigation controller with sensors",
        inventory=inventory(), requested_by="fry")
    assert revised["record"]["version"] == 2
    assert revised["record"]["source_revision"] == 2


def test_product_development_http_route_is_idempotent():
    class Inventory:
        def snapshot(self):
            return inventory()

    token = "p" * 32
    control = ControlPlane()
    server = OrcaHTTPServer(
        ("127.0.0.1", 0), control, operator_token=token,
        inventory_provider=Inventory())
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        body = json.dumps({"prompt": "Build an electronic bench instrument"}).encode()
        headers = {
            "Content-Type": "application/json",
            "X-ORCA-Operator-Token": token,
            "Idempotency-Key": "product-development-test-0001",
            "X-ORCA-Expected-Revision": str(control.state_revision),
        }
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/product-development/plans",
            data=body, method="POST", headers=headers)
        with urlopen(request) as response:
            first = json.load(response)
        with urlopen(request) as response:
            replay = json.load(response)
        assert first == replay
        assert response.headers["X-ORCA-Idempotency-Replayed"] == "true"
        assert control.snapshot()["business"]["counts"]["product"] == 1
    finally:
        server.shutdown()
        server.server_close()


def test_product_development_ui_exposes_program_controls():
    html = Path("orca/static/index.html").read_text()
    script = Path("orca/static/product-builder.js").read_text()
    css = Path("orca/static/product-development.css").read_text()
    section = html.split('<section id="product-builder" class="view">', 1)[1].split(
        '<section id="operations"', 1)[0]
    for label in (
        "Product Development", "Engineering workstreams", "Requirements and traceability",
        "Risk and FMEA", "Approval gates", "Inventory evidence",
        "Deliverables and file map", "Prototype execution",
    ):
        assert label in section
    assert "/api/product-development/plans" in script
    assert "postMutation" in script
    assert "legacy_pcb_draft_supported" in script
    assert "postProjectPlan(currentPlan.brief)" in script
    assert "builder-table" in css


def test_product_development_end_to_end_simulation():
    report = run_product_development_simulation()

    assert report["passed"] is True, report["failed_checks"]
    assert report["checks_passed"] == report["checks_total"]
    assert report["checks_total"] >= 20
    assert report["details"]["external_actions"] == 0
    assert report["safety"] == {
        "network_scope": "loopback only",
        "purchases": 0,
        "supplier_contacts": 0,
        "inventory_allocations": 0,
        "deployments": 0,
    }
