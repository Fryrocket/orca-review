#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone


JOB_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
FILE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".mkv", ".avi"})
MAX_FILE_BYTES = 500 * 1024 * 1024
MAX_FRAMES = 150
MAX_TTL_SECONDS = 600

MODELS = {
    "yolov6n_h8": {
        "hef": "/usr/share/hailo-models/yolov6n_h8.hef",
        "post": "/usr/lib/aarch64-linux-gnu/hailo/tappas/post_processes/libyolo_hailortpp_post.so",
        "function": "filter", "config": None,
    },
    "yolov8s_h8": {
        "hef": "/usr/share/hailo-models/yolov8s_h8.hef",
        "post": "/usr/lib/aarch64-linux-gnu/hailo/tappas/post_processes/libyolo_hailortpp_post.so",
        "function": "yolov8s", "config": None,
    },
    "yolov5n_seg_h8": {
        "hef": "/usr/share/hailo-models/yolov5n_seg_h8.hef",
        "post": "/usr/lib/aarch64-linux-gnu/hailo/tappas/post_processes/libyolov5seg_post.so",
        "function": "yolov5seg", "config": "/usr/share/hailo-models/yolov5seg.json",
    },
    "yolov8s_pose_h8": {
        "hef": "/usr/share/hailo-models/yolov8s_pose_h8.hef",
        "post": "/usr/lib/aarch64-linux-gnu/hailo/tappas/post_processes/libyolov8pose_post.so",
        "function": "filter", "config": None,
    },
}


class RejectedJob(ValueError):
    pass


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def load_key(path: Path) -> bytes:
    try:
        key = bytes.fromhex(path.read_text().strip())
    except (OSError, ValueError) as exc:
        raise RejectedJob("job-signing key is unavailable") from exc
    if len(key) != 32:
        raise RejectedJob("job-signing key has an invalid length")
    return key


def sign_job(job: dict, key: bytes) -> str:
    return hmac.new(key, canonical_json(job), hashlib.sha256).hexdigest()


def _parse_time(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise RejectedJob(f"{field} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RejectedJob(f"{field} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise RejectedJob(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def validate_envelope(envelope: object, key: bytes, *, now: datetime | None = None) -> dict:
    if not isinstance(envelope, dict) or set(envelope) != {"job", "signature"}:
        raise RejectedJob("job envelope schema is invalid")
    job = envelope["job"]
    signature = envelope["signature"]
    expected_keys = {
        "schema", "job_id", "nonce", "created_at", "expires_at",
        "model_id", "input", "max_frames",
    }
    if not isinstance(job, dict) or set(job) != expected_keys:
        raise RejectedJob("job schema is invalid")
    if job["schema"] != 1:
        raise RejectedJob("job schema version is unsupported")
    if not isinstance(job["job_id"], str) or not JOB_ID.fullmatch(job["job_id"]):
        raise RejectedJob("job id is invalid")
    if type(job["nonce"]) is not int or job["nonce"] < 1:
        raise RejectedJob("job nonce is invalid")
    if job["model_id"] not in MODELS:
        raise RejectedJob("model is not allowlisted")
    if type(job["max_frames"]) is not int or not 1 <= job["max_frames"] <= MAX_FRAMES:
        raise RejectedJob("frame limit is invalid")
    created = _parse_time(job["created_at"], "created_at")
    expires = _parse_time(job["expires_at"], "expires_at")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if created > current + timedelta(seconds=60):
        raise RejectedJob("job creation time is in the future")
    if expires <= current:
        raise RejectedJob("job has expired")
    if expires <= created or (expires - created).total_seconds() > MAX_TTL_SECONDS:
        raise RejectedJob("job lifetime is invalid")
    input_spec = job["input"]
    if not isinstance(input_spec, dict) or input_spec.get("kind") not in {
            "synthetic_probe", "file", "camera"}:
        raise RejectedJob("input type is invalid")
    if input_spec["kind"] == "synthetic_probe" and set(input_spec) != {"kind"}:
        raise RejectedJob("synthetic input schema is invalid")
    if input_spec["kind"] in {"file", "camera"} and set(input_spec) != {"kind", "path"}:
        raise RejectedJob("input schema is invalid")
    if not isinstance(signature, str) or not hmac.compare_digest(
            signature, sign_job(job, key)):
        raise RejectedJob("job signature is invalid")
    return job


def _inside(path: Path, root: Path) -> Path:
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise RejectedJob("input path is outside the approved root") from exc
    return resolved


def validate_input(input_spec: dict, incoming: Path,
                   video_root: Path = Path("/sys/class/video4linux")) -> dict:
    kind = input_spec["kind"]
    if kind == "synthetic_probe":
        return {"kind": kind}
    if kind == "file":
        if not isinstance(input_spec["path"], str):
            raise RejectedJob("file path is invalid")
        path = _inside(Path(input_spec["path"]), incoming)
        if path.suffix.casefold() not in FILE_SUFFIXES or not path.is_file():
            raise RejectedJob("file type is not allowlisted")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise RejectedJob("input file exceeds the size limit")
        return {"kind": kind, "path": str(path)}
    if not isinstance(input_spec["path"], str) or not re.fullmatch(r"/dev/video\d+", input_spec["path"]):
        raise RejectedJob("camera device is invalid")
    device = Path(input_spec["path"])
    class_entry = video_root / device.name
    try:
        resolved = class_entry.resolve(strict=True)
        driver = (class_entry / "device" / "driver").resolve(strict=True).name
    except (FileNotFoundError, OSError):
        driver = ""
        resolved = Path("")
    if driver != "uvcvideo" and "/usb" not in str(resolved):
        raise RejectedJob("camera is not an external USB/UVC device")
    return {"kind": kind, "path": str(device)}


def build_pipeline(job: dict, source: dict, metadata_path: Path) -> list[str]:
    model = MODELS[job["model_id"]]
    frames = str(job["max_frames"])
    command = ["/usr/bin/gst-launch-1.0", "-q", "-e"]
    if source["kind"] == "synthetic_probe":
        command += ["videotestsrc", f"num-buffers={frames}", "pattern=smpte", "!"]
    elif source["kind"] == "camera":
        command += ["v4l2src", f"device={source['path']}", f"num-buffers={frames}", "!",
                    "image/jpeg,width=1280,height=720,framerate=30/1", "!", "jpegdec", "!",
                    "videoconvert", "!", "videoscale", "!", "videorate", "!"]
    else:
        command += ["filesrc", f"location={source['path']}", "!", "decodebin", "!",
                    "queue", "!", "videoconvert", "!", "videoscale", "!"]
        if Path(source["path"]).suffix.casefold() in {".jpg", ".jpeg", ".png", ".webp"}:
            command += ["imagefreeze", f"num-buffers={frames}", "!"]
        else:
            command += ["videorate", "!", "identity", f"eos-after={frames}", "!"]
    command += [
        "video/x-raw,format=RGB,width=640,height=640,framerate=5/1", "!",
        "hailonet", f"hef-path={model['hef']}", "batch-size=1", "scheduling-algorithm=0", "!",
        "hailofilter", f"so-path={model['post']}", f"function-name={model['function']}",
    ]
    if model["config"]:
        command.append(f"config-path={model['config']}")
    command += ["!", "hailoexportfile", f"location={metadata_path}", "!", "fakesink"]
    return command


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: object, mode: int = 0o640) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.new")
    temporary.write_bytes(canonical_json(payload) + b"\n")
    temporary.chmod(mode)
    temporary.replace(path)


def _read_nonce(path: Path) -> int:
    try:
        return int(path.read_text().strip())
    except FileNotFoundError:
        return 0
    except (OSError, ValueError) as exc:
        raise RejectedJob("nonce state is invalid") from exc


def _write_nonce(path: Path, nonce: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    temporary = path.with_name(f".{path.name}.new")
    temporary.write_text(f"{nonce}\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def execute_job(job: dict, source: dict, result_dir: Path) -> dict:
    result_dir.mkdir(parents=True, mode=0o750, exist_ok=False)
    metadata_path = result_dir / "metadata.json"
    command = build_pipeline(job, source, metadata_path)
    model_path = Path(MODELS[job["model_id"]]["hef"])
    for required in (model_path, Path(MODELS[job["model_id"]]["post"])):
        if not required.is_file():
            raise RejectedJob("accepted model dependency is unavailable")
    started = time.monotonic()
    timeout = min(90, max(20, job["max_frames"] / 5 + 15))
    completed = subprocess.run(
        command, capture_output=True, text=True, timeout=timeout,
        env={"PATH": "/usr/bin:/bin", "GST_DEBUG": "1"},
    )
    duration = round(time.monotonic() - started, 3)
    if completed.returncode != 0 or not metadata_path.is_file():
        raise RejectedJob("Hailo pipeline failed closed")
    try:
        metadata = json.loads(metadata_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise RejectedJob("Hailo metadata is invalid") from exc
    result = {
        "schema": 1,
        "job_id": job["job_id"],
        "status": "completed",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "model_id": job["model_id"],
        "model_sha256": sha256_file(model_path),
        "input": {"kind": source["kind"]},
        "requested_frames": job["max_frames"],
        "metadata_records": len(metadata) if isinstance(metadata, list) else 1,
        "metadata_sha256": sha256_file(metadata_path),
        "duration_seconds": duration,
        "automatic_external_action": False,
    }
    if source["kind"] == "file":
        result["input"]["sha256"] = sha256_file(Path(source["path"]))
    elif source["kind"] == "camera":
        result["input"]["device"] = source["path"]
    _atomic_json(result_dir / "result.json", result)
    return result


def process_next(*, queue: Path, incoming: Path, results: Path, rejected: Path,
                 key_file: Path, nonce_file: Path, lock_file: Path) -> dict:
    queue.mkdir(parents=True, exist_ok=True, mode=0o750)
    incoming.mkdir(parents=True, exist_ok=True, mode=0o750)
    results.mkdir(parents=True, exist_ok=True, mode=0o750)
    rejected.mkdir(parents=True, exist_ok=True, mode=0o750)
    lock_file.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    with lock_file.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "busy"}
        candidates = sorted(queue.glob("*.json"), key=lambda item: (item.stat().st_mtime_ns, item.name))
        if not candidates:
            return {"status": "idle"}
        path = candidates[0]
        try:
            envelope = json.loads(path.read_text())
            job = validate_envelope(envelope, load_key(key_file))
            if path.stem != job["job_id"]:
                raise RejectedJob("queue filename does not match job id")
            last_nonce = _read_nonce(nonce_file)
            if job["nonce"] <= last_nonce:
                raise RejectedJob("job nonce was replayed")
            result_path = results / job["job_id"]
            if result_path.exists():
                raise RejectedJob("job id was already used")
            source = validate_input(job["input"], incoming)
            _write_nonce(nonce_file, job["nonce"])
            result = execute_job(job, source, result_path)
            path.replace(result_path / "request.json")
            return result
        except (RejectedJob, json.JSONDecodeError, OSError, subprocess.TimeoutExpired) as exc:
            reject_dir = rejected / path.stem
            reject_dir.mkdir(parents=True, exist_ok=True, mode=0o750)
            if path.exists():
                path.replace(reject_dir / "request.json")
            payload = {
                "schema": 1, "job_id": path.stem, "status": "rejected",
                "rejected_at": datetime.now(timezone.utc).isoformat(),
                "error": str(exc) if isinstance(exc, RejectedJob) else "bounded broker failure",
            }
            _atomic_json(reject_dir / "result.json", payload)
            return payload


def enqueue_probe(*, job_id: str, model_id: str, queue: Path,
                  key_file: Path, nonce_file: Path) -> Path:
    if not JOB_ID.fullmatch(job_id) or model_id not in MODELS:
        raise RejectedJob("probe request is invalid")
    if (queue / f"{job_id}.json").exists():
        raise RejectedJob("probe job id already exists")
    now = datetime.now(timezone.utc)
    job = {
        "schema": 1, "job_id": job_id, "nonce": _read_nonce(nonce_file) + 1,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=5)).isoformat(),
        "model_id": model_id, "input": {"kind": "synthetic_probe"}, "max_frames": 1,
    }
    queue.mkdir(parents=True, exist_ok=True, mode=0o750)
    path = queue / f"{job_id}.json"
    _atomic_json(path, {"job": job, "signature": sign_job(job, load_key(key_file))})
    return path


def enqueue_camera(*, job_id: str, model_id: str, device: str, frames: int,
                   queue: Path, key_file: Path, nonce_file: Path) -> Path:
    if (not JOB_ID.fullmatch(job_id) or model_id not in MODELS
            or not re.fullmatch(r"/dev/video\d+", device)
            or type(frames) is not int or not 1 <= frames <= MAX_FRAMES):
        raise RejectedJob("camera request is invalid")
    if (queue / f"{job_id}.json").exists():
        raise RejectedJob("camera job id already exists")
    now = datetime.now(timezone.utc)
    job = {
        "schema": 1, "job_id": job_id, "nonce": _read_nonce(nonce_file) + 1,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=5)).isoformat(),
        "model_id": model_id, "input": {"kind": "camera", "path": device},
        "max_frames": frames,
    }
    queue.mkdir(parents=True, exist_ok=True, mode=0o750)
    path = queue / f"{job_id}.json"
    _atomic_json(path, {"job": job, "signature": sign_job(job, load_key(key_file))})
    return path


def enqueue_file(*, job_id: str, model_id: str, path: str, frames: int,
                 queue: Path, key_file: Path, nonce_file: Path) -> Path:
    if (not JOB_ID.fullmatch(job_id) or model_id not in MODELS
            or not isinstance(path, str) or not path
            or type(frames) is not int or not 1 <= frames <= MAX_FRAMES):
        raise RejectedJob("file request is invalid")
    if (queue / f"{job_id}.json").exists():
        raise RejectedJob("file job id already exists")
    now = datetime.now(timezone.utc)
    job = {
        "schema": 1, "job_id": job_id, "nonce": _read_nonce(nonce_file) + 1,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=5)).isoformat(),
        "model_id": model_id, "input": {"kind": "file", "path": path},
        "max_frames": frames,
    }
    queue.mkdir(parents=True, exist_ok=True, mode=0o750)
    output = queue / f"{job_id}.json"
    _atomic_json(output, {"job": job, "signature": sign_job(job, load_key(key_file))})
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", type=Path, default=Path("/var/lib/orca-temper"))
    parser.add_argument("--enqueue-probe")
    parser.add_argument("--enqueue-camera")
    parser.add_argument("--enqueue-file")
    parser.add_argument("--device", default="/dev/video0")
    parser.add_argument("--input-path")
    parser.add_argument("--frames", type=int, default=10)
    parser.add_argument("--model", default="yolov6n_h8", choices=sorted(MODELS))
    args = parser.parse_args()
    root = args.state_root
    key = root / "hailo-job.key"
    nonce = root / "hailo-job-nonce"
    queue = root / "jobs/queue"
    if args.enqueue_probe:
        print(enqueue_probe(job_id=args.enqueue_probe, model_id=args.model, queue=queue,
                            key_file=key, nonce_file=nonce))
        return 0
    if args.enqueue_camera:
        print(enqueue_camera(
            job_id=args.enqueue_camera, model_id=args.model, device=args.device,
            frames=args.frames, queue=queue, key_file=key, nonce_file=nonce))
        return 0
    if args.enqueue_file:
        if not args.input_path:
            raise RejectedJob("file input path is required")
        print(enqueue_file(
            job_id=args.enqueue_file, model_id=args.model, path=args.input_path,
            frames=args.frames, queue=queue, key_file=key, nonce_file=nonce))
        return 0
    result = process_next(
        queue=queue, incoming=root / "jobs/incoming", results=root / "jobs/results",
        rejected=root / "jobs/rejected", key_file=key, nonce_file=nonce,
        lock_file=root / "hailo-job.lock",
    )
    print(json.dumps(result, sort_keys=True))
    # A recorded rejection is a successful fail-closed security disposition,
    # not a broker service crash.  Keep the timer healthy while preserving the
    # typed rejection evidence for operators.
    return 0 if result["status"] in {"idle", "busy", "completed", "rejected"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
