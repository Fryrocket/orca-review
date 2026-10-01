#!/usr/bin/env python3
"""Bounded Product Development Lead worker for approved ORCA briefs."""

import argparse
import json
import os
import time
from pathlib import Path

from orca.product_development import build_product_development_plan


MAX_INPUT_BYTES = 256_000
MAX_INVENTORY_ITEMS = 500


def evaluate(data, now=None):
    if not isinstance(data, dict) or set(data) - {
            "allow_external_actions", "brief", "inventory"}:
        raise ValueError("invalid approved product brief schema")
    if data.get("allow_external_actions") is not False:
        raise ValueError("external-action boundary missing")
    brief = data.get("brief")
    if not isinstance(brief, str):
        raise ValueError("product brief missing")

    inventory = data.get("inventory")
    if inventory is not None:
        if not isinstance(inventory, dict) or set(inventory) != {"items"}:
            raise ValueError("inventory snapshot has an invalid schema")
        items = inventory.get("items")
        if not isinstance(items, list) or len(items) > MAX_INVENTORY_ITEMS:
            raise ValueError("inventory snapshot is oversized")
        if not all(isinstance(item, dict) for item in items):
            raise ValueError("inventory snapshot contains an invalid item")

    plan = build_product_development_plan(brief, inventory)
    if plan["maturity"] != "concept" or plan["release_state"] != "not_released":
        raise ValueError("product plan crossed the release boundary")
    if plan["inventory"]["matched_items"]:
        raise ValueError("product plan allocated inventory")

    return {
        "schema_version": 1,
        "bot_id": "product_development_lead",
        "state": "healthy",
        "mode": "approved_brief_plan",
        "observed_epoch": int(time.time() if now is None else now),
        "authority": "unreleased_product_planning_and_review_coordination",
        "plan": plan,
        "purchases": 0,
        "supplier_contacts": 0,
        "inventory_allocations": 0,
        "manufacturing_releases": 0,
        "deployments": 0,
        "external_actions": 0,
    }


def waiting_report(now=None):
    return {
        "schema_version": 1,
        "bot_id": "product_development_lead",
        "state": "healthy",
        "mode": "waiting_for_approved_product_brief",
        "observed_epoch": int(time.time() if now is None else now),
        "authority": "unreleased_product_planning_and_review_coordination",
        "plan": None,
        "purchases": 0,
        "supplier_contacts": 0,
        "inventory_allocations": 0,
        "manufacturing_releases": 0,
        "deployments": 0,
        "external_actions": 0,
    }


def _read_input(path):
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("approved product brief is oversized")
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default="/var/lib/orca-product-development-input/approved-brief.json",
    )
    parser.add_argument(
        "--output",
        default="/var/lib/orca-product-development-lead/status.json",
    )
    args = parser.parse_args()
    try:
        source = Path(args.input)
        report = evaluate(_read_input(source)) if source.exists() else waiting_report()
    except (OSError, ValueError, json.JSONDecodeError, TypeError) as exc:
        report = waiting_report()
        report.update({
            "state": "degraded",
            "mode": "invalid_approved_product_brief",
            "error": type(exc).__name__,
        })

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
