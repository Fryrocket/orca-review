from __future__ import annotations

import math
import re
from typing import Any

from .security import redact_text


OPERATION_TYPES = frozenset({
    "receive", "transfer", "cycle_count", "reserve", "release", "adjustment",
})
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value.strip()):
        raise ValueError(f"inventory workflow {name} is invalid")
    return value.strip()


def _text(value: object, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"inventory workflow {name} is invalid")
    result = value.strip()
    if redact_text(result) != result:
        raise ValueError(f"inventory workflow {name} contains secret-shaped data")
    return result


def validate_inventory_operation(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("inventory workflow must be an object")
    allowed = {
        "operation_type", "sku", "location", "target_location", "quantity",
        "reason", "evidence",
    }
    required = {"operation_type", "sku", "location", "quantity", "reason", "evidence"}
    if not required <= set(value) or set(value) - allowed:
        raise ValueError("inventory workflow has an invalid schema")
    operation_type = value["operation_type"]
    if operation_type not in OPERATION_TYPES:
        raise ValueError("inventory workflow operation type is invalid")
    quantity = value["quantity"]
    if (isinstance(quantity, bool) or not isinstance(quantity, (int, float))
            or not math.isfinite(quantity) or quantity < 0):
        raise ValueError("inventory workflow quantity is invalid")
    if operation_type in {"receive", "transfer", "reserve", "release"} and quantity <= 0:
        raise ValueError("inventory workflow quantity must be positive")
    target_location = value.get("target_location")
    if operation_type == "transfer":
        target_location = _identifier(target_location, "target location")
        if target_location == value["location"]:
            raise ValueError("inventory transfer requires different locations")
    elif target_location not in {None, ""}:
        raise ValueError("target location is only valid for transfers")
    else:
        target_location = None
    return {
        "schema": 1,
        "operation_type": operation_type,
        "sku": _identifier(value["sku"], "SKU"),
        "location": _identifier(value["location"], "location"),
        "target_location": target_location,
        "quantity": float(quantity),
        "reason": _text(value["reason"], "reason", 500),
        "evidence": _text(value["evidence"], "evidence", 1000),
    }


def calculate_inventory_changes(
        operation: dict[str, Any], positions: dict[str, dict[str, float]],
        ) -> dict[str, dict[str, float]]:
    """Return after-state positions for one already validated operation."""

    operation = validate_inventory_operation({
        key: value for key, value in operation.items() if key != "schema"})
    locations = {operation["location"]}
    if operation["target_location"]:
        locations.add(operation["target_location"])
    normalized: dict[str, dict[str, float]] = {}
    for location in locations:
        current = positions.get(location, {"on_hand": 0.0, "reserved": 0.0})
        on_hand = current.get("on_hand")
        reserved = current.get("reserved")
        if any(isinstance(item, bool) or not isinstance(item, (int, float))
               or not math.isfinite(item) or item < 0 for item in (on_hand, reserved)):
            raise ValueError("inventory workflow baseline is invalid")
        if reserved > on_hand:
            raise ValueError("inventory workflow baseline is over-reserved")
        normalized[location] = {
            "on_hand": float(on_hand), "reserved": float(reserved)}

    source = normalized[operation["location"]]
    quantity = operation["quantity"]
    kind = operation["operation_type"]
    if kind == "receive":
        source["on_hand"] += quantity
    elif kind == "reserve":
        if quantity > source["on_hand"] - source["reserved"]:
            raise ValueError("inventory reservation exceeds available stock")
        source["reserved"] += quantity
    elif kind == "release":
        if quantity > source["reserved"]:
            raise ValueError("inventory release exceeds reserved stock")
        source["reserved"] -= quantity
    elif kind in {"cycle_count", "adjustment"}:
        if quantity < source["reserved"]:
            raise ValueError("inventory count cannot fall below reserved stock")
        source["on_hand"] = quantity
    elif kind == "transfer":
        if quantity > source["on_hand"] - source["reserved"]:
            raise ValueError("inventory transfer exceeds available stock")
        source["on_hand"] -= quantity
        normalized[operation["target_location"]]["on_hand"] += quantity
    for row in normalized.values():
        row["available"] = row["on_hand"] - row["reserved"]
    return normalized
