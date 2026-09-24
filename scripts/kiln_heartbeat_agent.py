#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
from dataclasses import asdict
import json
import os
from pathlib import Path
import stat
import time
from urllib.request import Request, urlopen

from orca.heartbeat_agent import HeartbeatAgent


def load_key(path: Path) -> bytes:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("node key must be a regular non-symlink file")
    if metadata.st_mode & 0o077 or metadata.st_uid != os.geteuid():
        raise ValueError("node key must be owner-only and owned by this user")
    key = path.read_bytes()
    if not 32 <= len(key) <= 512:
        raise ValueError("node key must contain 32-512 bytes")
    return key


def check_endpoint(url: str) -> None:
    with urlopen(url, timeout=5) as response:
        payload = json.load(response)
    if not isinstance(payload, dict) or not payload.get("data"):
        raise RuntimeError("model endpoint returned no model inventory")


def main() -> None:
    parser = argparse.ArgumentParser(description="KILN signed heartbeat agent")
    parser.add_argument("--key-file", required=True)
    parser.add_argument("--state-file", required=True)
    parser.add_argument("--url", default="http://127.0.0.1:18787/api/heartbeats")
    parser.add_argument("--smith-url", default="http://100.97.193.39:11434/v1/models")
    parser.add_argument("--quench-url", default="http://100.97.193.39:11435/v1/models")
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.interval < 10:
        raise ValueError("heartbeat interval must be at least 10 seconds")

    key = load_key(Path(args.key_file))

    def transport(heartbeat, signature):
        body = json.dumps({
            "heartbeat": asdict(heartbeat),
            "signature": signature,
            "key": base64.b64encode(key).decode("ascii"),
        }, separators=(",", ":")).encode()
        request = Request(
            args.url, data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=10) as response:
            return json.load(response)

    agent = HeartbeatAgent(
        node_id="kiln", key=key, state_path=args.state_file, transport=transport)
    while True:
        state = "healthy"
        detail = "SMITH and QUENCH endpoints healthy"
        try:
            check_endpoint(args.smith_url)
            check_endpoint(args.quench_url)
        except Exception:
            state = "degraded"
            detail = "one or more inference endpoints unavailable"
        agent.send(state=state, detail=detail)
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
