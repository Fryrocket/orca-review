#!/usr/bin/env python3
"""Privacy-preserving USB camera liveness probe for TEMPER Watch."""

import argparse
import json
import os
import stat
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def probe(device: Path, *, command="/usr/bin/v4l2-ctl", timeout=12) -> dict:
    started = time.monotonic()
    available = False
    error = None
    try:
        mode = device.stat().st_mode
        if not stat.S_ISCHR(mode):
            raise RuntimeError("camera path is not a character device")
        result = subprocess.run(
            [command, "-d", str(device), "--stream-mmap=3", "--stream-count=1",
             "--stream-to=/dev/null", "--stream-poll"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, text=True, timeout=timeout, check=False,
        )
        available = result.returncode == 0
        if not available:
            error = f"v4l2_exit_{result.returncode}"
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        error = type(exc).__name__
    return {
        "schema": 1,
        "source": "usb_camera_liveness",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "available": available,
        "device": str(device),
        "image_retained": False,
        "external_actions": 0,
        "latency_ms": round((time.monotonic() - started) * 1000, 2),
        "error": error,
    }


def atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.new")
    temporary.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    temporary.chmod(0o640)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", type=Path, default=Path("/dev/video0"))
    parser.add_argument("--output", type=Path,
                        default=Path("/var/lib/temper-sensors/camera-health.json"))
    args = parser.parse_args()
    payload = probe(args.device)
    atomic_write(args.output, payload)
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["available"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
