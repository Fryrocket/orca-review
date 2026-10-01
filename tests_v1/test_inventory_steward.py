import sys
from pathlib import Path

repository = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repository / "deploy" / "forge"))
from orca_inventory_steward import evaluate


def payload(exceptions=None):
    return {
        "snapshot": {"read_only": True},
        "analysis": {
            "read_only": True, "source": "test inventory",
            "metrics": {"records": 1, "on_hand": 25, "reserved": 0, "available": 25,
                        "stockouts": 0, "reorder": 0, "attention": 0},
            "exceptions": exceptions or [],
            "controls": {"stock_changes": "disabled", "reservations": "analysis_only",
                         "purchase_orders": "approval_required", "supplier_contact": "approval_required"},
        },
    }


def test_healthy_inventory_is_observed_without_actions():
    report = evaluate(payload(), now=1000)
    assert report["state"] == "healthy"
    assert report["metrics"]["available"] == 25
    assert report["stock_changes"] == report["orders_placed"] == 0
    assert report["shipments_created"] == report["vendor_contacts"] == 0


def test_high_severity_exception_degrades():
    report = evaluate(payload([{"severity": "high", "type": "stockout", "item": "SKU-1"}]), now=1000)
    assert report["state"] == "degraded"
    assert report["findings"][0]["type"] == "stockout"


def test_write_boundary_change_fails_closed():
    value = payload()
    value["analysis"]["controls"]["stock_changes"] = "enabled"
    try:
        evaluate(value, now=1000)
    except ValueError as exc:
        assert "boundary" in str(exc)
    else:
        raise AssertionError("unsafe control boundary accepted")
