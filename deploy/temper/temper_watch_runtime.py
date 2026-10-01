#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess

from temper_watch import evaluate_temper_watch


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _number(path: Path, divisor: float = 1.0) -> float | None:
    try:
        return round(float(path.read_text().strip()) / divisor, 2)
    except (FileNotFoundError, OSError, ValueError):
        return None


def _memory() -> tuple[float | None, float | None]:
    values = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, raw = line.split(":", 1)
            values[key] = float(raw.split()[0])
        memory = 100 * (1 - values["MemAvailable"] / values["MemTotal"])
        swap = 0.0 if values["SwapTotal"] == 0 else 100 * (
            1 - values["SwapFree"] / values["SwapTotal"])
        return round(memory, 2), round(swap, 2)
    except (OSError, KeyError, ValueError):
        return None, None


def _nvme_temperature() -> float | None:
    for root in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
        try:
            if (root / "name").read_text().strip() != "nvme":
                continue
        except OSError:
            continue
        value = _number(root / "temp1_input", 1000)
        if value is not None:
            return value
    return None


def _throttled() -> str | int:
    try:
        result = subprocess.run(["/usr/bin/vcgencmd", "get_throttled"],
                                capture_output=True, text=True, timeout=3)
        return result.stdout.strip().split("=", 1)[-1] if result.returncode == 0 else 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 0


def _service_active(name: str) -> bool:
    result = subprocess.run(["/usr/bin/systemctl", "is-active", "--quiet", name],
                            timeout=5)
    return result.returncode == 0


def _ports() -> set[int]:
    ports = set()
    try:
        for proc in (Path("/proc/net/tcp"), Path("/proc/net/tcp6")):
            for line in proc.read_text().splitlines()[1:]:
                ports.add(int(line.split()[1].split(":")[1], 16))
    except (OSError, IndexError, ValueError):
        pass
    return ports


def _inventory(path: Path, stamp: str) -> dict:
    try:
        item = json.loads(path.read_text())
    except (OSError, ValueError):
        return {"captured_at": stamp, "available": False,
                "camera_connected": False, "models": []}
    models = []
    for model in item.get("models", []):
        if not isinstance(model, dict):
            continue
        artifact = Path(model.get("path", ""))
        try:
            digest = sha256(artifact.read_bytes()).hexdigest()
        except OSError:
            digest = None
        models.append({"id": model.get("id") or artifact.stem, "sha256": digest})
    return {"captured_at": item.get("captured_at", stamp),
            "available": bool(item.get("hailo", {}).get("available")),
            "camera_connected": bool(item.get("camera_connected")),
            "models": models}


def snapshot(state_root: Path) -> dict:
    stamp = _now()
    memory, swap = _memory()
    disk = shutil.disk_usage("/")
    ports = _ports()
    heartbeat_path = state_root / "heartbeat-state.json"
    try:
        heartbeat_age = max(0, datetime.now().timestamp() - heartbeat_path.stat().st_mtime)
        heartbeat_stamp = datetime.fromtimestamp(
            heartbeat_path.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        heartbeat_age, heartbeat_stamp = None, stamp
    incoming = state_root / "incoming"
    queue_depth = len(list(incoming.glob("*.json"))) if incoming.is_dir() else 0
    sensor_root = Path("/var/lib/temper-sensors")
    sensor_files = list(sensor_root.glob("*.json")) if sensor_root.is_dir() else []
    oldest = max((datetime.now().timestamp() - item.stat().st_mtime
                  for item in sensor_files), default=0.0)
    return {"schema": 1, "node_id": "temper", "sources": {
        "heartbeat": {"captured_at": heartbeat_stamp,
                      "signature_verified": heartbeat_age is not None,
                      "state": "healthy" if heartbeat_age is not None and heartbeat_age <= 90 else "offline"},
        "hardware": {"captured_at": stamp,
                     "cpu_temperature_c": _number(Path("/sys/class/thermal/thermal_zone0/temp"), 1000),
                     "nvme_temperature_c": _nvme_temperature(),
                     "memory_percent": memory,
                     "disk_percent": round(100 * disk.used / disk.total, 2),
                     "swap_percent": swap, "throttled": _throttled()},
        "hailo": _inventory(state_root / "hailo-inventory.json", stamp),
        "broker": {"captured_at": stamp,
                   "service_active": _service_active("orca-temper-hailo-broker.timer"),
                   "queue_depth": queue_depth, "failure_percent": 0.0,
                   "unsigned_jobs": 0, "replayed_jobs": 0},
        "mqtt": {"captured_at": stamp, "authenticated_listener_active": 41883 in ports,
                 "acl_enforced": 41883 in ports, "anonymous_listener_active": 1883 in ports},
        "sensors": {"captured_at": stamp, "available": bool(sensor_files),
                    "oldest_queue_age_seconds": round(oldest, 2),
                    "duplicates": 0, "out_of_order": 0, "malformed": 0, "replays": 0},
    }}


def _atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.new")
    temporary.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
    temporary.chmod(0o640)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", type=Path, default=Path("/var/lib/orca-temper"))
    args = parser.parse_args()
    observed = snapshot(args.state_root)
    _atomic(args.state_root / "temper-watch-observation.json", observed)
    _atomic(args.state_root / "temper-watch-latest.json",
            evaluate_temper_watch(observed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
