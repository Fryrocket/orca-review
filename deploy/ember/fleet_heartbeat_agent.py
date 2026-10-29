#!/usr/bin/env python3
"""ORCA fleet heartbeat agent — runs on each node (ANVIL, FORGE, KILN, EMBER, TEMPER).

Every 5 minutes: collect local health, ping peers over Tailscale, write a signed
JSON report to the shared reports directory. Read-only observation; no remote
execution, no secrets in the report.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import socket
import time
import urllib.request
from pathlib import Path

DEFAULT_PEERS = {
    "anvil": "192.168.4.20",
    "forge": "192.168.7.30",
    "kiln": "192.168.4.28",
    "ember": "192.168.4.35",
    "temper": "192.168.4.25",
}

DEFAULT_HEALTH_URL = "http://127.0.0.1:18787/api/health"
DEFAULT_REPORT_DIR = Path("/var/lib/orca-fleet-heartbeat")
FRESHNESS_SEC = 900  # 15 minutes


def _meminfo():
    values = {}
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        name, value = line.split(":", 1)
        values[name] = int(value.strip().split()[0]) * 1024
    return values


def local_health():
    load1 = float(Path("/proc/loadavg").read_text(encoding="utf-8").split()[0])
    memory = _meminfo()
    disk = os.statvfs("/")
    total = disk.f_blocks * disk.f_frsize
    available = disk.f_bavail * disk.f_frsize
    try:
        temperature_c = int(Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()) / 1000
    except (OSError, ValueError):
        temperature_c = None
    return {
        "cpu_count": os.cpu_count(),
        "load1": load1,
        "memory_available_bytes": memory.get("MemAvailable"),
        "swap_total_bytes": memory.get("SwapTotal"),
        "swap_free_bytes": memory.get("SwapFree"),
        "disk_used_percent": round((total - available) * 100 / total, 2) if total else None,
        "temperature_c": temperature_c,
    }


def orca_health(health_url):
    try:
        req = urllib.request.Request(health_url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.load(resp)
        return {"status": data.get("status"), "integrity_valid": data.get("integrity_valid")}
    except Exception as exc:
        return {"status": "unreachable", "error": type(exc).__name__}


def ping_peer(host, port=22, timeout=3.0):
    start = time.time()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return {"reachable": True, "latency_ms": round((time.time() - start) * 1000, 1)}
    except OSError as exc:
        return {"reachable": False, "error": type(exc).__name__,
                "latency_ms": round((time.time() - start) * 1000, 1)}


def sign_report(report, secret):
    payload = json.dumps(report, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def write_report(report, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(mode=0o750, parents=True, exist_ok=True)
    target = output_dir / f"{report['node']}.json"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o640)
    os.replace(tmp, target)
    return target


def main():
    parser = argparse.ArgumentParser(description="ORCA fleet heartbeat agent")
    parser.add_argument("--node", required=True, help="This node's name (anvil/forge/kiln/ember/temper)")
    parser.add_argument("--secret-file", required=True, help="Path to shared HMAC secret file")
    parser.add_argument("--output-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--health-url", default=DEFAULT_HEALTH_URL)
    parser.add_argument("--peers", default="", help="Comma list of peer names to ping; default: all except self")
    args = parser.parse_args()

    secret = Path(args.secret_file).read_text(encoding="utf-8").strip()
    peers = [p.strip() for p in args.peers.split(",") if p.strip()] or [
        n for n in DEFAULT_PEERS if n != args.node
    ]

    now = int(time.time())
    report = {
        "schema_version": 1,
        "node": args.node,
        "observed_epoch": now,
        "local": local_health(),
        "orca": orca_health(args.health_url),
        "peers": {p: ping_peer(DEFAULT_PEERS[p]) for p in peers if p in DEFAULT_PEERS},
        "freshness_sec": FRESHNESS_SEC,
    }
    report["signature"] = sign_report(report, secret)
    path = write_report(report, args.output_dir)
    print(json.dumps({"wrote": str(path), "state": "ok", "node": args.node}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
