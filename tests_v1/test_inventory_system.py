import pytest
from pathlib import Path

from orca.inventory_system import (
    allocate_channel_stock, build_item_master, calculate_landed_cost,
    calculate_replenishment, explode_bom, inspect_return,
    inventory_document_manifest, inventory_system_blueprint,
    reconcile_receipt, supplier_scorecard,
)


def test_full_inventory_blueprint_has_all_operating_modules():
    result = inventory_system_blueprint()
    assert result["module_count"] == 12
    assert {item["id"] for item in result["modules"]} >= {
        "item_master", "purchasing", "receiving", "bom_builds", "channel_stock",
        "returns", "replenishment", "warehouse", "costing", "quality",
        "documents", "agent_control",
    }
    assert "money" in result["approval_boundaries"]


def test_item_master_normalizes_aliases_and_enforces_targets():
    item = build_item_master({"sku": "MCU-1", "name": "Controller", "unit": "ea",
        "category": "IC", "tracking_policy": "lot", "barcode_aliases": ["B2", "B1", "B1"],
        "reorder_point": 5, "target_stock": 20, "approved": True})
    assert item["barcode_aliases"] == ["B1", "B2"]
    assert item["status"] == "active"
    with pytest.raises(ValueError, match="below reorder"):
        build_item_master({"sku": "X", "name": "X", "unit": "ea", "category": "X",
            "tracking_policy": "none", "reorder_point": 5, "target_stock": 2})


def test_replenishment_is_cash_aware_and_does_not_order():
    result = calculate_replenishment([
        {"sku": "A", "available": 2, "reserved": 1, "daily_demand": 2,
         "lead_time_days": 4, "safety_days": 2, "minimum_order": 10,
         "order_multiple": 5, "unit_cost": 3},
    ], cash_limit=20)
    row = result["recommendations"][0]
    assert row["recommended_quantity"] == 15
    assert row["funded_quantity"] == 5
    assert row["state"] == "cash_constrained"
    assert result["orders_placed"] == 0


def test_receiving_reconciles_shortage_and_damage_without_stock_write():
    result = reconcile_receipt([{"sku": "A", "quantity": 10}],
                               [{"sku": "A", "quantity": 9, "damaged": 1}])
    assert result["rows"][0]["accepted"] == 8
    assert result["exceptions"] == 1
    assert result["stock_changes"] == 0


def test_bom_explosion_finds_shortage_and_build_limit():
    result = explode_bom([
        {"sku": "A", "quantity_per": 2, "scrap_rate": 0},
        {"sku": "B", "quantity_per": 1, "scrap_rate": 0},
    ], 5, {"A": 8, "B": 9})
    assert result["max_buildable"] == 4
    assert result["limiting_component"] == "A"
    assert result["release_state"] == "blocked"


def test_channel_allocation_never_oversells():
    result = allocate_channel_stock({"A": 5}, [
        {"sku": "A", "channel": "Shopify", "quantity": 4},
        {"sku": "A", "channel": "eBay", "quantity": 4},
    ])
    assert [row["granted"] for row in result["allocations"]] == [4, 1]
    assert result["oversold"] is False
    assert result["published"] is False


def test_costing_returns_quality_and_documents_are_governed():
    cost = calculate_landed_cost([{"sku": "A", "quantity": 10, "unit_cost": 2}], 5)
    assert cost["landed_total"] == 25
    assert cost["rows"][0]["landed_unit_cost"] == 2.5
    with pytest.raises(ValueError, match="cannot be directly restocked"):
        inspect_return(sku="A", quantity=1, disposition="restock",
                       safety_related=True, evidence="RMA-1")
    assert supplier_scorecard({"quality": 90, "delivery": 80, "cost": 70,
        "responsiveness": 80, "compliance": 100})["rating"] == "approved"
    manifest = inventory_document_manifest("INV-1")
    assert len(manifest["documents"]) == 6
    assert not any(item["external_write"] for item in manifest["documents"])


def test_inventory_interface_exposes_every_control_room():
    html = Path("orca/static/index.html").read_text()
    script = Path("orca/static/app.js").read_text()
    assert "ORCA INVENTORY OPERATING SYSTEM" in html
    assert "inventory-system-grid" in html
    assert "/api/inventory/system" in script
    assert "data-inventory-module" in script
    assert "stop for my approval" in script
