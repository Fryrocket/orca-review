import hashlib
import importlib.util
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "deploy/temper/temper_hailo_broker.py"
SPEC = importlib.util.spec_from_file_location("temper_hailo_broker", SCRIPT)
BROKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BROKER)


def make_job(key=b"k" * 32, **overrides):
    now = datetime.now(timezone.utc)
    job = {
        "schema": 1, "job_id": "probe-1", "nonce": 1,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=5)).isoformat(),
        "model_id": "yolov6n_h8", "input": {"kind": "synthetic_probe"},
        "max_frames": 1,
    }
    job.update(overrides)
    return {"job": job, "signature": BROKER.sign_job(job, key)}


def test_signed_job_validation_fails_closed():
    key = b"k" * 32
    assert BROKER.validate_envelope(make_job(key), key)["job_id"] == "probe-1"
    bad = make_job(key)
    bad["signature"] = "0" * 64
    with pytest.raises(BROKER.RejectedJob, match="signature"):
        BROKER.validate_envelope(bad, key)
    with pytest.raises(BROKER.RejectedJob, match="frame limit"):
        BROKER.validate_envelope(make_job(key, max_frames=151), key)
    with pytest.raises(BROKER.RejectedJob, match="allowlisted"):
        BROKER.validate_envelope(make_job(key, model_id="arbitrary.hef"), key)


def test_file_and_camera_inputs_are_strictly_scoped(tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    image = incoming / "board.jpg"
    image.write_bytes(b"jpg")
    assert BROKER.validate_input({"kind": "file", "path": str(image)}, incoming)["path"] == str(image)
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"jpg")
    with pytest.raises(BROKER.RejectedJob, match="approved root"):
        BROKER.validate_input({"kind": "file", "path": str(outside)}, incoming)
    with pytest.raises(BROKER.RejectedJob, match="USB/UVC"):
        BROKER.validate_input({"kind": "camera", "path": "/dev/video0"}, incoming,
                              tmp_path / "no-video-devices")


def test_pipeline_uses_only_allowlisted_model_and_metadata_output(tmp_path):
    job = make_job()["job"]
    command = BROKER.build_pipeline(job, {"kind": "synthetic_probe"}, tmp_path / "meta.json")
    joined = " ".join(command)
    assert command[0] == "/usr/bin/gst-launch-1.0"
    assert "yolov6n_h8.hef" in joined
    assert "hailoexportfile" in command
    assert "fakesink" in command
    assert "scheduling-algorithm=0" in command
    assert not any("sh" == part or "bash" == part for part in command)


def test_queue_rejects_replayed_nonce_without_running_pipeline(tmp_path, monkeypatch):
    root = tmp_path / "state"
    queue = root / "jobs/queue"
    queue.mkdir(parents=True)
    key = b"k" * 32
    (root / "hailo-job.key").write_text(key.hex())
    (root / "hailo-job-nonce").write_text("1\n")
    (queue / "probe-1.json").write_text(json.dumps(make_job(key)))
    monkeypatch.setattr(BROKER, "execute_job", lambda *args, **kwargs: pytest.fail("must not run"))
    result = BROKER.process_next(
        queue=queue, incoming=root / "jobs/incoming", results=root / "jobs/results",
        rejected=root / "jobs/rejected", key_file=root / "hailo-job.key",
        nonce_file=root / "hailo-job-nonce", lock_file=root / "hailo-job.lock")
    assert result["status"] == "rejected"
    assert result["error"] == "job nonce was replayed"


def test_successful_job_records_provenance_and_moves_request(tmp_path, monkeypatch):
    root = tmp_path / "state"
    queue = root / "jobs/queue"
    queue.mkdir(parents=True)
    key = b"k" * 32
    (root / "hailo-job.key").write_text(key.hex())
    (queue / "probe-1.json").write_text(json.dumps(make_job(key)))
    def execute(job, source, result_dir):
        result_dir.mkdir(parents=True)
        result = {"status": "completed", "job_id": job["job_id"]}
        BROKER._atomic_json(result_dir / "result.json", result)
        return result
    monkeypatch.setattr(BROKER, "execute_job", execute)
    result = BROKER.process_next(
        queue=queue, incoming=root / "jobs/incoming", results=root / "jobs/results",
        rejected=root / "jobs/rejected", key_file=root / "hailo-job.key",
        nonce_file=root / "hailo-job-nonce", lock_file=root / "hailo-job.lock")
    assert result == {"status": "completed", "job_id": "probe-1"}
    assert (root / "jobs/results/probe-1/request.json").is_file()
    assert (root / "hailo-job-nonce").read_text() == "1\n"
