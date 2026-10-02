#!/usr/bin/env python3
"""Read-only, atomic fleet recovery readiness report."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import time
from urllib.request import urlopen


REQUIRED_NODES = {"anvil", "forge", "kiln", "ember", "temper"}


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, separators=(",", ":"), sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def parse_epoch(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def assess(snapshot: dict, *, now: int, max_age: int) -> dict:
    failures: list[str] = []
    if snapshot.get("evidence_chain_valid") is not True:
        failures.append("evidence_integrity_invalid")
    if snapshot.get("emergency_stop") is True:
        failures.append("emergency_stop_active")
    paused = snapshot.get("paused_nodes")
    if not isinstance(paused, list):
        failures.append("paused_nodes_invalid")
        paused = []
    failures.extend(f"node_paused:{node}" for node in sorted(paused))
    nodes = {row.get("id"): row for row in snapshot.get("nodes", [])
             if isinstance(row, dict)}
    for node_id in sorted(REQUIRED_NODES):
        row = nodes.get(node_id)
        if row is None:
            failures.append(f"node_missing:{node_id}")
            continue
        if row.get("state") != "healthy":
            failures.append(f"node_unhealthy:{node_id}:{row.get('state')}")
        verified = row.get("last_verified")
        try:
            age = now - parse_epoch(verified)
            if age < 0 or age > max_age:
                failures.append(f"heartbeat_stale:{node_id}:{age}")
        except (AttributeError, TypeError, ValueError):
            failures.append(f"heartbeat_invalid:{node_id}")
    return {
        "schema_version": 1,
        "checked_epoch": now,
        "ready": not failures,
        "state_revision": snapshot.get("state_revision"),
        "required_nodes": sorted(REQUIRED_NODES),
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-url", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-age", type=int, default=180)
    parser.add_argument("--timeout", type=float, default=8)
    args = parser.parse_args()
    with urlopen(args.state_url, timeout=args.timeout) as response:
        snapshot = json.load(response)
    report = assess(snapshot, now=int(time.time()), max_age=args.max_age)
    atomic_json(Path(args.output), report)
    print(json.dumps(report, separators=(",", ":"), sort_keys=True))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
