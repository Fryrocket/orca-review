from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from .business import BusinessRevisionConflict
from .control_plane import ControlPlane
from .inventory import analyze_inventory_snapshot
from .inventory_system import (
    allocate_channel_stock,
    build_item_master,
    calculate_landed_cost,
    calculate_replenishment,
    explode_bom,
    inspect_return,
    inventory_document_manifest,
    inventory_system_blueprint,
    reconcile_receipt,
    supplier_scorecard,
)


def run_inventory_simulation() -> dict[str, Any]:
    """Exercise inventory analysis and canonical stock controls without external writes."""

    snapshot = {
        "source": "ORCA inventory simulation",
        "read_only": True,
        "items": [
            {"sku": "MCU-ESP32", "name": "ESP32 module", "category": "ICs",
             "location": "BIN-A", "qty": 20, "reserved": 4, "reorder_point": 8,
             "target_stock": 30, "unit_cost": 7.5, "lot": "LOT-100",
             "lastUpdated": "2026-09-25T12:00:00Z", "status": "ok"},
            {"sku": "SENSOR-T", "name": "Temperature sensor", "category": "Sensors",
             "location": "BIN-B", "qty": 7, "reserved": 2, "reorder_point": 6,
             "target_stock": 20, "unit_cost": 2.25,
             "lastUpdated": "2026-09-22T12:00:00Z", "status": "ok"},
            {"sku": "CONN-USB", "name": "USB-C connector", "category": "Connectors",
             "location": "BIN-C", "qty": 0, "reserved": 0, "reorder_point": 10,
             "target_stock": 50, "unit_cost": 0.9,
             "lastUpdated": "2026-09-20T12:00:00Z", "status": "ok"},
            {"sku": "PCB-BLANK", "name": "Copper-clad blank", "category": "PCB",
             "location": "SHELF-1", "qty": 3, "reserved": 5, "unit_cost": 4.0,
             "lastUpdated": "2026-09-18T12:00:00Z", "status": "ok"},
            {"sku": "DUP-LED", "name": "Status LED", "category": "Optical",
             "location": "BIN-D", "qty": 100, "reserved": 0,
             "lastUpdated": "2025-01-01T12:00:00Z", "status": "ok"},
            {"sku": "DUP-LED", "name": "Status LED duplicate", "category": "Optical",
             "location": "BIN-E", "qty": 25, "reserved": 0,
             "lastUpdated": "2026-09-24T12:00:00Z", "status": "ok"},
        ],
    }
    analysis = analyze_inventory_snapshot(
        snapshot, as_of=datetime(2026, 9, 28, tzinfo=timezone.utc))
    checks: dict[str, bool] = {}
    exception_types = [item["type"] for item in analysis["exceptions"]]
    by_sku = {item["sku"]: item for item in analysis["items"] if item["sku"]}
    checks.update({
        "all_records_analyzed": analysis["metrics"]["records"] == 6,
        "availability_calculated": by_sku["MCU-ESP32"]["available"] == 16,
        "reorder_detected": by_sku["SENSOR-T"]["status"] == "reorder",
        "reorder_quantity_calculated": by_sku["SENSOR-T"]["reorder_quantity"] == 15,
        "stockout_detected": by_sku["CONN-USB"]["status"] == "stockout",
        "over_reservation_detected": "over_reserved" in exception_types,
        "duplicate_identity_detected": exception_types.count("duplicate_sku") == 2,
        "stale_count_detected": analysis["metrics"]["stale"] == 1,
        "valuation_is_evidence_bounded": (
            analysis["metrics"]["valued_records"] == 4
            and analysis["metrics"]["inventory_value"] == 177.75),
        "traceability_measured": analysis["metrics"]["traceable"] == 1,
        "write_controls_remain_closed": analysis["controls"] == {
            "stock_changes": "disabled",
            "reservations": "analysis_only",
            "purchase_orders": "approval_required",
            "supplier_contact": "approval_required",
        },
    })

    control = ControlPlane()
    written = control.upsert_business_record(
        record_type="inventory_position", record_id="MCU-ESP32:BIN-A",
        source_system="inventory_simulator", source_revision=1, status="active",
        data={"sku": "MCU-ESP32", "location": "BIN-A", "on_hand": 20, "reserved": 4},
        provenance={"kind": "non_external_simulation"}, confidence=1.0,
        requested_by="orca",
    )
    checks["canonical_position_derives_available"] = (
        written["record"]["data"]["available"] == 16)
    replay = control.upsert_business_record(
        record_type="inventory_position", record_id="MCU-ESP32:BIN-A",
        source_system="inventory_simulator", source_revision=1, status="active",
        data={"sku": "MCU-ESP32", "location": "BIN-A", "on_hand": 20, "reserved": 4},
        provenance={"kind": "non_external_simulation"}, confidence=1.0,
        requested_by="orca",
    )
    checks["identical_source_revision_replays_safely"] = replay["replayed"] is True
    conflict_rejected = False
    try:
        control.upsert_business_record(
            record_type="inventory_position", record_id="MCU-ESP32:BIN-A",
            source_system="inventory_simulator", source_revision=1, status="active",
            data={"sku": "MCU-ESP32", "location": "BIN-A", "on_hand": 19, "reserved": 4},
            provenance={"kind": "non_external_simulation"}, confidence=1.0,
            requested_by="orca",
        )
    except BusinessRevisionConflict:
        conflict_rejected = True
    checks["conflicting_replay_rejected"] = conflict_rejected
    oversell_rejected = False
    try:
        control.upsert_business_record(
            record_type="inventory_position", record_id="CONN-USB:BIN-C",
            source_system="inventory_simulator", source_revision=1, status="active",
            data={"sku": "CONN-USB", "location": "BIN-C", "on_hand": 0, "reserved": 1},
            provenance={"kind": "non_external_simulation"}, confidence=1.0,
            requested_by="orca",
        )
    except ValueError:
        oversell_rejected = True
    checks["oversell_write_rejected"] = oversell_rejected
    proposal = control.propose_inventory_workflow(
        operation={
            "operation_type": "transfer", "sku": "MCU-ESP32",
            "location": "BIN-A", "target_location": "ASSEMBLY",
            "quantity": 3, "reason": "Simulation assembly allocation",
            "evidence": "Simulation work order SIM-100",
        },
        requested_by="fry",
    )
    checks["workflow_waits_for_fry_approval"] = (
        proposal["job"]["status"] == "waiting_approval"
        and proposal["job"]["assigned_to"] == "smith")
    control.decide(
        proposal["job"]["approval_id"], actor="fry", approve=True,
        note="Approve non-external inventory simulation")
    applied = control.run_approved_inventory_workflow(
        proposal["job"]["id"], requested_by="fry")
    applied_by_location = {
        item["data"]["location"]: item["data"] for item in applied["records"]}
    checks["approved_workflow_updates_balanced_positions"] = (
        applied_by_location["BIN-A"]["on_hand"] == 17
        and applied_by_location["ASSEMBLY"]["on_hand"] == 3)
    checks["workflow_routes_to_quench_review"] = (
        applied["job"]["status"] == "review"
        and applied["job"]["reviewer"] == "quench")
    completed = control.complete_job(
        proposal["job"]["id"], actor="quench",
        note="Simulation inventory transfer and audit evidence verified")
    checks["quench_completes_independent_review"] = completed.status.value == "complete"
    count_observations = [{
        "sku": "MCU-ESP32", "barcode": "MCU-ESP32",
        "location": "ASSEMBLY", "counted_quantity": 2, "unit": "ea",
        "lot": "SIM-LOT-1", "serial": "", "condition": "good",
        "notes": "Simulation physical count",
    }]
    count_preview = control.preview_inventory_count_session(
        observations=count_observations, reason="Simulation cycle count",
        evidence="Simulation count sheet SIM-COUNT-1", requested_by="fry")
    checks["count_session_detects_variance"] = (
        count_preview["metrics"]["variances"] == 1
        and count_preview["metrics"]["net_variance"] == -1)
    count_proposal = control.propose_inventory_count_session(
        observations=count_observations, reason="Simulation cycle count",
        evidence="Simulation count sheet SIM-COUNT-1", requested_by="fry")
    checks["count_session_waits_for_approval"] = (
        count_proposal["job"]["status"] == "waiting_approval")
    control.decide(
        count_proposal["job"]["approval_id"], actor="fry", approve=True,
        note="Approve simulated physical count reconciliation")
    count_applied = control.run_approved_inventory_count_session(
        count_proposal["job"]["id"], requested_by="fry")
    checks["count_session_preserves_traceability"] = (
        count_applied["records"][0]["data"]["on_hand"] == 2
        and count_applied["records"][0]["data"]["lot"] == "SIM-LOT-1")
    control.complete_job(
        count_proposal["job"]["id"], actor="quench",
        note="Simulation count variance and traceability verified")
    checks["count_session_quench_review_complete"] = (
        control.jobs[count_proposal["job"]["id"]].status.value == "complete")
    checks["ledger_integrity_valid"] = control.business.verify()

    blueprint = inventory_system_blueprint()
    checks["full_operating_system_present"] = blueprint["module_count"] == 12
    item = build_item_master({
        "sku": "QVP-HAT-1", "name": "QuasarVolt Pi HAT", "unit": "ea",
        "category": "assembled_board", "tracking_policy": "lot",
        "barcode_aliases": ["QVP001", "QVP-HAT-1", "QVP001"],
        "manufacturer": "QuasarVolt Works", "reorder_point": 10,
        "target_stock": 30, "approved": True,
    })
    checks["item_master_controls_identity"] = (
        item["status"] == "active" and len(item["barcode_aliases"]) == 2)
    replenishment = calculate_replenishment([{
        "sku": "MCU-ESP32", "available": 4, "reserved": 2,
        "daily_demand": 2, "lead_time_days": 5, "safety_days": 2,
        "minimum_order": 10, "order_multiple": 5, "unit_cost": 3,
    }], cash_limit=20)
    checks["replenishment_respects_cash"] = (
        replenishment["recommendations"][0]["state"] == "cash_constrained"
        and replenishment["orders_placed"] == 0)
    receipt = reconcile_receipt(
        [{"sku": "MCU-ESP32", "quantity": 10}],
        [{"sku": "MCU-ESP32", "quantity": 9, "damaged": 1}])
    checks["receiving_detects_exceptions"] = (
        receipt["exceptions"] == 1 and receipt["stock_changes"] == 0)
    bom = explode_bom([
        {"sku": "MCU-ESP32", "quantity_per": 1, "scrap_rate": 0},
        {"sku": "CONN-USB", "quantity_per": 2, "scrap_rate": 0},
    ], 5, {"MCU-ESP32": 8, "CONN-USB": 6})
    checks["bom_blocks_short_builds"] = (
        bom["release_state"] == "blocked" and bom["max_buildable"] == 3)
    channels = allocate_channel_stock({"QVP-HAT-1": 5}, [
        {"sku": "QVP-HAT-1", "channel": "Shopify", "quantity": 4},
        {"sku": "QVP-HAT-1", "channel": "eBay", "quantity": 4},
    ])
    checks["channel_stock_prevents_oversell"] = (
        not channels["oversold"] and channels["allocations"][1]["granted"] == 1
        and not channels["published"])
    returns = inspect_return(
        sku="QVP-HAT-1", quantity=1, disposition="quarantine",
        safety_related=True, evidence="SIM-RMA-1")
    checks["returns_enforce_quarantine"] = (
        returns["quarantine_required"] and returns["stock_changes"] == 0)
    costs = calculate_landed_cost(
        [{"sku": "QVP-HAT-1", "quantity": 10, "unit_cost": 8}], 20)
    checks["landed_cost_allocated"] = (
        costs["landed_total"] == 100 and costs["rows"][0]["landed_unit_cost"] == 10)
    scorecard = supplier_scorecard({
        "quality": 90, "delivery": 80, "cost": 70,
        "responsiveness": 80, "compliance": 100})
    checks["supplier_quality_scored"] = scorecard["rating"] == "approved"
    documents = inventory_document_manifest("SIM-INVENTORY-1")
    checks["document_pack_is_draft_only"] = (
        len(documents["documents"]) == 6
        and not any(row["external_write"] for row in documents["documents"]))

    failed = sorted(name for name, passed in checks.items() if not passed)
    return {
        "simulation": "ORCA inventory control end-to-end",
        "passed": not failed,
        "checks_passed": sum(checks.values()),
        "checks_total": len(checks),
        "failed_checks": failed,
        "checks": checks,
        "details": {
            "records": analysis["metrics"]["records"],
            "exceptions": len(analysis["exceptions"]),
            "stockouts": analysis["metrics"]["stockouts"],
            "reorder": analysis["metrics"]["reorder"],
            "canonical_records": control.business.snapshot()["counts"]["inventory_position"],
            "operating_modules": blueprint["module_count"],
            "external_actions": 0,
        },
        "safety": {
            "stock_changes": 0, "purchase_orders": 0, "supplier_contacts": 0,
            "deployments": 0, "external_network_calls": 0,
        },
    }


def main() -> int:
    report = run_inventory_simulation()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
