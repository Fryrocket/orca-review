#!/usr/bin/env python3
"""Deterministic, evidence-cited product candidate scorer for ORCA."""

import argparse
import json
import os
import time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import urlparse


MAX_CANDIDATES = 100
MAX_EVIDENCE = 25
ALLOWED_SIGNAL_TYPES = {
    "search_interest", "marketplace_presence", "customer_problem",
    "price_observation", "supplier_quote", "return_risk", "compliance_rule",
}


def _decimal(value, name):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"invalid {name}") from None
    if not result.is_finite():
        raise ValueError(f"invalid {name}")
    return result


def _score(value, name):
    result = _decimal(value, name)
    if result < 0 or result > 100:
        raise ValueError(f"{name} must be between 0 and 100")
    return result


def _money(value, name):
    result = _decimal(value, name)
    if result < 0:
        raise ValueError(f"{name} cannot be negative")
    return result


def _round(value):
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _validate_evidence(rows):
    if not isinstance(rows, list) or not rows or len(rows) > MAX_EVIDENCE:
        raise ValueError("candidate evidence missing or oversized")
    evidence = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("invalid evidence row")
        label = row.get("label")
        url = row.get("url")
        signal_type = row.get("signal_type")
        observed_fact = row.get("observed_fact")
        parsed = urlparse(url or "")
        if not all(isinstance(value, str) and value.strip()
                   for value in (label, url, signal_type, observed_fact)):
            raise ValueError("incomplete evidence row")
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("evidence URL must use HTTPS")
        if signal_type not in ALLOWED_SIGNAL_TYPES:
            raise ValueError("unsupported evidence signal type")
        evidence.append({
            "label": label.strip(), "url": url, "signal_type": signal_type,
            "observed_fact": observed_fact.strip(),
        })
    return evidence


def evaluate(data, now=None):
    now = int(time.time() if now is None else now)
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates or len(candidates) > MAX_CANDIDATES:
        raise ValueError("candidates missing or oversized")
    if data.get("allow_external_actions") is not False:
        raise ValueError("external-action boundary missing")

    ranked = []
    seen = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("invalid candidate")
        candidate_id = candidate.get("id")
        name = candidate.get("name")
        if not all(isinstance(value, str) and value.strip() for value in (candidate_id, name)):
            raise ValueError("invalid candidate identity")
        if candidate_id in seen:
            raise ValueError("duplicate candidate id")
        seen.add(candidate_id)
        if "estimated_sales" in candidate or "sales_forecast" in candidate:
            raise ValueError("unsupported sales estimate supplied")

        evidence = _validate_evidence(candidate.get("evidence"))
        sale_price = _money(candidate.get("sale_price"), "sale_price")
        landed_cost = _money(candidate.get("landed_cost"), "landed_cost")
        fulfillment_cost = _money(candidate.get("fulfillment_cost"), "fulfillment_cost")
        fee_rate = _score(candidate.get("marketplace_fee_percent"), "marketplace_fee_percent")
        demand = _score(candidate.get("demand_score"), "demand_score")
        competition = _score(candidate.get("competition_score"), "competition_score")
        supplier_fit = _score(candidate.get("supplier_fit_score"), "supplier_fit_score")
        compliance_risk = _score(candidate.get("compliance_risk_score"), "compliance_risk_score")
        return_risk = _score(candidate.get("return_risk_score"), "return_risk_score")
        if sale_price <= 0:
            raise ValueError("sale_price must be positive")

        marketplace_fee = sale_price * fee_rate / Decimal(100)
        gross_profit = sale_price - landed_cost - fulfillment_cost - marketplace_fee
        margin_percent = gross_profit * Decimal(100) / sale_price
        composite = (
            demand * Decimal("0.30")
            + (Decimal(100) - competition) * Decimal("0.15")
            + supplier_fit * Decimal("0.20")
            + max(Decimal(0), min(Decimal(100), margin_percent)) * Decimal("0.20")
            + (Decimal(100) - compliance_risk) * Decimal("0.10")
            + (Decimal(100) - return_risk) * Decimal("0.05")
        )
        findings = []
        if gross_profit <= 0:
            findings.append("non_positive_gross_profit")
        if compliance_risk >= 70:
            findings.append("high_compliance_risk")
        if return_risk >= 70:
            findings.append("high_return_risk")
        ranked.append({
            "id": candidate_id, "name": name.strip(),
            "gross_profit": _round(gross_profit),
            "margin_percent": _round(margin_percent),
            "score": _round(composite),
            "evidence": evidence, "findings": findings,
        })

    ranked.sort(key=lambda row: (-row["score"], row["id"]))
    return {
        "schema_version": 1,
        "bot_id": "product_scout",
        "state": "healthy",
        "mode": data.get("mode", "approved_candidate_pack"),
        "observed_epoch": now,
        "authority": "cited_product_research_and_scoring",
        "ranked_candidates": ranked,
        "sales_estimates_created": 0,
        "purchases": 0,
        "vendor_contacts": 0,
        "publications": 0,
        "external_actions": 0,
    }


def waiting_report(now=None):
    return {
        "schema_version": 1, "bot_id": "product_scout", "state": "healthy",
        "mode": "waiting_for_approved_candidate_pack",
        "observed_epoch": int(time.time() if now is None else now),
        "authority": "cited_product_research_and_scoring",
        "ranked_candidates": [], "sales_estimates_created": 0,
        "purchases": 0, "vendor_contacts": 0, "publications": 0,
        "external_actions": 0,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="/var/lib/orca-product-scout-input/input.json")
    parser.add_argument("--output", default="/var/lib/orca-product-scout/status.json")
    args = parser.parse_args()
    try:
        source = Path(args.input)
        report = evaluate(json.loads(source.read_text(encoding="utf-8"))) if source.exists() else waiting_report()
    except (OSError, ValueError, json.JSONDecodeError, TypeError) as exc:
        report = waiting_report()
        report.update({"state": "degraded", "mode": "invalid_candidate_pack", "error": type(exc).__name__})
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
