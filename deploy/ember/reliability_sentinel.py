#!/usr/bin/env python3
"""Read-only reliability observer for EMBER and the loopback ORCA endpoint."""

import argparse
import json
import os
import time
import urllib.request
from pathlib import Path


DEFAULT_RECOVERY_REPORT = Path("/var/lib/orca-recovery-marshal/status.json")


def evaluate(snapshot, now=None):
    now = int(time.time() if now is None else now)
    findings = []

    cpu_count = snapshot.get("cpu_count")
    load1 = snapshot.get("load1")
    if not isinstance(cpu_count, int) or cpu_count < 1 or not isinstance(load1, (int, float)):
        findings.append("cpu telemetry unavailable")
    elif load1 / cpu_count > 1.5:
        findings.append("sustained load exceeds 1.5 per CPU")

    memory_available = snapshot.get("memory_available_bytes")
    if not isinstance(memory_available, int):
        findings.append("memory telemetry unavailable")
    elif memory_available < 512 * 1024 * 1024:
        findings.append("available memory below 512 MiB")

    swap_total = snapshot.get("swap_total_bytes")
    swap_free = snapshot.get("swap_free_bytes")
    if not isinstance(swap_total, int) or not isinstance(swap_free, int):
        findings.append("swap telemetry unavailable")
    elif swap_total > 0 and (swap_total - swap_free) / swap_total > 0.80:
        findings.append("swap usage exceeds 80 percent")

    disk_used_percent = snapshot.get("disk_used_percent")
    if not isinstance(disk_used_percent, (int, float)):
        findings.append("disk telemetry unavailable")
    elif disk_used_percent > 85:
        findings.append("root disk usage exceeds 85 percent")

    temperature_c = snapshot.get("temperature_c")
    if not isinstance(temperature_c, (int, float)):
        findings.append("temperature telemetry unavailable")
    elif temperature_c > 75:
        findings.append("CPU temperature exceeds 75 C")

    if snapshot.get("orca_health") != "healthy" or snapshot.get("integrity_valid") is not True:
        findings.append("loopback ORCA health or integrity check failed")
    if snapshot.get("recovery_state") != "healthy":
        findings.append("recovery evidence is not healthy")

    return {
        "schema_version": 1,
        "bot_id": "reliability_sentinel",
        "state": "healthy" if not findings else "degraded",
        "observed_epoch": now,
        "authority": "read_only_health_observer",
        "findings": findings,
        "metrics": snapshot,
        "actions_taken": [],
    }


def _meminfo():
    values = {}
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        name, value = line.split(":", 1)
        values[name] = int(value.strip().split()[0]) * 1024
    return values


def collect_snapshot(health_url, recovery_report=DEFAULT_RECOVERY_REPORT):
    load1 = float(Path("/proc/loadavg").read_text(encoding="utf-8").split()[0])
    memory = _meminfo()
    disk = os.statvfs("/")
    total = disk.f_blocks * disk.f_frsize
    available = disk.f_bavail * disk.f_frsize
    temperature_c = int(Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()) / 1000

    request = urllib.request.Request(health_url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=8) as response:
        health = json.load(response)
    recovery = json.loads(Path(recovery_report).read_text(encoding="utf-8"))

    return {
        "cpu_count": os.cpu_count(),
        "load1": load1,
        "memory_available_bytes": memory.get("MemAvailable"),
        "swap_total_bytes": memory.get("SwapTotal"),
        "swap_free_bytes": memory.get("SwapFree"),
        "disk_used_percent": round((total - available) * 100 / total, 2),
        "temperature_c": temperature_c,
        "orca_health": health.get("status"),
        "integrity_valid": health.get("integrity_valid"),
        "recovery_state": recovery.get("state"),
    }


def write_report(report, output):
    target = Path(output)
    target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o640)
    os.replace(temporary, target)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--health-url", default="http://127.0.0.1:18787/api/health")
    parser.add_argument("--recovery-report", default=str(DEFAULT_RECOVERY_REPORT))
    parser.add_argument("--output", default="/var/lib/orca-reliability-sentinel/status.json")
    args = parser.parse_args()
    try:
        snapshot = collect_snapshot(args.health_url, Path(args.recovery_report))
        report = evaluate(snapshot)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = {
            "schema_version": 1,
            "bot_id": "reliability_sentinel",
            "state": "degraded",
            "observed_epoch": int(time.time()),
            "authority": "read_only_health_observer",
            "findings": [f"telemetry unavailable: {type(exc).__name__}"],
            "metrics": {},
            "actions_taken": [],
        }
    write_report(report, args.output)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["state"] == "healthy" else 1


if __name__ == "__main__":
    raise SystemExit(main())
