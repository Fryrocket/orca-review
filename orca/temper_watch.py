from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json


SCHEMA_VERSION = 1
THRESHOLDS_VERSION = "temper-watch-2026-10-01"
DATA_SOURCES = {
    "heartbeat": "signed ORCA fleet heartbeat",
    "hardware": "local Pi/NVMe resource snapshot",
    "hailo": "Hailo inventory and accepted artifact hashes",
    "broker": "bounded Hailo broker queue/result summary",
    "mqtt": "local authenticated and transition MQTT listeners",
    "sensors": "sensor freshness and offline queue summary",
}
FRESHNESS_SECONDS = {
    "heartbeat": 90, "hardware": 120, "hailo": 180,
    "broker": 120, "mqtt": 120, "sensors": 300,
}
LIMITS = {
    "cpu_temperature_c": (75.0, 85.0),
    "nvme_temperature_c": (70.0, 80.0),
    "memory_percent": (85.0, 95.0),
    "disk_percent": (80.0, 90.0),
    "swap_percent": (25.0, 60.0),
    "broker_queue_depth": (1.0, 3.0),
    "broker_failure_percent": (2.0, 5.0),
    "sensor_queue_age_seconds": (300.0, 900.0),
}
ACCEPTED_MODELS = frozenset({
    "yolov6n_h8", "yolov8s_h8", "yolov5n_seg_h8", "yolov8s_pose_h8",
})
PROHIBITED = (
    "body_action", "change_model", "publish_mqtt", "remote_shell",
    "approve", "deploy", "restart_service", "delete_evidence",
)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("source timestamp must be an ISO string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("source timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _finding(findings: list[dict], source: str, code: str, severity: str,
             detail: str) -> None:
    findings.append({"source": source, "code": code,
                     "severity": severity, "detail": detail})


def _check_limit(findings: list[dict], source: str, key: str,
                 value: object) -> None:
    if value is None:
        _finding(findings, source, f"{key}_missing", "warning",
                 f"{key} is unavailable")
        return
    if type(value) not in {int, float}:
        _finding(findings, source, f"{key}_invalid", "critical",
                 f"{key} is not numeric")
        return
    warning, critical = LIMITS[key]
    if value >= critical:
        _finding(findings, source, f"{key}_critical", "critical",
                 f"{key}={value} exceeds {critical}")
    elif value >= warning:
        _finding(findings, source, f"{key}_warning", "warning",
                 f"{key}={value} exceeds {warning}")


def evaluate_temper_watch(snapshot: dict, *, now: datetime | None = None) -> dict:
    """Evaluate one immutable TEMPER observation without taking any action."""
    if not isinstance(snapshot, dict) or snapshot.get("schema") != SCHEMA_VERSION:
        raise ValueError("TEMPER Watch snapshot schema is unsupported")
    if snapshot.get("node_id") != "temper":
        raise ValueError("TEMPER Watch snapshot belongs to another node")
    sources = snapshot.get("sources")
    if not isinstance(sources, dict) or set(sources) != set(DATA_SOURCES):
        raise ValueError("TEMPER Watch source map is incomplete")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    findings: list[dict] = []
    for source, max_age in FRESHNESS_SECONDS.items():
        payload = sources[source]
        if not isinstance(payload, dict):
            raise ValueError(f"TEMPER Watch source {source} is invalid")
        try:
            age = (current - _timestamp(payload.get("captured_at"))).total_seconds()
        except (TypeError, ValueError):
            _finding(findings, source, "timestamp_invalid", "critical",
                     "source timestamp is missing or invalid")
            continue
        if age < -60:
            _finding(findings, source, "timestamp_future", "critical",
                     "source timestamp is too far in the future")
        elif age > max_age:
            _finding(findings, source, "source_stale", "critical",
                     f"source age {round(age, 1)}s exceeds {max_age}s")

    heartbeat = sources["heartbeat"]
    if not heartbeat.get("signature_verified") or heartbeat.get("state") != "healthy":
        _finding(findings, "heartbeat", "heartbeat_unhealthy", "critical",
                 "signed healthy heartbeat is not verified")

    hardware = sources["hardware"]
    for key in ("cpu_temperature_c", "nvme_temperature_c", "memory_percent",
                "disk_percent", "swap_percent"):
        _check_limit(findings, "hardware", key, hardware.get(key))
    if hardware.get("throttled", 0) not in {0, "0x0", "0"}:
        _finding(findings, "hardware", "pi_throttled", "critical",
                 "Pi throttling or undervoltage flag is set")

    hailo = sources["hailo"]
    if not hailo.get("available"):
        _finding(findings, "hailo", "hailo_unavailable", "critical",
                 "Hailo-8 is unavailable")
    models = hailo.get("models", [])
    model_ids = {item.get("id") for item in models if isinstance(item, dict)}
    if model_ids != ACCEPTED_MODELS:
        _finding(findings, "hailo", "model_set_drift", "critical",
                 "accepted Hailo model set changed")
    if any(not item.get("sha256") for item in models if isinstance(item, dict)):
        _finding(findings, "hailo", "model_hash_missing", "critical",
                 "one or more Hailo artifacts lack a recorded hash")
    if not hailo.get("camera_connected"):
        _finding(findings, "hailo", "camera_unavailable", "warning",
                 "accepted USB camera is not connected")

    broker = sources["broker"]
    if not broker.get("service_active"):
        _finding(findings, "broker", "broker_inactive", "critical",
                 "bounded inference broker is inactive")
    _check_limit(findings, "broker", "broker_queue_depth",
                 broker.get("queue_depth"))
    _check_limit(findings, "broker", "broker_failure_percent",
                 broker.get("failure_percent"))
    if broker.get("unsigned_jobs", 0) or broker.get("replayed_jobs", 0):
        _finding(findings, "broker", "broker_security_rejection", "warning",
                 "broker rejected unsigned or replayed work")

    mqtt = sources["mqtt"]
    if not mqtt.get("authenticated_listener_active") or not mqtt.get("acl_enforced"):
        _finding(findings, "mqtt", "mqtt_secure_path_unavailable", "critical",
                 "authenticated MQTT listener or ACL is unavailable")
    if mqtt.get("anonymous_listener_active"):
        _finding(findings, "mqtt", "mqtt_transition_listener", "warning",
                 "temporary anonymous MQTT listener remains active")

    sensors = sources["sensors"]
    if not sensors.get("available", True):
        _finding(findings, "sensors", "sensor_stream_unavailable", "warning",
                 "no accepted sensor stream or offline queue is present")
    _check_limit(findings, "sensors", "sensor_queue_age_seconds",
                 sensors.get("oldest_queue_age_seconds"))
    if any(sensors.get(key, 0) for key in
           ("duplicates", "out_of_order", "malformed", "replays")):
        _finding(findings, "sensors", "sensor_integrity_exception", "critical",
                 "sensor queue contains duplicate, out-of-order, malformed or replayed data")

    severity_order = {"warning": 1, "critical": 2}
    top = max((severity_order[item["severity"]] for item in findings), default=0)
    status = "critical" if top == 2 else "warning" if top == 1 else "healthy"
    observation_hash = sha256(_canonical(snapshot)).hexdigest()
    report = {
        "schema": SCHEMA_VERSION,
        "role_id": "temper_watch",
        "node_id": "temper",
        "evaluated_at": current.isoformat(),
        "status": status,
        "mode": "read_only_exception_reporting",
        "source_map": DATA_SOURCES,
        "thresholds_version": THRESHOLDS_VERSION,
        "findings": findings,
        "exception_count": len(findings),
        "actions_taken": [],
        "external_actions": 0,
        "prohibited": list(PROHIBITED),
        "observation_sha256": observation_hash,
    }
    report["report_sha256"] = sha256(_canonical(report)).hexdigest()
    return report


def healthy_fixture(captured_at: str) -> dict:
    """Return disposable synthetic input used by acceptance simulations."""
    stamp = {"captured_at": captured_at}
    return {
        "schema": 1, "node_id": "temper", "sources": {
            "heartbeat": {**stamp, "signature_verified": True, "state": "healthy"},
            "hardware": {**stamp, "cpu_temperature_c": 48.0,
                         "nvme_temperature_c": 42.0, "memory_percent": 32.0,
                         "disk_percent": 18.0, "swap_percent": 0.0,
                         "throttled": 0},
            "hailo": {**stamp, "available": True, "camera_connected": True,
                      "models": [{"id": model, "sha256": "a" * 64}
                                 for model in sorted(ACCEPTED_MODELS)]},
            "broker": {**stamp, "service_active": True, "queue_depth": 0,
                       "failure_percent": 0.0, "unsigned_jobs": 0,
                       "replayed_jobs": 0},
            "mqtt": {**stamp, "authenticated_listener_active": True,
                     "acl_enforced": True, "anonymous_listener_active": False},
            "sensors": {**stamp, "oldest_queue_age_seconds": 0.0,
                        "available": True,
                        "duplicates": 0, "out_of_order": 0,
                        "malformed": 0, "replays": 0},
        },
    }
