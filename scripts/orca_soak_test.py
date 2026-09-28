#!/usr/bin/env python3
"""Bounded, non-destructive ORCA soak test with fail-closed safety limits."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import secrets
import shutil
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


READ_PATHS = (
    "/api/health", "/api/health", "/api/health", "/api/state",
    "/api/images/health", "/api/videos/health",
)
MODEL_PROBES = (
    ("kiln_codex", "orca", "Return only the word healthy."),
    ("forge_qwen", "smith", "Return only the word healthy."),
    ("kiln_quench", "quench", "Return only the word healthy."),
)
IMAGE_PROMPTS = (
    "A realistic product photo of a compact black electronics module on a clean workbench, neutral labels, soft studio lighting, no brand marks",
    "Detailed engineering concept art of a Raspberry Pi accessory board in a moonlit workshop, accurate proportions, no text",
    "A clean catalog photo of electronic components arranged on an ESD mat, natural shadows, no logos or writing",
)
VIDEO_PROMPTS = (
    "A black circuit board rotates slowly on a dark studio table, soft moonlit rim light, smooth camera orbit, no text",
    "Macro camera glide across silver traces on a compact electronics board, subtle workshop lights, steady motion, no text",
    "A small electronics module rests on an ESD mat while the camera makes a slow controlled arc, realistic lighting, no logos",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def percentile(values: list[float], percent: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(percent * len(ordered)) - 1))
    return ordered[index]


def request(base_url: str, path: str, *, body: dict | None = None,
            timeout: float = 30.0) -> dict:
    payload = None if body is None else json.dumps(body).encode()
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    started = time.monotonic()
    try:
        with urlopen(Request(base_url + path, data=payload, headers=headers),
                     timeout=timeout) as response:
            content = response.read(8_000_001)
            if len(content) > 8_000_000:
                raise ValueError("response exceeded the eight-megabyte safety limit")
            decoded = json.loads(content) if content else {}
            return {"ok": 200 <= response.status < 300, "status": response.status,
                    "latency_ms": round((time.monotonic() - started) * 1000, 2),
                    "bytes": len(content), "body": decoded}
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        return {"ok": False, "status": getattr(exc, "code", 0),
                "latency_ms": round((time.monotonic() - started) * 1000, 2),
                "bytes": 0, "error": str(exc)}


def media_request(base_url: str, path: str, body: dict, output_path: Path,
                  timeout: float = 1_260.0) -> dict:
    started = time.monotonic()
    try:
        payload = json.dumps(body).encode()
        with urlopen(Request(base_url + path, data=payload,
                             headers={"Content-Type": "application/json"}),
                     timeout=timeout) as response:
            content = response.read(128_000_001)
            content_type = response.headers.get_content_type()
            if len(content) > 128_000_000:
                raise ValueError("media exceeded the 128-megabyte safety limit")
            expected = ("video/mp4" if path.endswith("generate") and "videos" in path
                        else "image/png")
            if content_type != expected:
                raise ValueError(f"unexpected media type {content_type}")
            output_path.write_bytes(content)
            return {"ok": True, "status": response.status,
                    "latency_ms": round((time.monotonic() - started) * 1000, 2),
                    "bytes": len(content), "content_type": content_type,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "artifact": str(output_path)}
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
        return {"ok": False, "status": getattr(exc, "code", 0),
                "latency_ms": round((time.monotonic() - started) * 1000, 2),
                "bytes": 0, "error": str(exc)}


def host_snapshot(output_dir: Path) -> dict:
    disk = shutil.disk_usage(output_dir)
    snapshot = {
        "load": list(os.getloadavg()), "disk_free_bytes": disk.free,
        "disk_total_bytes": disk.total,
    }
    try:
        fields = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            fields[key] = int(value.strip().split()[0]) * 1024
        snapshot["memory_available_bytes"] = fields.get("MemAvailable")
        snapshot["swap_free_bytes"] = fields.get("SwapFree")
    except (OSError, ValueError):
        pass
    return snapshot


def append_event(handle, event: dict) -> None:
    handle.write(json.dumps({"timestamp": utc_now(), **event}, sort_keys=True) + "\n")
    handle.flush()


def compact_result(result: dict) -> dict:
    """Keep verification metadata, never copy large state/model bodies into logs."""
    compact = {key: value for key, value in result.items() if key != "body"}
    body = result.get("body")
    if body is not None:
        encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        compact["body_sha256"] = hashlib.sha256(encoded).hexdigest()
        if isinstance(body, dict):
            compact["body_keys"] = sorted(str(key) for key in body)[:40]
            for key in ("status", "integrity_valid", "mode"):
                if key in body and isinstance(body[key], (str, bool, int, float, type(None))):
                    compact[f"body_{key}"] = body[key]
    return compact


def run(args: argparse.Namespace) -> dict:
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    events_path = output_dir / f"orca-soak-{run_id}.jsonl"
    report_path = output_dir / f"orca-soak-{run_id}-report.json"
    started = time.monotonic()
    deadline = started + args.duration
    next_model = started
    next_media = started if args.media_every > 0 else float("inf")
    model_index = 0
    media_index = 0
    media_future = None
    media_meta = None
    latencies: list[float] = []
    requests = failures = 0
    consecutive_health_failures = 0
    stop_reason = "duration_complete"
    with events_path.open("x", encoding="utf-8") as events:
        append_event(events, {"kind": "start", "duration_seconds": args.duration,
                              "rps": args.rps, "workers": args.workers,
                              "base_url": args.base_url, "non_destructive": True})
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            while time.monotonic() < deadline:
                cycle_started = time.monotonic()
                batch_size = max(1, min(args.workers, math.ceil(args.rps)))
                futures = [pool.submit(request, args.base_url,
                                       READ_PATHS[(requests + i) % len(READ_PATHS)],
                                       timeout=args.timeout)
                           for i in range(batch_size)]
                cycle_health_ok = True
                for future in as_completed(futures):
                    result = future.result()
                    requests += 1
                    latencies.append(result["latency_ms"])
                    if not result["ok"]:
                        failures += 1
                        cycle_health_ok = False
                    append_event(events, {"kind": "read_probe", **compact_result(result)})
                consecutive_health_failures = (0 if cycle_health_ok
                                               else consecutive_health_failures + 1)

                if time.monotonic() >= next_model:
                    service_id, bot_id, prompt = MODEL_PROBES[model_index % len(MODEL_PROBES)]
                    result = request(args.base_url, "/api/inference", body={
                        "service_id": service_id, "bot_id": bot_id,
                        "prompt": prompt, "history": [],
                    }, timeout=args.model_timeout)
                    requests += 1
                    latencies.append(result["latency_ms"])
                    if not result["ok"]:
                        failures += 1
                    append_event(events, {"kind": "model_probe", "service_id": service_id,
                                          "bot_id": bot_id, **compact_result(result)})
                    model_index += 1
                    next_model = time.monotonic() + args.model_every

                if media_future is not None and media_future.done():
                    result = media_future.result()
                    requests += 1
                    latencies.append(result["latency_ms"])
                    if not result["ok"]:
                        failures += 1
                    append_event(events, {"kind": "media_probe", **media_meta, **result})
                    media_future = None
                    media_meta = None
                if media_future is None and time.monotonic() >= next_media:
                    make_video = media_index % 2 == 1
                    prompt = secrets.choice(VIDEO_PROMPTS if make_video else IMAGE_PROMPTS)
                    seed = secrets.randbelow(2**53)
                    if make_video:
                        path = "/api/videos/generate"
                        body = {"prompt": prompt, "width": 832, "height": 480,
                                "length": 49, "steps": 12, "fps": 16, "seed": seed}
                        artifact = output_dir / f"media-{media_index + 1:02d}.mp4"
                    else:
                        path = "/api/images/generate"
                        body = {"prompt": prompt, "width": 1024, "height": 1024,
                                "steps": 28, "cfg": 6.0, "seed": seed,
                                "sampler": "dpmpp_2m", "scheduler": "karras"}
                        artifact = output_dir / f"media-{media_index + 1:02d}.png"
                    media_meta = {"media": "video" if make_video else "image",
                                  "prompt": prompt, "seed": seed}
                    media_future = pool.submit(media_request, args.base_url, path, body,
                                               artifact, args.media_timeout)
                    append_event(events, {"kind": "media_started", **media_meta})
                    media_index += 1
                    next_media = time.monotonic() + args.media_every

                snapshot = host_snapshot(output_dir)
                append_event(events, {"kind": "host", **snapshot})
                failure_rate = failures / requests
                if snapshot["disk_free_bytes"] < args.minimum_free_bytes:
                    stop_reason = "disk_safety_threshold"
                    break
                if consecutive_health_failures >= args.max_consecutive_failures:
                    stop_reason = "consecutive_health_failures"
                    break
                if requests >= 100 and failure_rate > args.max_failure_rate:
                    stop_reason = "failure_rate_threshold"
                    break
                elapsed = time.monotonic() - cycle_started
                time.sleep(max(0.0, batch_size / args.rps - elapsed))

            if media_future is not None:
                result = media_future.result(timeout=args.media_timeout + 5)
                requests += 1
                latencies.append(result["latency_ms"])
                if not result["ok"]:
                    failures += 1
                append_event(events, {"kind": "media_probe", **media_meta, **result})

        report = {
            "run_id": run_id, "started_at": run_id,
            "finished_at": utc_now(), "elapsed_seconds": round(time.monotonic() - started, 2),
            "planned_seconds": args.duration, "requests": requests, "failures": failures,
            "failure_rate": round(failures / requests, 6) if requests else 1.0,
            "latency_ms": {
                "mean": round(statistics.fmean(latencies), 2) if latencies else None,
                "p50": percentile(latencies, .50), "p95": percentile(latencies, .95),
                "p99": percentile(latencies, .99), "max": max(latencies) if latencies else None,
            },
            "stop_reason": stop_reason,
            "passed": stop_reason == "duration_complete" and failures / max(1, requests) <= args.max_failure_rate,
            "non_destructive": True, "events_path": str(events_path),
        }
        append_event(events, {"kind": "finish", **report})
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {**report, "report_path": str(report_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8788")
    parser.add_argument("--duration", type=int, default=14_400)
    parser.add_argument("--rps", type=float, default=4.0)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--model-timeout", type=float, default=180.0)
    parser.add_argument("--model-every", type=float, default=600.0)
    parser.add_argument("--media-every", type=float, default=1_800.0,
                        help="seconds between alternating image/video probes; 0 disables")
    parser.add_argument("--media-timeout", type=float, default=1_260.0)
    parser.add_argument("--max-failure-rate", type=float, default=.05)
    parser.add_argument("--max-consecutive-failures", type=int, default=3)
    parser.add_argument("--minimum-free-bytes", type=int, default=5_000_000_000)
    parser.add_argument("--output-dir", default="/tmp/orca-soak")
    args = parser.parse_args()
    if (args.duration < 10 or not .1 <= args.rps <= 20 or not 1 <= args.workers <= 32
            or args.media_every < 0 or (args.media_every and args.media_every < 300)):
        parser.error("duration, rps, or workers exceed bounded test limits")
    report = run(args)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
