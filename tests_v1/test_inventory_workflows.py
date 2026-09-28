from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import json

import pytest

from orca.control_plane import ControlPlane
from orca.domain import JobStatus
from orca.inventory_workflows import (
    calculate_inventory_changes,
    validate_inventory_operation,
)
from orca.web import OrcaHTTPServer


def operation(kind="reserve", **overrides):
    value = {
        "operation_type": kind,
        "sku": "PART-1",
        "location": "BIN-A",
        "quantity": 2,
        "reason": "Approved prototype allocation",
        "evidence": "Build record BR-100",
    }
    if kind == "transfer":
        value["target_location"] = "BIN-B"
    value.update(overrides)
    return value


def seed(control, *, location="BIN-A", on_hand=10, reserved=1, revision=1):
    return control.upsert_business_record(
        record_type="inventory_position", record_id=f"PART-1:{location}",
        source_system="seed", source_revision=revision, status="active",
        data={"sku": "PART-1", "location": location,
              "on_hand": on_hand, "reserved": reserved},
        provenance={"kind": "test_fixture"}, confidence=1.0,
        requested_by="fry",
    )["record"]


@pytest.mark.parametrize(("kind", "quantity", "expected"), [
    ("receive", 4, {"on_hand": 14.0, "reserved": 1.0, "available": 13.0}),
    ("reserve", 4, {"on_hand": 10.0, "reserved": 5.0, "available": 5.0}),
    ("release", 1, {"on_hand": 10.0, "reserved": 0.0, "available": 10.0}),
    ("cycle_count", 8, {"on_hand": 8.0, "reserved": 1.0, "available": 7.0}),
    ("adjustment", 12, {"on_hand": 12.0, "reserved": 1.0, "available": 11.0}),
])
def test_inventory_workflow_calculates_each_single_position_operation(
        kind, quantity, expected):
    result = calculate_inventory_changes(
        validate_inventory_operation(operation(kind, quantity=quantity)),
        {"BIN-A": {"on_hand": 10, "reserved": 1}},
    )
    assert result == {"BIN-A": expected}


def test_inventory_transfer_is_balanced_and_uses_available_not_on_hand():
    result = calculate_inventory_changes(
        validate_inventory_operation(operation("transfer", quantity=6)),
        {"BIN-A": {"on_hand": 10, "reserved": 3},
         "BIN-B": {"on_hand": 2, "reserved": 0}},
    )
    assert result == {
        "BIN-A": {"on_hand": 4.0, "reserved": 3.0, "available": 1.0},
        "BIN-B": {"on_hand": 8.0, "reserved": 0.0, "available": 8.0},
    }
    with pytest.raises(ValueError, match="exceeds available"):
        calculate_inventory_changes(
            operation("transfer", quantity=8),
            {"BIN-A": {"on_hand": 10, "reserved": 3},
             "BIN-B": {"on_hand": 2, "reserved": 0}},
        )


def test_inventory_workflow_rejects_unsafe_or_ambiguous_requests():
    with pytest.raises(ValueError, match="positive"):
        validate_inventory_operation(operation("receive", quantity=0))
    with pytest.raises(ValueError, match="different locations"):
        validate_inventory_operation(operation(
            "transfer", target_location="BIN-A"))
    with pytest.raises(ValueError, match="below reserved"):
        calculate_inventory_changes(
            operation("cycle_count", quantity=0),
            {"BIN-A": {"on_hand": 10, "reserved": 1}},
        )
    with pytest.raises(ValueError, match="release exceeds"):
        calculate_inventory_changes(
            operation("release", quantity=2),
            {"BIN-A": {"on_hand": 10, "reserved": 1}},
        )


def test_reservation_requires_approval_updates_ledger_and_routes_to_quench():
    control = ControlPlane()
    seed(control)
    proposal = control.propose_inventory_workflow(
        operation=operation("reserve", quantity=3), requested_by="fry")
    job = proposal["job"]

    assert job["level"] == "R2"
    assert job["status"] == "waiting_approval"
    assert job["assigned_to"] == "smith"
    assert proposal["preview"]["BIN-A"]["available"] == 6
    with pytest.raises(PermissionError, match="requires Fry approval"):
        control.run_approved_inventory_workflow(job["id"], requested_by="fry")

    control.decide(job["approval_id"], actor="fry", approve=True,
                   note="Reserve for approved prototype build")
    result = control.run_approved_inventory_workflow(
        job["id"], requested_by="fry")

    assert result["job"]["status"] == "review"
    assert result["job"]["reviewer"] == "quench"
    assert result["records"][0]["data"]["reserved"] == 4
    assert result["records"][0]["data"]["available"] == 6
    completed = control.complete_job(
        job["id"], actor="quench",
        note="Reservation math and approval evidence verified")
    assert completed.status is JobStatus.COMPLETE
    kinds = {item["kind"] for item in control.evidence.list(limit=50)}
    assert {"inventory.workflow.proposed", "inventory.workflow.execution_triggered",
            "inventory.workflow.applied", "job.review_requested", "job.completed"} <= kinds


def test_transfer_updates_two_positions_atomically_after_approval():
    control = ControlPlane()
    seed(control, location="BIN-A", on_hand=10, reserved=2)
    seed(control, location="BIN-B", on_hand=1, reserved=0)
    proposal = control.propose_inventory_workflow(
        operation=operation("transfer", quantity=5), requested_by="fry")
    control.decide(proposal["job"]["approval_id"], actor="fry", approve=True)
    result = control.run_approved_inventory_workflow(
        proposal["job"]["id"], requested_by="fry")

    records = {item["data"]["location"]: item["data"] for item in result["records"]}
    assert records["BIN-A"]["on_hand"] == 5
    assert records["BIN-A"]["reserved"] == 2
    assert records["BIN-B"]["on_hand"] == 6
    assert control.business.verify() is True


def test_changed_position_blocks_execution_and_preserves_newer_truth():
    control = ControlPlane()
    seed(control)
    proposal = control.propose_inventory_workflow(
        operation=operation("adjustment", quantity=12), requested_by="fry")
    control.upsert_business_record(
        record_type="inventory_position", record_id="PART-1:BIN-A",
        source_system="cycle_counter", source_revision=1, status="active",
        data={"sku": "PART-1", "location": "BIN-A", "on_hand": 9, "reserved": 1},
        provenance={"kind": "newer_count"}, confidence=1.0, requested_by="fry")
    control.decide(proposal["job"]["approval_id"], actor="fry", approve=True)

    with pytest.raises(ValueError, match="changed after proposal"):
        control.run_approved_inventory_workflow(
            proposal["job"]["id"], requested_by="fry")
    assert control.business.get(
        "inventory_position", "PART-1:BIN-A")["data"]["on_hand"] == 9


def test_inventory_workflow_http_proposal_is_idempotent():
    token = "i" * 32
    control = ControlPlane()
    seed(control)
    server = OrcaHTTPServer(("127.0.0.1", 0), control, operator_token=token)
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        payload = json.dumps({"operation": operation("reserve")}).encode()
        headers = {
            "Content-Type": "application/json", "X-ORCA-Operator-Token": token,
            "Idempotency-Key": "inventory-workflow-proposal-0001",
            "X-ORCA-Expected-Revision": str(control.state_revision),
        }
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/inventory/workflows",
            data=payload, method="POST", headers=headers)
        with urlopen(request) as response:
            first = json.load(response)
        with urlopen(request) as response:
            replay = json.load(response)
            assert response.headers["X-ORCA-Idempotency-Replayed"] == "true"
        assert first == replay
        assert len([job for job in control.jobs.values()
                    if job.task_type == "inventory_workflow"]) == 1
    finally:
        server.shutdown()
        server.server_close()


def test_inventory_workflow_ui_has_all_governed_operations():
    html = open("orca/static/index.html", encoding="utf-8").read()
    script = open("orca/static/app.js", encoding="utf-8").read()
    section = html.split('<section id="inventory" class="view">', 1)[1].split(
        '<section id="engineering"', 1)[0]
    for label in (
        "Governed stock workflow", "Receive stock", "Transfer location",
        "Record cycle count", "Reserve stock", "Release reservation",
        "Correct quantity", "Calculate and request approval",
    ):
        assert label in section
    assert "/api/inventory/workflows" in script
    assert "data-inventory-execute" in script
