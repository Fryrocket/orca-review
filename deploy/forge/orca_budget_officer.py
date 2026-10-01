#!/usr/bin/env python3
"""Deterministic, read-only budgeting and runway calculator."""

import argparse
import json
import os
import time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path


CENT = Decimal("0.01")


def money(value):
    try:
        result = Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise ValueError("invalid monetary value")
    if not result.is_finite():
        raise ValueError("invalid monetary value")
    return result


def evaluate(data, now=None):
    now = int(time.time() if now is None else now)
    categories = data.get("categories")
    if not isinstance(categories, list) or not categories:
        raise ValueError("budget categories missing")
    rows = []
    total_budget = Decimal("0")
    total_actual = Decimal("0")
    for item in categories:
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("invalid category")
        budget = money(item.get("budget"))
        actual = money(item.get("actual"))
        if budget < 0 or actual < 0:
            raise ValueError("negative monetary value")
        variance = budget - actual
        rows.append({"name": name, "budget": str(budget), "actual": str(actual),
                     "variance": str(variance), "over_budget": variance < 0})
        total_budget += budget
        total_actual += actual
    cash = money(data.get("cash_on_hand", 0))
    monthly_burn = money(data.get("monthly_burn", 0))
    if cash < 0 or monthly_burn < 0:
        raise ValueError("negative runway input")
    runway = None if monthly_burn == 0 else (cash / monthly_burn).quantize(CENT, rounding=ROUND_HALF_UP)
    return {
        "schema_version": 1,
        "bot_id": "budget_officer",
        "state": "healthy",
        "mode": data.get("mode", "approved_summary"),
        "observed_epoch": now,
        "authority": "read_only_financial_calculator",
        "currency": data.get("currency", "USD"),
        "categories": rows,
        "total_budget": str(total_budget.quantize(CENT)),
        "total_actual": str(total_actual.quantize(CENT)),
        "total_variance": str((total_budget - total_actual).quantize(CENT)),
        "runway_months": None if runway is None else str(runway),
        "money_moved": False,
        "external_actions": False,
    }


def waiting_report(now=None):
    return {
        "schema_version": 1, "bot_id": "budget_officer", "state": "healthy",
        "mode": "waiting_for_approved_financial_summary",
        "observed_epoch": int(time.time() if now is None else now),
        "authority": "read_only_financial_calculator", "money_moved": False,
        "external_actions": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="/var/lib/orca-budget-input/input.json")
    parser.add_argument("--output", default="/var/lib/orca-budget-officer/status.json")
    args = parser.parse_args()
    try:
        source = Path(args.input)
        report = evaluate(json.loads(source.read_text(encoding="utf-8"))) if source.exists() else waiting_report()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = waiting_report()
        report.update({"state": "degraded", "mode": "invalid_financial_summary",
                       "error": type(exc).__name__})
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
