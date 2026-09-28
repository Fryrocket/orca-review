from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from orca.inventory import (
    InventoryProvider,
    InventoryReadError,
    analyze_inventory_snapshot,
)
from orca.inventory_simulation import run_inventory_simulation


def _runner_for(payloads):
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        action = command[-1]
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps(payloads[action]).encode(), stderr=b""
        )

    return calls, runner


def test_inventory_provider_is_fixed_read_only_and_bounded():
    calls, runner = _runner_for({
        "catalog": {
            "ok": True,
            "locations": [{"code": "BENCH", "label": "Bench"}],
            "categories": ["Parts"],
            "units": ["ea"],
        },
        "list": {
            "ok": True,
            "items": [{"name": "Resistor", "qty": 10, "unit": "ea"}],
        },
    })
    provider = InventoryProvider(
        key_file="/state/key", known_hosts_file="/state/known-hosts",
        runner=runner,
    )
    snapshot = provider.snapshot()
    assert snapshot["read_only"] is True
    assert snapshot["items"][0]["name"] == "Resistor"
    assert [call[0][-1] for call in calls] == ["catalog", "list"]
    assert all(call[0][0] == "/usr/bin/ssh" for call in calls)
    assert all(call[1]["timeout"] == 12 for call in calls)
    with pytest.raises(ValueError, match="not allowlisted"):
        provider._command("submit")


def test_inventory_provider_fails_closed_on_transport_and_shape():
    def rejected(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout=b"", stderr=b"denied")

    provider = InventoryProvider(
        key_file="/state/key", known_hosts_file="/state/known-hosts",
        runner=rejected,
    )
    with pytest.raises(InventoryReadError, match="rejected"):
        provider.snapshot()

    def malformed(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout=b"[]", stderr=b"")

    provider.runner = malformed
    with pytest.raises(InventoryReadError, match="not successful"):
        provider.snapshot()


def test_inventory_provider_rejects_other_hosts_and_bad_timeout():
    with pytest.raises(ValueError, match="not allowlisted"):
        InventoryProvider(key_file="k", known_hosts_file="h", host="example.com")
    with pytest.raises(ValueError, match="timeout"):
        InventoryProvider(key_file="k", known_hosts_file="h", timeout_seconds=31)


def test_inventory_analysis_calculates_availability_reorder_value_and_traceability():
    snapshot = {
        "source": "simulation inventory",
        "items": [
            {
                "sku": "SENSOR-01", "name": "Environmental sensor",
                "category": "Sensors", "location": "BIN-A", "qty": 12,
                "reserved": 4, "minStock": 10, "target_stock": 30,
                "unit_cost": 6.25, "lot": "LOT-100",
                "lastUpdated": "2026-09-20T12:00:00Z", "status": "ok",
            },
            {
                "sku": "MCU-01", "name": "Controller", "category": "ICs",
                "location": "BIN-B", "qty": 0, "reserved": 0,
                "reorder_point": 5, "target_stock": 20, "unit_cost": 8.0,
                "serial": "SER-001", "lastUpdated": "2026-09-21T12:00:00Z",
            },
        ],
    }
    analysis = analyze_inventory_snapshot(
        snapshot, as_of=datetime(2026, 9, 28, tzinfo=timezone.utc))

    assert analysis["read_only"] is True
    assert analysis["metrics"] == {
        "records": 2, "unique_skus": 2, "on_hand": 12.0, "reserved": 4.0,
        "available": 8.0, "stockouts": 1, "reorder": 1, "attention": 2,
        "stale": 0, "traceable": 2, "inventory_value": 75.0,
        "valued_records": 2,
    }
    assert analysis["items"][0]["available"] == 8
    assert analysis["items"][0]["reorder_quantity"] == 22
    assert analysis["items"][1]["status"] == "stockout"
    assert analysis["items"][1]["reorder_quantity"] == 20
    assert analysis["controls"]["stock_changes"] == "disabled"


def test_inventory_analysis_surfaces_identity_reservation_and_freshness_problems():
    snapshot = {"items": [
        {"sku": "DUP-1", "name": "First", "qty": 2, "reserved": 3,
         "lastUpdated": "2025-01-01T00:00:00Z"},
        {"sku": "DUP-1", "name": "Second", "qty": 1},
        {"name": "Unidentified", "qty": "unknown"},
        "not-an-object",
    ]}
    analysis = analyze_inventory_snapshot(
        snapshot, as_of=datetime(2026, 9, 28, tzinfo=timezone.utc))
    types = [item["type"] for item in analysis["exceptions"]]

    assert analysis["metrics"]["records"] == 3
    assert analysis["metrics"]["unique_skus"] == 1
    assert types.count("duplicate_sku") == 2
    assert "over_reserved" in types
    assert "missing_sku" in types
    assert "missing_quantity" in types
    assert "invalid_record" in types
    assert analysis["exceptions"][0]["severity"] == "critical"


def test_inventory_workspace_exposes_control_room_and_uses_analysis_endpoint():
    html = Path("orca/static/index.html").read_text()
    script = Path("orca/static/app.js").read_text()
    section = html.split('<section id="inventory" class="view">', 1)[1].split(
        '<section id="engineering"', 1)[0]

    for label in (
        "INVENTORY CONTROL", "Action queue", "Location health", "Data quality",
        "On hand", "Reserved", "Available", "Reorder",
    ):
        assert label in section
    assert "/api/inventory/analysis" in script
    assert "inventoryAnalysis.exceptions" in script
    assert "inventoryAnalysis.locations" in script


def test_inventory_end_to_end_simulation():
    report = run_inventory_simulation()

    assert report["passed"] is True, report["failed_checks"]
    assert report["checks_passed"] == report["checks_total"]
    assert report["checks_total"] >= 24
    assert report["details"]["external_actions"] == 0
