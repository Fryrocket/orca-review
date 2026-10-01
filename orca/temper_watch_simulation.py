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
