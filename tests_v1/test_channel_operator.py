import sys
from pathlib import Path

import pytest


repository = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repository / "deploy" / "forge"))
from orca_channel_operator import evaluate, waiting_report


def channel_pack():
    return {
        "allow_external_actions": False,
        "product": {
            "sku": "QV-HAT-001",
            "name": "QuasarVolt Pi 5 Guardian HAT",
            "description": "Synthetic draft listing for acceptance testing only.",
            "unit_cost": "24.00",
            "available_quantity": 12,
        },
        "channels": [
            {
                "channel": "shopify", "currency": "usd", "price": "69.00",
                "fee_percent": "3", "fulfillment_cost": "6.00",
                "draft_order_quantity": 2,
            },
            {
                "channel": "amazon", "currency": "USD", "price": "74.00",
                "fee_percent": "15", "fulfillment_cost": "8.00",
                "draft_order_quantity": 0,
            },
        ],
    }


def test_channel_drafts_have_exact_economics_and_no_live_effects():
    report = evaluate(channel_pack(), now=1000)
    by_channel = {row["channel"]: row for row in report["drafts"]}
    assert report["state"] == "healthy"
    assert by_channel["shopify"]["marketplace_fee"] == 2.07
    assert by_channel["shopify"]["contribution"] == 36.93
    assert by_channel["shopify"]["contribution_margin_percent"] == 53.52
    assert by_channel["amazon"]["marketplace_fee"] == 11.10
    assert by_channel["amazon"]["contribution"] == 30.90
    assert all(row["listing_state"] == "draft_requires_owner_approval"
               for row in report["drafts"])
    assert report["listings_published"] == report["orders_submitted"] == 0
    assert report["external_actions"] == 0


def test_shared_inventory_is_mapped_but_never_reserved():
    report = evaluate(channel_pack(), now=1000)
    assert all(row["shared_available_quantity"] == 12 for row in report["drafts"])
    assert all(row["inventory_reservation"] == "proposal_only_not_applied"
               for row in report["drafts"])
    assert report["inventory_reservations_applied"] == 0


def test_every_consequential_action_requires_approval_and_stays_zero():
    report = evaluate(channel_pack(), now=1000)
    assert set(report["approval_gates"].values()) == {"required"}
    for key in (
        "listings_published", "live_price_changes", "orders_submitted",
        "messages_sent", "refunds_issued", "shipments_created",
        "inventory_reservations_applied", "spend_committed", "external_actions",
    ):
        assert report[key] == 0


def test_unknown_duplicate_and_oversold_channels_fail_closed():
    value = channel_pack()
    value["channels"][0]["channel"] = "unknown-marketplace"
    with pytest.raises(ValueError, match="unsupported"):
        evaluate(value, now=1000)
    value = channel_pack()
    value["channels"][1]["channel"] = "shopify"
    with pytest.raises(ValueError, match="duplicate"):
        evaluate(value, now=1000)
    value = channel_pack()
    value["channels"][0]["draft_order_quantity"] = 13
    with pytest.raises(ValueError, match="exceeds"):
        evaluate(value, now=1000)


def test_invalid_economics_and_external_permission_fail_closed():
    value = channel_pack()
    value["channels"][0]["price"] = float("nan")
    with pytest.raises(ValueError, match="price"):
        evaluate(value, now=1000)
    value = channel_pack()
    value["allow_external_actions"] = True
    with pytest.raises(ValueError, match="external-action boundary"):
        evaluate(value, now=1000)


def test_secret_shaped_listing_text_fails_closed():
    value = channel_pack()
    value["product"]["description"] = "password=not-for-a-listing"
    with pytest.raises(ValueError, match="secret-shaped"):
        evaluate(value, now=1000)


def test_waiting_state_is_truthful_and_inert():
    report = waiting_report(now=1000)
    assert report["state"] == "healthy"
    assert report["mode"] == "waiting_for_approved_channel_pack"
    assert report["drafts"] == []
    assert report["external_actions"] == 0


def test_role_contract_is_active_but_cannot_take_consequential_actions():
    from orca.roles import ROLE_CATALOG

    role = ROLE_CATALOG["channel_operator"]
    assert role.active is True
    assert set(role.authority) == {
        "prepare_listing", "map_inventory", "stage_order", "reconcile_channel"
    }
    assert {
        "publish", "refund", "message_customer", "change_price_live", "spend",
        "ship", "approve",
    } <= set(role.prohibited)
    assert role.activation_gate == "draft_only_multichannel_acceptance_20261001"
