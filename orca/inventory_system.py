from __future__ import annotations

from hashlib import sha256
import json
import math
from typing import Any


INVENTORY_MODULES = (
    ("item_master", "Item master", "Identity, barcode, manufacturer, MPN, unit, tracking and compliance"),
    ("purchasing", "Purchasing", "Demand, supplier comparison, draft purchase orders and approvals"),
    ("receiving", "Receiving", "PO matching, shortages, damage, lots, serials and quarantine"),
    ("bom_builds", "BOM & builds", "Material explosion, reservations, issues, completions and scrap"),
    ("channel_stock", "Channel stock", "Shared availability and protected marketplace reservations"),
    ("returns", "Returns & RMA", "Inspection, repair, restock, quarantine and supplier claims"),
    ("replenishment", "Replenishment", "Lead time, safety stock, days of supply and cash-aware buying"),
    ("warehouse", "Warehouse", "Bins, labels, cycle counts, pick lists and packing lists"),
    ("costing", "Cost accounting", "Landed cost, labor, duty, valuation and product contribution"),
    ("quality", "Quality", "Inspection plans, defects, recalls, counterfeit risk and supplier scorecards"),
    ("documents", "Documents", "POs, receipts, variances, valuation and audit-ready exports"),
    ("agent_control", "Agent control", "Objectives, evidence, approvals, execution, verification and rollback"),
)

DISPOSITIONS = frozenset({"restock", "repair", "quarantine", "scrap", "supplier_claim"})


def _number(value: object, name: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise ValueError(f"{name} is outside its allowed range")
    return result


def _text(value: object, name: str, maximum: int = 128) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError(f"{name} is invalid")
    return value.strip()


def build_item_master(item: dict[str, Any]) -> dict[str, Any]:
    required = {"sku", "name", "unit", "category", "tracking_policy"}
    if not isinstance(item, dict) or not required <= set(item):
        raise ValueError("item master record is incomplete")
    tracking = item["tracking_policy"]
    if tracking not in {"none", "lot", "serial"}:
        raise ValueError("item tracking policy is invalid")
    aliases = item.get("barcode_aliases", [])
    if not isinstance(aliases, list) or any(not isinstance(value, str) or not value.strip() for value in aliases):
        raise ValueError("barcode aliases are invalid")
    aliases = sorted(set(value.strip() for value in aliases))
    result = {
        "sku": _text(item["sku"], "sku"),
        "name": _text(item["name"], "item name", 240),
        "unit": _text(item["unit"], "unit", 24),
        "category": _text(item["category"], "category", 80),
        "tracking_policy": tracking,
        "barcode_aliases": aliases,
        "manufacturer": str(item.get("manufacturer", "")).strip(),
        "manufacturer_part_number": str(item.get("manufacturer_part_number", "")).strip(),
        "preferred_supplier": str(item.get("preferred_supplier", "")).strip(),
        "reorder_point": _number(item.get("reorder_point", 0), "reorder point"),
        "target_stock": _number(item.get("target_stock", 0), "target stock"),
        "compliance_documents": sorted(set(item.get("compliance_documents", []))),
        "status": "active" if item.get("approved", False) else "draft",
    }
    if result["target_stock"] and result["target_stock"] < result["reorder_point"]:
        raise ValueError("target stock cannot be below reorder point")
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":"))
    result["record_id"] = f"item-{sha256(encoded.encode()).hexdigest()[:16]}"
    return result


def calculate_replenishment(items: list[dict[str, Any]], *, cash_limit: float) -> dict[str, Any]:
    remaining = _number(cash_limit, "cash limit")
    recommendations = []
    for raw in items:
        sku = _text(raw.get("sku"), "sku")
        available = _number(raw.get("available", 0), "available")
        reserved = _number(raw.get("reserved", 0), "reserved")
        daily_demand = _number(raw.get("daily_demand", 0), "daily demand")
        lead_days = _number(raw.get("lead_time_days", 0), "lead time")
        safety_days = _number(raw.get("safety_days", 0), "safety days")
        minimum = _number(raw.get("minimum_order", 0), "minimum order")
        pack = _number(raw.get("order_multiple", 1), "order multiple", minimum=0.000001)
        unit_cost = _number(raw.get("unit_cost", 0), "unit cost")
        target = daily_demand * (lead_days + safety_days)
        raw_quantity = max(0.0, target + reserved - available)
        quantity = math.ceil(raw_quantity / pack) * pack if raw_quantity else 0.0
        if 0 < quantity < minimum:
            quantity = minimum
        requested_cost = quantity * unit_cost
        funded_quantity = quantity
        state = "recommended" if quantity else "healthy"
        if requested_cost > remaining and unit_cost:
            funded_quantity = math.floor(remaining / unit_cost / pack) * pack
            state = "cash_constrained"
        funded_cost = funded_quantity * unit_cost
        remaining -= funded_cost
        recommendations.append({
            "sku": sku, "available": available, "target_stock": target,
            "recommended_quantity": quantity, "funded_quantity": funded_quantity,
            "estimated_cost": round(funded_cost, 2), "state": state,
            "days_of_supply": None if not daily_demand else round(available / daily_demand, 2),
            "approval_required": funded_quantity > 0,
        })
    return {"recommendations": recommendations, "cash_limit": cash_limit,
            "cash_remaining": round(remaining, 2), "orders_placed": 0}


def reconcile_receipt(purchase_lines: list[dict[str, Any]], receipts: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = {}
    for line in purchase_lines:
        key = _text(line.get("sku"), "sku")
        ordered[key] = ordered.get(key, 0.0) + _number(line.get("quantity"), "ordered quantity")
    received = {}
    damaged = {}
    for row in receipts:
        key = _text(row.get("sku"), "sku")
        received[key] = received.get(key, 0.0) + _number(row.get("quantity"), "received quantity")
        damaged[key] = damaged.get(key, 0.0) + _number(row.get("damaged", 0), "damaged quantity")
    rows = []
    for sku in sorted(set(ordered) | set(received)):
        expected, actual, bad = ordered.get(sku, 0.0), received.get(sku, 0.0), damaged.get(sku, 0.0)
        if bad > actual:
            raise ValueError("damaged quantity exceeds received quantity")
        variance = actual - expected
        state = "match" if variance == 0 and bad == 0 else "exception"
        rows.append({"sku": sku, "ordered": expected, "received": actual,
                     "damaged": bad, "accepted": actual - bad,
                     "variance": variance, "state": state})
    return {"rows": rows, "exceptions": sum(row["state"] == "exception" for row in rows),
            "stock_changes": 0, "release_state": "approval_required"}


def explode_bom(bom: list[dict[str, Any]], build_quantity: float,
                availability: dict[str, float]) -> dict[str, Any]:
    build_quantity = _number(build_quantity, "build quantity", minimum=0.000001)
    requirements, limiting = [], None
    possible = math.inf
    for line in bom:
        sku = _text(line.get("sku"), "sku")
        per = _number(line.get("quantity_per"), "quantity per", minimum=0.000001)
        scrap = _number(line.get("scrap_rate", 0), "scrap rate")
        if scrap >= 1:
            raise ValueError("scrap rate must be below one")
        needed = math.ceil(per * build_quantity / (1 - scrap))
        have = _number(availability.get(sku, 0), "available")
        shortage = max(0.0, needed - have)
        line_possible = math.floor(have * (1 - scrap) / per)
        if line_possible < possible:
            possible, limiting = line_possible, sku
        requirements.append({"sku": sku, "required": needed, "available": have,
                             "shortage": shortage, "reservation_created": False})
    return {"build_quantity": build_quantity, "requirements": requirements,
            "max_buildable": 0 if possible is math.inf else possible,
            "limiting_component": limiting,
            "release_state": "blocked" if any(row["shortage"] for row in requirements) else "approval_required"}


def allocate_channel_stock(available: dict[str, float], requests: list[dict[str, Any]]) -> dict[str, Any]:
    remaining = {sku: _number(value, "available") for sku, value in available.items()}
    allocations = []
    for request in requests:
        sku = _text(request.get("sku"), "sku")
        channel = _text(request.get("channel"), "channel", 80)
        requested = _number(request.get("quantity"), "reservation quantity")
        granted = min(requested, remaining.get(sku, 0.0))
        remaining[sku] = remaining.get(sku, 0.0) - granted
        allocations.append({"sku": sku, "channel": channel, "requested": requested,
                            "granted": granted, "backordered": requested - granted})
    return {"allocations": allocations, "remaining": remaining,
            "oversold": any(value < 0 for value in remaining.values()), "published": False}


def calculate_landed_cost(lines: list[dict[str, Any]], shared_costs: float) -> dict[str, Any]:
    shared = _number(shared_costs, "shared costs")
    prepared, base_total = [], 0.0
    for line in lines:
        sku = _text(line.get("sku"), "sku")
        quantity = _number(line.get("quantity"), "quantity", minimum=0.000001)
        unit_cost = _number(line.get("unit_cost"), "unit cost")
        base = quantity * unit_cost
        prepared.append({"sku": sku, "quantity": quantity, "base": base})
        base_total += base
    if not base_total and shared:
        raise ValueError("shared costs require nonzero item value")
    rows = []
    for line in prepared:
        allocation = shared * line["base"] / base_total if base_total else 0.0
        rows.append({"sku": line["sku"], "quantity": line["quantity"],
                     "allocated_shared_cost": round(allocation, 2),
                     "landed_unit_cost": round((line["base"] + allocation) / line["quantity"], 4)})
    return {"rows": rows, "base_total": round(base_total, 2),
            "shared_costs": round(shared, 2), "landed_total": round(base_total + shared, 2)}


def inspect_return(*, sku: str, quantity: float, disposition: str,
                   safety_related: bool, evidence: str) -> dict[str, Any]:
    if disposition not in DISPOSITIONS:
        raise ValueError("return disposition is invalid")
    result = {"sku": _text(sku, "sku"), "quantity": _number(quantity, "return quantity", minimum=0.000001),
              "disposition": disposition, "evidence": _text(evidence, "return evidence", 1000),
              "restock_quantity": quantity if disposition == "restock" else 0,
              "quarantine_required": safety_related or disposition == "quarantine",
              "stock_changes": 0, "approval_required": True}
    if safety_related and disposition == "restock":
        raise ValueError("safety-related returns cannot be directly restocked")
    return result


def supplier_scorecard(metrics: dict[str, float]) -> dict[str, Any]:
    weights = {"quality": .35, "delivery": .25, "cost": .15, "responsiveness": .10,
               "compliance": .15}
    scores = {name: _number(metrics.get(name), name) for name in weights}
    if any(value > 100 for value in scores.values()):
        raise ValueError("supplier metrics cannot exceed 100")
    total = round(sum(scores[name] * weight for name, weight in weights.items()), 2)
    return {"score": total, "rating": "approved" if total >= 80 else "conditional" if total >= 60 else "blocked",
            "metrics": scores, "evidence_required": True}


def inventory_document_manifest(reference: str) -> dict[str, Any]:
    reference = _text(reference, "document reference")
    documents = [
        ("purchase_order", "LibreOffice Writer", "Drive/Purchasing"),
        ("receiving_report", "LibreOffice Writer", "Drive/Inventory/Receiving"),
        ("inventory_valuation", "LibreOffice Calc", "Drive/Finance/Inventory"),
        ("variance_report", "LibreOffice Calc", "Drive/Inventory/Counts"),
        ("quality_report", "LibreOffice Writer", "Drive/Quality"),
        ("pick_pack_packet", "LibreOffice Writer", "Drive/Fulfillment"),
    ]
    return {"reference": reference, "documents": [
        {"document_type": kind, "application": app, "destination": destination,
         "state": "draft", "external_write": False} for kind, app, destination in documents
    ]}


def inventory_system_blueprint() -> dict[str, Any]:
    modules = [{"id": module_id, "name": name, "purpose": purpose,
                "state": "implemented", "mode": "agentic_with_approval"}
               for module_id, name, purpose in INVENTORY_MODULES]
    return {
        "name": "ORCA Inventory Operating System", "version": 1,
        "modules": modules, "module_count": len(modules),
        "agent_loop": ["inspect", "reconcile", "plan", "simulate", "request_approval",
                       "execute", "verify", "record", "monitor"],
        "approval_boundaries": ["stock changes", "purchase orders", "supplier messages",
                                "customer refunds", "marketplace publishing", "write-offs",
                                "recalls", "money", "external document writes"],
        "systems": ["ORCA ledger", "KILN inventory", "Google Drive", "Notion",
                    "LibreOffice", "ERPNext staging", "sales channels"],
    }
