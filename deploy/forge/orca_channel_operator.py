#!/usr/bin/env python3
"""Deterministic draft-only multichannel operator for ORCA."""

import argparse
import json
import os
import time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from orca.security import redact_text


MAX_INPUT_BYTES = 256_000
MAX_CHANNELS = 20
ALLOWED_CHANNELS = {
    "website", "shopify", "amazon", "ebay", "alibaba", "temu", "wholesale",
}


def _decimal(value, name, *, positive=False):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"invalid {name}") from None
    if not result.is_finite() or result < 0 or (positive and result <= 0):
        raise ValueError(f"invalid {name}")
    return result


def _integer(value, name):
    if type(value) is not int or value < 0:
        raise ValueError(f"invalid {name}")
    return value


def _text(value, name, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"invalid {name}")
    cleaned = value.strip()
    if redact_text(cleaned) != cleaned:
        raise ValueError(f"{name} contains secret-shaped data")
    return cleaned


def _money(value):
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def evaluate(data, now=None):
    if not isinstance(data, dict) or set(data) != {
            "allow_external_actions", "product", "channels"}:
        raise ValueError("invalid channel pack schema")
    if data.get("allow_external_actions") is not False:
        raise ValueError("external-action boundary missing")

    product = data.get("product")
    if not isinstance(product, dict) or set(product) != {
            "sku", "name", "description", "unit_cost", "available_quantity"}:
        raise ValueError("invalid product schema")
    sku = _text(product.get("sku"), "sku", 80)
    name = _text(product.get("name"), "product name", 160)
    description = _text(product.get("description"), "description", 2_000)
    unit_cost = _decimal(product.get("unit_cost"), "unit cost")
    available = _integer(product.get("available_quantity"), "available quantity")

    channels = data.get("channels")
    if not isinstance(channels, list) or not channels or len(channels) > MAX_CHANNELS:
        raise ValueError("channels missing or oversized")
    drafts = []
    seen = set()
    for row in channels:
        if not isinstance(row, dict) or set(row) != {
                "channel", "currency", "price", "fee_percent", "fulfillment_cost",
                "draft_order_quantity"}:
            raise ValueError("invalid channel row")
        channel = row.get("channel")
        if channel not in ALLOWED_CHANNELS:
            raise ValueError("unsupported channel")
        if channel in seen:
            raise ValueError("duplicate channel")
        seen.add(channel)
        currency = _text(row.get("currency"), "currency", 3).upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError("invalid currency")
        price = _decimal(row.get("price"), "price", positive=True)
        fee_percent = _decimal(row.get("fee_percent"), "fee percent")
        if fee_percent > 100:
            raise ValueError("invalid fee percent")
        fulfillment = _decimal(row.get("fulfillment_cost"), "fulfillment cost")
        draft_quantity = _integer(row.get("draft_order_quantity"), "draft order quantity")
        if draft_quantity > available:
            raise ValueError("draft order exceeds shared availability")

        fees = price * fee_percent / Decimal(100)
        contribution = price - unit_cost - fulfillment - fees
        margin = contribution * Decimal(100) / price
        drafts.append({
            "channel": channel,
            "sku": sku,
            "currency": currency,
            "title": name,
            "description": description,
            "price": _money(price),
            "marketplace_fee": _money(fees),
            "contribution": _money(contribution),
            "contribution_margin_percent": _money(margin),
            "shared_available_quantity": available,
            "draft_order_quantity": draft_quantity,
            "inventory_reservation": "proposal_only_not_applied",
            "listing_state": "draft_requires_owner_approval",
            "order_state": "draft_requires_owner_approval" if draft_quantity else "not_requested",
            "findings": ["non_positive_contribution"] if contribution <= 0 else [],
        })

    return {
        "schema_version": 1,
        "bot_id": "channel_operator",
        "state": "healthy",
        "mode": "approved_channel_pack_drafts",
        "observed_epoch": int(time.time() if now is None else now),
        "authority": "draft_listing_order_and_channel_reconciliation",
        "drafts": drafts,
        "approval_gates": {
            "publish_listing": "required",
            "change_live_price": "required",
            "submit_order": "required",
            "message_customer": "required",
            "refund": "required",
            "ship": "required",
            "spend": "required",
        },
        "listings_published": 0,
        "live_price_changes": 0,
        "orders_submitted": 0,
        "messages_sent": 0,
        "refunds_issued": 0,
        "shipments_created": 0,
        "inventory_reservations_applied": 0,
        "spend_committed": 0,
        "external_actions": 0,
    }


def waiting_report(now=None):
    report = {
        "schema_version": 1,
        "bot_id": "channel_operator",
        "state": "healthy",
        "mode": "waiting_for_approved_channel_pack",
        "observed_epoch": int(time.time() if now is None else now),
        "authority": "draft_listing_order_and_channel_reconciliation",
        "drafts": [],
        "approval_gates": {},
    }
    for key in (
        "listings_published", "live_price_changes", "orders_submitted",
        "messages_sent", "refunds_issued", "shipments_created",
        "inventory_reservations_applied", "spend_committed", "external_actions",
    ):
        report[key] = 0
    return report


def _read_input(path):
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("approved channel pack is oversized")
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="/var/lib/orca-channel-input/approved-pack.json")
    parser.add_argument("--output", default="/var/lib/orca-channel-operator/status.json")
    args = parser.parse_args()
    try:
        source = Path(args.input)
        report = evaluate(_read_input(source)) if source.exists() else waiting_report()
    except (OSError, ValueError, json.JSONDecodeError, TypeError) as exc:
        report = waiting_report()
        report.update({
            "state": "degraded",
            "mode": "invalid_approved_channel_pack",
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
