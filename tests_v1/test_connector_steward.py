import sys
from pathlib import Path

repository = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repository / "deploy" / "forge"))
from orca_connector_steward import evaluate


def good_state():
    return {
        "connectors": [
            {"id": "drive", "name": "Google Drive", "writes_enabled": False},
            {"id": "linear", "name": "Linear", "writes_enabled": False},
        ],
        "connector_capabilities": [
            {
                "connector": "drive",
                "operations": ["get", "read"],
                "writes_enabled": False,
                "declared_actions": [
                    {"operation": "read", "level": "R0", "mutates": False},
                    {"operation": "update", "level": "R2", "mutates": True},
                ],
            },
            {
                "connector": "linear",
                "operations": ["list", "search"],
                "writes_enabled": False,
                "declared_actions": [
                    {"operation": "search", "level": "R0", "mutates": False},
                    {"operation": "delete", "level": "R3", "mutates": True},
                ],
            },
        ],
    }


def test_healthy_registry_is_truthful_about_unproven_runtime():
    report = evaluate(good_state(), now=1000)
    assert report["state"] == "healthy"
    assert report["runtime_connectivity"] == "unproven"
    assert all(row["read_path"] == "unproven" for row in report["connectors"])
    assert report["authority"] == "read_only_registry_observer"


def test_missing_matrix_fails_closed():
    report = evaluate({"connectors": []}, now=1000)
    assert report["state"] == "degraded"
    assert report["findings"]


def test_duplicates_writes_and_bad_risk_classification_fail_closed():
    state = good_state()
    state["connectors"].append(dict(state["connectors"][0]))
    state["connector_capabilities"][0]["writes_enabled"] = True
    state["connector_capabilities"][0]["declared_actions"][1]["level"] = "R0"
    report = evaluate(state, now=1000)
    assert report["state"] == "degraded"
    assert any("duplicate" in finding for finding in report["findings"])
    assert any("writes" in finding for finding in report["findings"])
    assert any("classified R0" in finding for finding in report["findings"])
