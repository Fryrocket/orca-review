import sys
from pathlib import Path

repository = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repository / "deploy" / "forge"))
from orca_budget_officer import evaluate, waiting_report


def test_budget_variance_and_runway_are_deterministic():
    report = evaluate({
        "currency": "USD", "cash_on_hand": "1000.00", "monthly_burn": "250.00",
        "categories": [
            {"name": "hosting", "budget": "100.00", "actual": "80.25"},
            {"name": "models", "budget": "50.00", "actual": "60.00"},
        ],
    }, now=1000)
    assert report["total_variance"] == "9.75"
    assert report["runway_months"] == "4.00"
    assert report["categories"][1]["over_budget"] is True
    assert report["money_moved"] is False


def test_invalid_or_negative_values_fail_closed():
    for value in ("nan", "-1", "bad"):
        try:
            evaluate({"categories": [{"name": "x", "budget": value, "actual": 0}]})
        except ValueError:
            pass
        else:
            raise AssertionError("invalid value accepted")


def test_waiting_mode_is_truthful_and_non_mutating():
    report = waiting_report(now=1000)
    assert report["mode"] == "waiting_for_approved_financial_summary"
    assert report["money_moved"] is False
    assert report["external_actions"] is False
