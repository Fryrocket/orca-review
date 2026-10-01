#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess


def discover_uvc_cameras(root: Path = Path("/sys/class/video4linux")) -> list[dict]:
    cameras = []
    if not root.is_dir():
        return cameras
    for entry in sorted(root.glob("video*")):
        try:
            resolved = entry.resolve(strict=True)
            name = (entry / "name").read_text().strip()
        except (FileNotFoundError, OSError):
            continue
        driver = ""
        driver_link = entry / "device" / "driver"
        try:
            driver = driver_link.resolve(strict=True).name
        except (FileNotFoundError, OSError):
            pass
        # The Pi codecs and ISP also expose /dev/video* nodes.  Only a USB path
        # or the standard UVC driver qualifies as the external camera.
        if driver != "uvcvideo" and "/usb" not in str(resolved):
            continue
        cameras.append({
            "device": f"/dev/{entry.name}",
            "name": name,
            "driver": driver or "usb",
        })
    return cameras


def discover_h8_models(root: Path = Path("/usr/share/hailo-models")) -> list[dict]:
    models = []
    if not root.is_dir():
        return models
    for artifact in sorted(root.glob("*_h8.hef")):
        try:
            stat = artifact.stat()
        except OSError:
            continue
        models.append({
            "id": artifact.stem,
            "path": str(artifact),
            "bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        })
    return models


def identify_hailo(timeout: float = 8.0) -> dict:
    try:
        completed = subprocess.run(
            ["/usr/bin/hailortcli", "fw-control", "identify"],
            check=False, capture_output=True, text=True, timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {"available": False, "error": "hailort identification unavailable"}
    if completed.returncode != 0:
        return {"available": False, "error": "hailort identification failed"}
    values = {}
    for line in completed.stdout.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        normalized = key.strip().casefold().replace(" ", "_")
        if normalized in {"firmware_version", "board_name", "device_architecture", "product_name"}:
            values[normalized] = value.strip().replace("\x00", "")
    return {"available": True, **values}


def cpu_temperature() -> float | None:
    try:
        return round(int(Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()) / 1000, 2)
    except (FileNotFoundError, OSError, ValueError):
        return None


def snapshot() -> dict:
    cameras = discover_uvc_cameras()
    return {
        "schema": 1,
        "node_id": "temper",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "hailo": identify_hailo(),
        "models": discover_h8_models(),
        "cameras": cameras,
        "camera_connected": bool(cameras),
        "cpu_temperature_c": cpu_temperature(),
        "automatic_execution": False,
    }


def write_atomic(output: Path, payload: dict) -> None:
    output.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.new")
    temporary.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    temporary.chmod(0o640)
    temporary.replace(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    write_atomic(args.output, snapshot())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
