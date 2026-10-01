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
from orca.telemetry import encode_detail


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
    if not isinstance(payload, dict):
        raise RuntimeError("health endpoint returned an invalid response")
    if payload.get("status") in {"healthy", "pass"} or payload.get("data"):
        return
    raise RuntimeError("health endpoint did not report available capacity")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ORCA signed node heartbeat agent")
    parser.add_argument("--node-id", default="kiln")
    parser.add_argument("--key-file", required=True)
    parser.add_argument("--state-file", required=True)
    parser.add_argument("--url", default="http://127.0.0.1:18787/api/heartbeats")
    parser.add_argument("--check-url", action="append", default=[])
    parser.add_argument("--healthy-detail", default="")
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--once", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.interval < 10:
        raise ValueError("heartbeat interval must be at least 10 seconds")

    check_urls = list(args.check_url)
    if not check_urls and args.node_id == "kiln":
        check_urls = [
            "http://100.97.193.39:11434/v1/models",
            "http://100.97.193.39:11435/v1/models",
        ]
    if not check_urls:
        raise ValueError("node heartbeat requires at least one health endpoint")

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
        node_id=args.node_id, key=key, state_path=args.state_file, transport=transport)
    while True:
        state = "healthy"
        detail = args.healthy_detail or f"{len(check_urls)} health endpoints available"
        try:
            for check_url in check_urls:
                check_endpoint(check_url)
        except Exception:
            state = "degraded"
            detail = "one or more required health endpoints unavailable"
        agent.send(state=state, detail=encode_detail(detail))
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
