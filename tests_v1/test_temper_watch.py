from copy import deepcopy
from datetime import datetime, timezone

import pytest

from orca.temper_watch import (ACCEPTED_MODELS, PROHIBITED,
                               evaluate_temper_watch, healthy_fixture)
from orca.temper_watch_simulation import run_temper_watch_simulation


NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def fixture():
    return healthy_fixture(NOW.isoformat())


def test_healthy_report_is_hashed_read_only_and_exception_free():
    report = evaluate_temper_watch(fixture(), now=NOW)
    assert report["status"] == "healthy"
    assert report["findings"] == []
    assert report["actions_taken"] == [] and report["external_actions"] == 0
    assert len(report["observation_sha256"]) == len(report["report_sha256"]) == 64
    assert {"publish_mqtt", "remote_shell", "deploy"} <= set(report["prohibited"])


@pytest.mark.parametrize(("source", "field", "value", "code"), [
    ("hardware", "cpu_temperature_c", 86.0, "cpu_temperature_c_critical"),
    ("hardware", "disk_percent", 91.0, "disk_percent_critical"),
    ("broker", "queue_depth", 4, "broker_queue_depth_critical"),
    ("sensors", "oldest_queue_age_seconds", 901, "sensor_queue_age_seconds_critical"),
])
def test_resource_and_queue_thresholds(source, field, value, code):
    item = fixture(); item["sources"][source][field] = value
    report = evaluate_temper_watch(item, now=NOW)
    assert code in {finding["code"] for finding in report["findings"]}
    assert report["actions_taken"] == []


def test_stale_signed_heartbeat_and_hailo_drift_fail_closed():
    item = fixture()
    item["sources"]["heartbeat"]["captured_at"] = "2026-10-01T11:50:00+00:00"
    item["sources"]["hailo"]["models"] = [{"id": next(iter(ACCEPTED_MODELS)),
                                              "sha256": ""}]
    codes = {finding["code"] for finding in
             evaluate_temper_watch(item, now=NOW)["findings"]}
    assert {"source_stale", "model_set_drift", "model_hash_missing"} <= codes


def test_mqtt_and_sensor_integrity_are_advisory_only():
    item = fixture()
    item["sources"]["mqtt"].update(authenticated_listener_active=False,
                                    anonymous_listener_active=True)
    item["sources"]["sensors"].update(duplicates=1, replays=2)
    report = evaluate_temper_watch(item, now=NOW)
    codes = {finding["code"] for finding in report["findings"]}
    assert {"mqtt_secure_path_unavailable", "mqtt_transition_listener",
            "sensor_integrity_exception"} <= codes
    assert report["external_actions"] == 0


def test_schema_rejects_wrong_node_and_incomplete_sources():
    item = fixture(); item["node_id"] = "forge"
    with pytest.raises(ValueError, match="another node"):
        evaluate_temper_watch(item, now=NOW)
    item = fixture(); del item["sources"]["mqtt"]
    with pytest.raises(ValueError, match="incomplete"):
        evaluate_temper_watch(item, now=NOW)


def test_negative_permissions_and_disposable_D_through_P_simulation():
    assert {"body_action", "change_model", "publish_mqtt", "remote_shell",
            "approve", "deploy", "restart_service"} <= set(PROHIBITED)
    result = run_temper_watch_simulation()
    assert result["passed"] is True
    assert result["check_count"] == 13
    assert result["live_state_changed"] is False
    assert result["external_actions"] == 0


def test_runtime_unit_is_least_privilege_and_network_blocked():
    from pathlib import Path
    unit = (Path(__file__).parents[1] /
            "deploy/temper/orca-temper-watch.service").read_text()
    assert "User=fryrocket" in unit
    assert "NoNewPrivileges=yes" in unit
    assert "ProtectSystem=strict" in unit
    assert "RestrictAddressFamilies=AF_UNIX" in unit
    assert "MemoryMax=128M" in unit and "CPUQuota=25%" in unit
    assert "sudo" not in unit and "ExecStartPre" not in unit
