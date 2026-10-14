#!/usr/bin/env python3
"""ORCA Reliability Sentinel — extended with fleet heartbeat aggregation.

Modes:
  1. local  (default): original EMBER-local observation (CPU, memory, disk,
     temperature, loopback ORCA health, recovery marshal evidence).
  2. fleet  : read signed heartbeat reports from all enrolled nodes, check
     freshness (default 15 min), verify HMAC signatures, and report any node
     that is silent, degraded, or has failed peers.

Read-only. No remote execution, no threshold changes, no restarts.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import time
import urllib.request
from pathlib import Path

DEFAULT_RECOVERY_REPORT = Path("/var/lib/orca-recovery-marshal/status.json")
DEFAULT_HEARTBEAT_DIR = Path("/var/lib/orca-fleet-heartbeat")
DEFAULT_FRESHNESS = 900  # 15 minutes
ENROLLED_NODES = ("anvil", "forge", "kiln", "ember", "temper")


# ---------- original local evaluation (unchanged behavior) ----------

def evaluate_local(snapshot, now=None):
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
        "mode": "local",
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


def collect_local_snapshot(health_url, recovery_report=DEFAULT_RECOVERY_REPORT):
    load1 = float(Path("/proc/loadavg").read_text(encoding="utf-8").split()[0])
    memory = _meminfo()
    disk = os.statvfs("/")
    total = disk.f_blocks * disk.f_frsize
    available = disk.f_bavail * disk.f_frsize
    try:
        temperature_c = int(Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()) / 1000
    except (OSError, ValueError):
        temperature_c = None

    try:
        request = urllib.request.Request(health_url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=8) as response:
            health = json.load(response)
        orca_health = health.get("status")
        integrity_valid = health.get("integrity_valid")
    except (OSError, ValueError, json.JSONDecodeError):
        orca_health, integrity_valid = "unreachable", None

    try:
        recovery = json.loads(Path(recovery_report).read_text(encoding="utf-8"))
        recovery_state = recovery.get("state")
    except (OSError, ValueError, json.JSONDecodeError):
        recovery_state = "unavailable"

    return {
        "cpu_count": os.cpu_count(),
        "load1": load1,
        "memory_available_bytes": memory.get("MemAvailable"),
        "swap_total_bytes": memory.get("SwapTotal"),
        "swap_free_bytes": memory.get("SwapFree"),
        "disk_used_percent": round((total - available) * 100 / total, 2) if total else None,
        "temperature_c": temperature_c,
        "orca_health": orca_health,
        "integrity_valid": integrity_valid,
        "recovery_state": recovery_state,
    }


# ---------- new fleet evaluation ----------

def _verify_signature(report, secret):
    sig = report.pop("signature", None)
    if not sig or not secret:
        return False
    payload = json.dumps(report, sort_keys=True, separators=(",", ":")).encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    report["signature"] = sig
    return hmac.compare_digest(sig, expected)


def evaluate_fleet(heartbeat_dir, secret, now=None, freshness=DEFAULT_FRESHNESS):
    now = int(time.time() if now is None else now)
    heartbeat_dir = Path(heartbeat_dir)
    findings = []
    node_reports = {}

    for node in ENROLLED_NODES:
        path = heartbeat_dir / f"{node}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            findings.append(f"{node}: report missing or unreadable ({type(exc).__name__})")
            node_reports[node] = {"state": "unavailable"}
            continue

        if not _verify_signature(data, secret):
            findings.append(f"{node}: signature invalid")
            node_reports[node] = {"state": "untrusted"}
            continue

        age = now - int(data.get("observed_epoch", 0))
        if age > freshness:
            findings.append(f"{node}: heartbeat stale ({age}s old, limit {freshness}s)")
            node_reports[node] = {"state": "stale", "age_seconds": age}
            continue

        local = data.get("local", {})
        node_state = "healthy"
        node_findings = []
        if local.get("disk_used_percent", 0) > 85:
            node_findings.append("disk > 85%")
        if local.get("temperature_c") is not None and local["temperature_c"] > 75:
            node_findings.append("temp > 75C")
        mem = local.get("memory_available_bytes")
        if isinstance(mem, int) and mem < 512 * 1024 * 1024:
            node_findings.append("memory < 512 MiB")
        orca = data.get("orca", {})
        if orca.get("status") != "healthy":
            node_findings.append(f"orca {orca.get('status', 'unreachable')}")
        for peer, info in data.get("peers", {}).items():
            if not info.get("reachable"):
                node_findings.append(f"peer {peer} unreachable")
        if node_findings:
            node_state = "degraded"
            findings.append(f"{node}: " + "; ".join(node_findings))
        node_reports[node] = {"state": node_state, "age_seconds": age, "findings": node_findings}

    for node in ENROLLED_NODES:
        if node not in node_reports:
            findings.append(f"{node}: no report received")
            node_reports[node] = {"state": "missing"}

    return {
        "schema_version": 1,
        "bot_id": "reliability_sentinel",
        "mode": "fleet",
        "state": "healthy" if not findings else "degraded",
        "observed_epoch": now,
        "authority": "read_only_health_observer",
        "freshness_sec": freshness,
        "findings": findings,
        "nodes": node_reports,
        "actions_taken": [],
    }


def write_report(report, output):
    target = Path(output)
    target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o640)
    os.replace(temporary, target)


def main():
    parser = argparse.ArgumentParser(description="ORCA Reliability Sentinel")
    parser.add_argument("--mode", choices=("local", "fleet"), default="local")
    parser.add_argument("--health-url", default="http://127.0.0.1:18787/api/health")
    parser.add_argument("--recovery-report", default=str(DEFAULT_RECOVERY_REPORT))
    parser.add_argument("--heartbeat-dir", default=str(DEFAULT_HEARTBEAT_DIR))
    parser.add_argument("--secret-file", default="", help="Required for fleet mode")
    parser.add_argument("--freshness", type=int, default=DEFAULT_FRESHNESS)
    parser.add_argument("--output", default="/var/lib/orca-reliability-sentinel/status.json")
    args = parser.parse_args()

    try:
        if args.mode == "local":
            snapshot = collect_local_snapshot(args.health_url, Path(args.recovery_report))
            report = evaluate_local(snapshot)
        else:
            if not args.secret_file:
                raise ValueError("fleet mode requires --secret-file")
            secret = Path(args.secret_file).read_text(encoding="utf-8").strip()
            report = evaluate_fleet(args.heartbeat_dir, secret, freshness=args.freshness)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = {
            "schema_version": 1,
            "bot_id": "reliability_sentinel",
            "mode": args.mode,
            "state": "degraded",
            "observed_epoch": int(time.time()),
            "authority": "read_only_health_observer",
            "findings": [f"telemetry unavailable: {type(exc).__name__}: {exc}"],
            "metrics": {},
            "actions_taken": [],
        }

    write_report(report, args.output)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["state"] == "healthy" else 1


if __name__ == "__main__":
    raise SystemExit(main())
