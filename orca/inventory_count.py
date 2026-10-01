from __future__ import annotations

from hashlib import sha256
import json
import math
import re
from typing import Any

from .security import redact_text
from .barcodes import normalize_barcode


MAX_COUNT_ROWS = 100
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
CONDITIONS = frozenset({"new", "good", "damaged", "quarantine"})


def _safe_optional(value: object, name: str, maximum: int = 240) -> str:
    if value in {None, ""}:
        return ""
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"inventory count {name} is invalid")
    result = value.strip()
    if redact_text(result) != result:
        raise ValueError(f"inventory count {name} contains secret-shaped data")
    return result


def validate_count_observations(observations: object) -> list[dict[str, Any]]:
    if not isinstance(observations, list) or not 1 <= len(observations) <= MAX_COUNT_ROWS:
        raise ValueError("inventory count requires 1-100 observations")
    normalized = []
    identities: set[tuple[str, str, str, str]] = set()
    serials: set[str] = set()
    allowed = {"sku", "barcode", "location", "counted_quantity", "unit",
               "lot", "serial", "condition", "notes"}
    for raw in observations:
        if not isinstance(raw, dict) or set(raw) - allowed:
            raise ValueError("inventory count observation has an invalid schema")
        barcode = _safe_optional(raw.get("barcode"), "barcode", 128)
        if barcode:
            barcode = normalize_barcode(barcode)["value"]
        sku = raw.get("sku") or barcode
        location = raw.get("location")
        if (not isinstance(sku, str) or not _SAFE_ID.fullmatch(sku.strip())
                or not isinstance(location, str)
                or not _SAFE_ID.fullmatch(location.strip())):
            raise ValueError("inventory count SKU or location is invalid")
        quantity = raw.get("counted_quantity")
        if (isinstance(quantity, bool) or not isinstance(quantity, (int, float))
                or not math.isfinite(quantity) or quantity < 0):
            raise ValueError("inventory counted quantity is invalid")
        condition = raw.get("condition", "good")
        if condition not in CONDITIONS:
            raise ValueError("inventory count condition is invalid")
        lot = _safe_optional(raw.get("lot"), "lot", 128)
        serial = _safe_optional(raw.get("serial"), "serial", 128)
        unit = _safe_optional(raw.get("unit"), "unit", 24) or "ea"
        notes = _safe_optional(raw.get("notes"), "notes", 500)
        identity = (sku.strip(), location.strip(), lot, serial)
        if identity in identities:
            raise ValueError("inventory count contains a duplicate observation")
        identities.add(identity)
        if serial:
            if serial in serials:
                raise ValueError("inventory count contains a duplicate serial number")
            serials.add(serial)
            if quantity != 1:
                raise ValueError("serialized inventory observations must count exactly one unit")
        normalized.append({
            "sku": sku.strip(), "barcode": barcode,
            "location": location.strip(), "counted_quantity": float(quantity),
            "unit": unit, "lot": lot, "serial": serial,
            "condition": condition, "notes": notes,
        })
    return normalized


def build_count_reconciliation(
        observations: object, positions: dict[str, dict[str, Any]],
        *, reason: str, evidence: str) -> dict[str, Any]:
    rows = validate_count_observations(observations)
    reason = _safe_optional(reason, "reason", 500)
    evidence = _safe_optional(evidence, "evidence", 1000)
    if not reason or not evidence:
        raise ValueError("inventory count requires a reason and evidence reference")
    results = []
    for row in rows:
        record_id = f"{row['sku']}:{row['location']}"
        current = positions.get(record_id)
        on_hand = float(current["on_hand"]) if current else 0.0
        reserved = float(current["reserved"]) if current else 0.0
        counted = row["counted_quantity"]
        blocked = counted < reserved
        results.append({
            **row, "record_id": record_id, "recorded_on_hand": on_hand,
            "recorded_reserved": reserved, "variance": counted - on_hand,
            "status": "blocked" if blocked else "match" if counted == on_hand else "variance",
            "blocker": (
                "Count is below reserved quantity; resolve reservations before reconciliation."
                if blocked else ""),
        })
    digest = sha256(json.dumps(
        {"evidence": evidence, "reason": reason, "rows": results},
        sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return {
        "schema": 1, "session_id": f"count-{digest[:16]}",
        "reason": reason, "evidence": evidence, "rows": results,
        "metrics": {
            "observations": len(results),
            "matches": sum(row["status"] == "match" for row in results),
            "variances": sum(row["status"] == "variance" for row in results),
            "blocked": sum(row["status"] == "blocked" for row in results),
            "net_variance": sum(row["variance"] for row in results),
            "serialized": sum(bool(row["serial"]) for row in results),
            "lots": len({row["lot"] for row in results if row["lot"]}),
        },
        "release_state": "blocked" if any(row["status"] == "blocked" for row in results)
        else "approval_required",
    }
