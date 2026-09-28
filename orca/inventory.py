from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess
from typing import Any

from .security import redact


class InventoryReadError(RuntimeError):
    """The bounded inventory read could not be completed."""


def _inventory_number(item: dict, *names: str, default: float | None = None) -> float | None:
    for name in names:
        value = item.get(name)
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0:
            return float(value)
    return default


def _inventory_text(item: dict, *names: str, default: str = "") -> str:
    for name in names:
        value = item.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()[:240]
    return default


def _inventory_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def analyze_inventory_snapshot(
        snapshot: dict[str, Any], *, as_of: datetime | None = None,
        stale_after_days: int = 90) -> dict[str, Any]:
    """Normalize and analyze a read-only inventory snapshot without changing stock."""

    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("items"), list):
        raise ValueError("inventory snapshot must contain an item list")
    if len(snapshot["items"]) > 10_000:
        raise ValueError("inventory item list exceeds the analysis limit")
    if type(stale_after_days) is not int or not 1 <= stale_after_days <= 3650:
        raise ValueError("inventory stale threshold must be 1-3650 days")
    as_of = as_of or datetime.now(timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    as_of = as_of.astimezone(timezone.utc)

    normalized: list[dict[str, Any]] = []
    exceptions: list[dict[str, str]] = []
    sku_counts: dict[str, int] = {}
    total_value = 0.0
    valued_items = 0

    for index, raw in enumerate(snapshot["items"], start=1):
        if not isinstance(raw, dict):
            exceptions.append({
                "severity": "high", "type": "invalid_record",
                "item": f"Record {index}", "detail": "Item is not an object and was skipped.",
            })
            continue
        name = _inventory_text(raw, "name", "label", default=f"Unnamed item {index}")
        sku = _inventory_text(raw, "sku", "part_number", "mpn")
        category = _inventory_text(raw, "category", default="Uncategorized")
        location = _inventory_text(raw, "location", "location_code", default="Unassigned")
        unit = _inventory_text(raw, "unit", default="ea")
        on_hand = _inventory_number(raw, "on_hand", "qty", "quantity")
        reserved = _inventory_number(raw, "reserved", "reserved_qty", default=0.0)
        reorder_point = _inventory_number(
            raw, "reorder_point", "reorderPoint", "minStock", "min_qty", "minimum")
        target_stock = _inventory_number(
            raw, "target_stock", "targetStock", "par_level", "max_qty")
        unit_cost = _inventory_number(raw, "unit_cost", "unitCost", "cost")
        updated_text = _inventory_text(raw, "lastUpdated", "last_updated", "updated_at")
        updated_at = _inventory_timestamp(updated_text)
        lot = _inventory_text(raw, "lot", "lot_number")
        serial = _inventory_text(raw, "serial", "serial_number")

        if on_hand is None:
            on_hand = 0.0
            exceptions.append({
                "severity": "high", "type": "missing_quantity", "item": sku or name,
                "detail": "On-hand quantity is missing or invalid; analysis used zero.",
            })
        if reserved is None:
            reserved = 0.0
            exceptions.append({
                "severity": "high", "type": "invalid_reservation", "item": sku or name,
                "detail": "Reserved quantity is invalid; analysis used zero.",
            })
        available = on_hand - reserved
        if reserved > on_hand:
            exceptions.append({
                "severity": "critical", "type": "over_reserved", "item": sku or name,
                "detail": f"Reserved {reserved:g} exceeds on hand {on_hand:g}.",
            })
        if not sku:
            exceptions.append({
                "severity": "medium", "type": "missing_sku", "item": name,
                "detail": "Stable SKU or part number is missing.",
            })
        else:
            sku_counts[sku.casefold()] = sku_counts.get(sku.casefold(), 0) + 1
        if location == "Unassigned":
            exceptions.append({
                "severity": "medium", "type": "missing_location", "item": sku or name,
                "detail": "Storage location is not assigned.",
            })

        stale = updated_at is None or (as_of - updated_at).days > stale_after_days
        if stale:
            exceptions.append({
                "severity": "low", "type": "stale_or_unknown_count", "item": sku or name,
                "detail": "Count date is missing or older than the configured threshold.",
            })

        raw_status = _inventory_text(raw, "status", default="ok").casefold()
        if available <= 0:
            state = "stockout"
        elif reorder_point is not None and available <= reorder_point:
            state = "reorder"
        elif raw_status not in {"ok", "active", "available", "in stock", "instock"}:
            state = "attention"
        else:
            state = "healthy"
        if state in {"stockout", "reorder", "attention"}:
            exceptions.append({
                "severity": "high" if state == "stockout" else "medium",
                "type": state, "item": sku or name,
                "detail": (
                    f"Available quantity is {available:g}; reorder point is "
                    f"{reorder_point:g}." if reorder_point is not None
                    else f"Available quantity is {available:g}; reorder point is not recorded."
                ),
            })

        reorder_quantity = None
        if state in {"stockout", "reorder"} and target_stock is not None:
            reorder_quantity = max(target_stock - available, 0.0)
        extended_value = None
        if unit_cost is not None:
            extended_value = max(on_hand, 0.0) * unit_cost
            total_value += extended_value
            valued_items += 1
        normalized.append({
            "inventory_id": sku or f"unidentified-{index:05d}",
            "sku": sku, "name": name, "category": category, "location": location,
            "unit": unit, "on_hand": on_hand, "reserved": reserved,
            "available": available, "reorder_point": reorder_point,
            "target_stock": target_stock, "reorder_quantity": reorder_quantity,
            "unit_cost": unit_cost, "extended_value": extended_value,
            "status": state, "source_status": raw_status, "last_updated": updated_text,
            "stale": stale, "lot": lot, "serial": serial,
            "traceable": bool(lot or serial),
        })

    duplicate_skus = {sku for sku, count in sku_counts.items() if count > 1}
    for item in normalized:
        if item["sku"] and item["sku"].casefold() in duplicate_skus:
            exceptions.append({
                "severity": "high", "type": "duplicate_sku", "item": item["sku"],
                "detail": "SKU appears in multiple records; reconcile location or lot identity.",
            })

    locations: dict[str, dict[str, Any]] = {}
    categories: dict[str, dict[str, Any]] = {}
    for item in normalized:
        for key, destination in ((item["location"], locations), (item["category"], categories)):
            row = destination.setdefault(key, {
                "name": key, "items": 0, "on_hand": 0.0, "available": 0.0,
                "needs_attention": 0,
            })
            row["items"] += 1
            row["on_hand"] += item["on_hand"]
            row["available"] += item["available"]
            row["needs_attention"] += item["status"] != "healthy"

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    exceptions.sort(key=lambda row: (
        severity_order[row["severity"]], row["type"], row["item"].casefold()))
    return {
        "schema": 1,
        "generated_at": as_of.isoformat().replace("+00:00", "Z"),
        "source": str(snapshot.get("source") or "inventory snapshot")[:240],
        "read_only": True,
        "stale_after_days": stale_after_days,
        "metrics": {
            "records": len(normalized),
            "unique_skus": len(sku_counts),
            "on_hand": sum(item["on_hand"] for item in normalized),
            "reserved": sum(item["reserved"] for item in normalized),
            "available": sum(item["available"] for item in normalized),
            "stockouts": sum(item["status"] == "stockout" for item in normalized),
            "reorder": sum(item["status"] == "reorder" for item in normalized),
            "attention": sum(item["status"] != "healthy" for item in normalized),
            "stale": sum(item["stale"] for item in normalized),
            "traceable": sum(item["traceable"] for item in normalized),
            "inventory_value": round(total_value, 2),
            "valued_records": valued_items,
        },
        "items": normalized,
        "exceptions": exceptions,
        "locations": sorted(locations.values(), key=lambda row: row["name"].casefold()),
        "categories": sorted(categories.values(), key=lambda row: row["name"].casefold()),
        "controls": {
            "stock_changes": "disabled",
            "reservations": "analysis_only",
            "purchase_orders": "approval_required",
            "supplier_contact": "approval_required",
        },
    }


class InventoryProvider:
    """Read the canonical KILN inventory through one fixed SSH command.

    The provider accepts no caller-controlled command text and exposes no write
    action. Its key and known-hosts files live in ORCA's protected state path.
    """

    def __init__(
        self,
        *,
        key_file: str | Path,
        known_hosts_file: str | Path,
        host: str = "192.168.4.28",
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        timeout_seconds: int = 12,
    ) -> None:
        if host != "192.168.4.28":
            raise ValueError("inventory provider host is not allowlisted")
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 30:
            raise ValueError("inventory timeout must be 1-30 seconds")
        self.key_file = str(key_file)
        self.known_hosts_file = str(known_hosts_file)
        self.host = host
        self.runner = runner
        self.timeout_seconds = timeout_seconds

    def _command(self, action: str) -> list[str]:
        if action not in {"catalog", "list"}:
            raise ValueError("inventory action is not allowlisted")
        return [
            "/usr/bin/ssh",
            "-i", self.key_file,
            "-o", "IdentitiesOnly=yes",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=6",
            "-o", "StrictHostKeyChecking=yes",
            "-o", f"UserKnownHostsFile={self.known_hosts_file}",
            f"fryrocket@{self.host}",
            "/usr/bin/python3",
            "/home/fryrocket/inventory-backend/inventory_cli.py",
            action,
        ]

    def _read_action(self, action: str) -> dict:
        try:
            completed = self.runner(
                self._command(action),
                capture_output=True,
                check=False,
                timeout=self.timeout_seconds,
                env={"PATH": "/usr/bin:/bin"},
            )
        except (OSError, subprocess.SubprocessError):
            raise InventoryReadError("inventory transport failed") from None
        if completed.returncode != 0:
            raise InventoryReadError("inventory source rejected the read")
        raw = completed.stdout
        if not isinstance(raw, bytes) or len(raw) > 1_000_000:
            raise InventoryReadError("inventory response exceeds the size limit")
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise InventoryReadError("inventory response is not valid JSON") from None
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise InventoryReadError("inventory response is not successful")
        return redact(payload)

    def snapshot(self) -> dict:
        catalog = self._read_action("catalog")
        listing = self._read_action("list")
        items = listing.get("items")
        if not isinstance(items, list) or len(items) > 10_000:
            raise InventoryReadError("inventory item list is invalid")
        for key in ("locations", "categories", "units"):
            if not isinstance(catalog.get(key), list):
                raise InventoryReadError("inventory catalog is invalid")
        return {
            "ok": True,
            "source": "KILN canonical bench inventory",
            "read_only": True,
            "items": items,
            "locations": catalog["locations"],
            "categories": catalog["categories"],
            "units": catalog["units"],
        }
