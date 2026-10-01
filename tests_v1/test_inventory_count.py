from pathlib import Path

import pytest

from orca.control_plane import ControlPlane
from orca.inventory_count import (
    build_count_reconciliation,
    validate_count_observations,
)


def observations():
    return [
        {"sku": "PART-A", "barcode": "PART-A", "location": "BIN-1",
         "counted_quantity": 8, "unit": "ea", "lot": "LOT-1",
         "serial": "", "condition": "good", "notes": "First shelf"},
        {"sku": "PART-B", "barcode": "PART-B", "location": "BIN-2",
         "counted_quantity": 1, "unit": "ea", "lot": "",
         "serial": "SER-001", "condition": "new", "notes": "Verified label"},
    ]


def seed(control, sku, location, on_hand, reserved=0):
    return control.upsert_business_record(
        record_type="inventory_position", record_id=f"{sku}:{location}",
        source_system="count_test_seed", source_revision=1, status="active",
        data={"sku": sku, "location": location,
              "on_hand": on_hand, "reserved": reserved},
        provenance={"kind": "fixture"}, confidence=1.0,
        requested_by="fry")["record"]


def test_count_reconciliation_reports_matches_variances_lots_and_serials():
    result = build_count_reconciliation(
        observations(),
        {
            "PART-A:BIN-1": {"on_hand": 10, "reserved": 2},
            "PART-B:BIN-2": {"on_hand": 1, "reserved": 0},
        },
        reason="Scheduled physical inventory",
        evidence="Count sheet COUNT-100",
    )

    assert result["release_state"] == "approval_required"
    assert result["metrics"] == {
        "observations": 2, "matches": 1, "variances": 1, "blocked": 0,
        "net_variance": -2.0, "serialized": 1, "lots": 1,
    }
    assert result["rows"][0]["variance"] == -2
    assert result["rows"][1]["status"] == "match"


def test_count_reconciliation_blocks_counts_below_reservations():
    result = build_count_reconciliation(
        [observations()[0]],
        {"PART-A:BIN-1": {"on_hand": 10, "reserved": 9}},
        reason="Scheduled physical inventory", evidence="COUNT-101")
    assert result["release_state"] == "blocked"
    assert result["metrics"]["blocked"] == 1
    assert "below reserved" in result["rows"][0]["blocker"]


def test_count_observations_reject_duplicate_and_bad_serial_counts():
    duplicate = observations()[0]
    with pytest.raises(ValueError, match="duplicate observation"):
        validate_count_observations([duplicate, dict(duplicate)])
    bad_serial = dict(observations()[1], counted_quantity=2)
    with pytest.raises(ValueError, match="exactly one"):
        validate_count_observations([bad_serial])


def test_count_session_requires_approval_applies_atomically_and_routes_review():
    control = ControlPlane()
    seed(control, "PART-A", "BIN-1", 10, reserved=2)
    seed(control, "PART-B", "BIN-2", 1)
    preview = control.preview_inventory_count_session(
        observations=observations(), reason="Scheduled physical inventory",
        evidence="COUNT-100", requested_by="fry")
    assert preview["metrics"]["variances"] == 1

    proposal = control.propose_inventory_count_session(
        observations=observations(), reason="Scheduled physical inventory",
        evidence="COUNT-100", requested_by="fry")
    assert proposal["job"]["status"] == "waiting_approval"
    assert proposal["job"]["assigned_to"] == "smith"
    control.decide(
        proposal["job"]["approval_id"], actor="fry", approve=True,
        note="Count sheet checked")
    result = control.run_approved_inventory_count_session(
        proposal["job"]["id"], requested_by="fry")

    assert result["job"]["status"] == "review"
    records = {item["record_id"]: item["data"] for item in result["records"]}
    assert records["PART-A:BIN-1"]["on_hand"] == 8
    assert records["PART-A:BIN-1"]["reserved"] == 2
    assert records["PART-A:BIN-1"]["lot"] == "LOT-1"
    assert records["PART-B:BIN-2"]["serial"] == "SER-001"
    control.complete_job(
        proposal["job"]["id"], actor="quench",
        note="Count evidence, variances, and traceability verified")
    kinds = {item["kind"] for item in control.evidence.list(limit=60)}
    assert {"inventory.count.proposed", "inventory.count.applied",
            "inventory.count.execution_triggered", "job.completed"} <= kinds


def test_count_session_detects_position_change_after_approval():
    control = ControlPlane()
    seed(control, "PART-A", "BIN-1", 10, reserved=2)
    proposal = control.propose_inventory_count_session(
        observations=[observations()[0]], reason="Scheduled count",
        evidence="COUNT-102", requested_by="fry")
    control.upsert_business_record(
        record_type="inventory_position", record_id="PART-A:BIN-1",
        source_system="newer_source", source_revision=1, status="active",
        data={"sku": "PART-A", "location": "BIN-1",
              "on_hand": 9, "reserved": 2},
        provenance={"kind": "later_observation"}, confidence=1.0,
        requested_by="fry")
    control.decide(proposal["job"]["approval_id"], actor="fry", approve=True)
    with pytest.raises(ValueError, match="changed after count"):
        control.run_approved_inventory_count_session(
            proposal["job"]["id"], requested_by="fry")
    assert control.business.get(
        "inventory_position", "PART-A:BIN-1")["data"]["on_hand"] == 9


def test_inventory_count_ui_supports_scanning_preview_and_batch_approval():
    html = Path("orca/static/index.html").read_text()
    script = Path("orca/static/app.js").read_text()
    section = html.split('<section id="inventory" class="view">', 1)[1].split(
        '<section id="engineering"', 1)[0]
    for label in (
        "Physical inventory count", "SKU or barcode", "Counted quantity",
        "Lot", "Serial", "Condition", "Review variances",
        "Request batch approval",
    ):
        assert label in section
    assert "/api/inventory/counts/preview" in script
    assert "inventoryCountRows" in script
    for scanner_feature in ("barcode-scanner-toggle", "barcode-scanner-mode",
                            "acceptBarcodeScan", "findInventoryBarcode"):
        assert scanner_feature in html + script
