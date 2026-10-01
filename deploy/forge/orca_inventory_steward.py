#!/usr/bin/env python3
"""Read-only steward for ORCA's canonical inventory analysis."""

import argparse
import json
import os
import time
import urllib.request
from pathlib import Path


def evaluate(payload, now=None):
    now = int(time.time() if now is None else now)
    snapshot = payload.get("snapshot")
    analysis = payload.get("analysis")
    if not isinstance(snapshot, dict) or not isinstance(analysis, dict):
        raise ValueError("inventory analysis envelope invalid")
    if snapshot.get("read_only") is not True or analysis.get("read_only") is not True:
        raise ValueError("inventory source is not read-only")
    metrics = analysis.get("metrics")
    controls = analysis.get("controls")
    exceptions = analysis.get("exceptions")
    if not isinstance(metrics, dict) or not isinstance(controls, dict) or not isinstance(exceptions, list):
        raise ValueError("inventory evidence missing")
    required_controls = {
        "stock_changes": "disabled",
        "reservations": "analysis_only",
        "purchase_orders": "approval_required",
        "supplier_contact": "approval_required",
    }
    if any(controls.get(key) != value for key, value in required_controls.items()):
        raise ValueError("inventory control boundary changed")
    for key in ("records", "on_hand", "reserved", "available", "stockouts", "reorder", "attention"):
        value = metrics.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValueError("inventory metric invalid")
    severity = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    findings = sorted(
        [{"severity": item.get("severity"), "type": item.get("type"), "item": item.get("item")}
         for item in exceptions if isinstance(item, dict)],
        key=lambda item: (severity.get(item["severity"], 9), str(item["type"]), str(item["item"])),
    )
    return {
        "schema_version": 1,
        "bot_id": "inventory_steward",
        "state": "degraded" if any(item["severity"] in {"critical", "high"} for item in findings) else "healthy",
        "observed_epoch": now,
        "authority": "read_only_inventory_observer",
        "source": analysis.get("source"),
        "metrics": {key: metrics[key] for key in (
            "records", "on_hand", "reserved", "available", "stockouts", "reorder", "attention")},
        "findings": findings,
        "stock_changes": 0,
        "orders_placed": 0,
        "shipments_created": 0,
        "vendor_contacts": 0,
    }


def fetch(url, timeout=15):
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise ValueError("inventory endpoint rejected request")
        return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8787/api/inventory/analysis")
    parser.add_argument("--output", default="/var/lib/orca-inventory-steward/status.json")
    args = parser.parse_args()
    try:
        report = evaluate(fetch(args.url))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = {
            "schema_version": 1, "bot_id": "inventory_steward", "state": "degraded",
            "observed_epoch": int(time.time()), "authority": "read_only_inventory_observer",
            "error": type(exc).__name__, "stock_changes": 0, "orders_placed": 0,
            "shipments_created": 0, "vendor_contacts": 0,
        }
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
