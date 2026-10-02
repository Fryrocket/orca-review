#!/usr/bin/env python3
"""Bounded Wake-on-LAN guard for the ORCA recovery chain."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import tempfile
import time
from urllib.request import urlopen


def magic_packet(mac: str) -> bytes:
    raw = bytes.fromhex(mac.replace(":", "").replace("-", ""))
    if len(raw) != 6:
        raise ValueError("MAC address must contain six octets")
    return b"\xff" * 6 + raw * 16


def send_magic(mac: str, broadcasts: list[str], port: int = 9) -> None:
    packet = magic_packet(mac)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for address in broadcasts:
            sock.sendto(packet, (address, port))


def tcp_ok(target: str, timeout: float) -> bool:
    host, port_text = target.rsplit(":", 1)
    try:
        with socket.create_connection((host, int(port_text)), timeout=timeout):
            return True
    except OSError:
        return False


def http_ok(url: str, timeout: float) -> bool:
    try:
        with urlopen(url, timeout=timeout) as response:
            payload = json.load(response)
        return (response.status == 200 and payload.get("status") == "healthy"
                and payload.get("integrity_valid") is True)
    except Exception:
        return False


def write_state(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, separators=(",", ":"), sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--target", required=True)
    result.add_argument("--mac", required=True)
    result.add_argument("--broadcast", action="append", required=True)
    result.add_argument("--tcp", required=True)
    result.add_argument("--health-url")
    result.add_argument("--state-file", required=True)
    result.add_argument("--failures-before-wake", type=int, default=3)
    result.add_argument("--retries", type=int, default=3)
    result.add_argument("--retry-wait", type=int, default=30)
    result.add_argument("--timeout", type=float, default=4.0)
    return result


def main() -> int:
    args = parser().parse_args()
    state_path = Path(args.state_file)
    failures = 0
    if state_path.exists():
        try:
            failures = int(json.loads(state_path.read_text()).get(
                "consecutive_failures", 0))
        except Exception:
            failures = 0

    powered = tcp_ok(args.tcp, args.timeout)
    app_healthy = (
        http_ok(args.health_url, args.timeout)
        if args.health_url and powered else powered
    )
    now = int(time.time())
    if powered and app_healthy:
        write_state(state_path, {"target": args.target, "state": "healthy",
                    "consecutive_failures": 0, "checked_epoch": now})
        print(f"{args.target}: healthy")
        return 0
    if powered:
        failures += 1
        write_state(state_path, {"target": args.target,
                    "state": "application_degraded",
                    "consecutive_failures": failures, "checked_epoch": now})
        print(f"{args.target}: powered but application health failed; no wake sent")
        return 1

    failures += 1
    if failures < args.failures_before_wake:
        write_state(state_path, {"target": args.target, "state": "suspect_offline",
                    "consecutive_failures": failures, "checked_epoch": now})
        print(f"{args.target}: offline check {failures}/{args.failures_before_wake}")
        return 1
    for attempt in range(1, args.retries + 1):
        send_magic(args.mac, args.broadcast)
        deadline = time.monotonic() + args.retry_wait
        while time.monotonic() < deadline:
            time.sleep(min(5, max(0.1, deadline - time.monotonic())))
            if tcp_ok(args.tcp, args.timeout):
                write_state(state_path, {"target": args.target, "state": "woken",
                            "consecutive_failures": 0,
                            "checked_epoch": int(time.time()),
                            "wake_attempt": attempt})
                print(f"{args.target}: reachable after wake attempt {attempt}")
                return 0
    write_state(state_path, {"target": args.target, "state": "wake_failed",
                "consecutive_failures": failures, "checked_epoch": int(time.time()),
                "wake_attempts": args.retries})
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
