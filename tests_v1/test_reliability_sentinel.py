import sys
from pathlib import Path

repository = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repository / "deploy" / "ember"))
from reliability_sentinel import evaluate


def healthy_snapshot():
    return {
        "cpu_count": 4,
        "load1": 1.0,
        "memory_available_bytes": 4 * 1024**3,
        "swap_total_bytes": 2 * 1024**3,
        "swap_free_bytes": 2 * 1024**3,
        "disk_used_percent": 42.0,
        "temperature_c": 40.0,
        "orca_health": "healthy",
        "integrity_valid": True,
        "recovery_state": "healthy",
    }


def test_healthy_snapshot_is_read_only_and_accepts_no_actions():
    report = evaluate(healthy_snapshot(), now=1000)
    assert report["state"] == "healthy"
    assert report["authority"] == "read_only_health_observer"
    assert report["actions_taken"] == []
    assert report["findings"] == []


def test_each_safety_threshold_fails_closed():
    snapshot = healthy_snapshot()
    snapshot.update({
        "load1": 8.0,
        "memory_available_bytes": 100 * 1024**2,
        "swap_free_bytes": 0,
        "disk_used_percent": 95,
        "temperature_c": 90,
        "orca_health": "degraded",
        "integrity_valid": False,
        "recovery_state": "degraded",
    })
    report = evaluate(snapshot, now=1000)
    assert report["state"] == "degraded"
    assert len(report["findings"]) == 7
    assert report["actions_taken"] == []


def test_missing_metrics_fail_closed():
    report = evaluate({}, now=1000)
    assert report["state"] == "degraded"
    assert report["findings"]


def test_role_contract_forbids_mutation_and_records_accepted_gate():
    from orca.roles import ROLE_CATALOG

    role = ROLE_CATALOG["reliability_sentinel"]
    assert role.active
    assert role.node_id == "ember"
    assert set(role.authority) == {"observe_health", "detect_anomaly", "stage_alert"}
    assert {"remote_shell", "restart_service", "change_threshold", "approve", "deploy"} <= set(role.prohibited)
    assert role.activation_gate == "read_only_telemetry_and_exception_reporting_accepted_20261001"
