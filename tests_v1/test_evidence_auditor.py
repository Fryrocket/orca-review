import hashlib
import json
import sys
from pathlib import Path

repository = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repository / "deploy" / "kiln"))
from orca_evidence_auditor import evaluate


def test_idle_is_healthy_but_explicit(tmp_path):
    report = evaluate(tmp_path, now=1000)
    assert report["state"] == "healthy"
    assert report["mode"] == "idle"


def test_valid_envelope(tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    artifact = artifacts / "artifact.txt"
    artifact.write_text("verified evidence", encoding="utf-8")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "claim.json").write_text(json.dumps({
        "claim_id": "claim-1", "actor": "smith",
        "artifacts": [{"path": str(artifact), "sha256": digest}],
        "approvals": [],
    }), encoding="utf-8")
    report = evaluate(inbox, now=1000)
    assert report["state"] == "healthy"
    assert report["valid_count"] == 1


def test_tamper_and_malformed_fail_closed(tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    artifact = artifacts / "artifact.txt"
    artifact.write_text("tampered", encoding="utf-8")
    (tmp_path / "bad.json").write_text(json.dumps({
        "claim_id": "claim-2", "actor": "smith",
        "artifacts": [{"path": str(artifact), "sha256": "0" * 64}],
    }), encoding="utf-8")
    (tmp_path / "malformed.json").write_text("nope", encoding="utf-8")
    report = evaluate(tmp_path, now=1000)
    assert report["state"] == "degraded"
    assert report["valid_count"] == 0
