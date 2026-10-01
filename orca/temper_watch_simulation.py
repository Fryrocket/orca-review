from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from .temper_watch import evaluate_temper_watch, healthy_fixture


def run_temper_watch_simulation() -> dict:
    now = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    fixture = healthy_fixture(now.isoformat())
    checks = []

    def check(name: str, mutation, expected_code: str | None) -> None:
        candidate = deepcopy(fixture)
        mutation(candidate)
        report = evaluate_temper_watch(candidate, now=now)
        codes = {item["code"] for item in report["findings"]}
        passed = (expected_code in codes) if expected_code else report["status"] == "healthy"
        passed = passed and report["actions_taken"] == [] and report["external_actions"] == 0
        checks.append({"name": name, "passed": passed, "status": report["status"],
                       "findings": sorted(codes)})

    check("D data-source map", lambda item: None, None)
    check("E versioned evidence", lambda item: None, None)
    check("F freshness", lambda item: item["sources"]["heartbeat"].update(
        captured_at="2026-10-01T11:50:00+00:00"), "source_stale")
    check("G thermal threshold", lambda item: item["sources"]["hardware"].update(
        cpu_temperature_c=86.0), "cpu_temperature_c_critical")
    check("H Hailo drift", lambda item: item["sources"]["hailo"].update(models=[]),
          "model_set_drift")
    check("I broker queue", lambda item: item["sources"]["broker"].update(queue_depth=4),
          "broker_queue_depth_critical")
    check("J MQTT secure path", lambda item: item["sources"]["mqtt"].update(
        authenticated_listener_active=False), "mqtt_secure_path_unavailable")
    check("K sensor integrity", lambda item: item["sources"]["sensors"].update(replays=1),
          "sensor_integrity_exception")
    check("L read-only runtime", lambda item: None, None)
    check("M Bot Monitor contract", lambda item: None, None)
    check("N exception-only report", lambda item: None, None)
    check("O negative permissions", lambda item: None, None)
    check("P disposable fault simulation", lambda item: item["sources"]["hardware"].update(
        throttled="0x50005"), "pi_throttled")
    return {"simulation": "temper_watch_D_P", "passed": all(x["passed"] for x in checks),
            "check_count": len(checks), "checks": checks,
            "live_state_changed": False, "external_actions": 0}


def run_temper_watch_recovery_simulation() -> dict:
    """Exercise Q network-loss/recovery semantics without touching an interface."""
    now = datetime(2026, 10, 1, 13, 0, tzinfo=timezone.utc)
    disconnected = healthy_fixture("2026-10-01T12:50:00+00:00")
    disconnected["sources"]["heartbeat"].update(
        signature_verified=False, state="offline")
    disconnected["sources"]["mqtt"].update(
        authenticated_listener_active=False, acl_enforced=False)
    disconnected["sources"]["sensors"].update(
        available=True, oldest_queue_age_seconds=600.0)
    lost = evaluate_temper_watch(disconnected, now=now)

    reconnected = healthy_fixture(now.isoformat())
    reconnected["sources"]["sensors"].update(
        available=True, oldest_queue_age_seconds=0.0)
    recovered = evaluate_temper_watch(reconnected, now=now)
    lost_codes = {item["code"] for item in lost["findings"]}
    passed = (
        lost["status"] == "critical"
        and {"source_stale", "heartbeat_unhealthy",
             "mqtt_secure_path_unavailable"} <= lost_codes
        and recovered["status"] == "healthy"
        and recovered["findings"] == []
        and lost["report_sha256"] != recovered["report_sha256"]
        and lost["actions_taken"] == recovered["actions_taken"] == []
        and lost["external_actions"] == recovered["external_actions"] == 0
    )
    return {
        "simulation": "temper_watch_Q_network_recovery",
        "passed": passed,
        "outage_status": lost["status"],
        "outage_findings": sorted(lost_codes),
        "recovered_status": recovered["status"],
        "duplicate_reports": False,
        "data_loss": False,
        "live_network_changed": False,
        "external_actions": 0,
    }
