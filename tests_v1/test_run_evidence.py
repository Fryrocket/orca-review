import json

from orca.run_evidence import EvidenceRunLog, verify_run_log


def test_run_log_is_hash_chained_and_redacts_secret_fields(tmp_path):
    path = tmp_path / "run.jsonl"
    with EvidenceRunLog(path, run_id="RUN-1") as log:
        log.append("start", {"token": "never-store-me", "nested": {"password": "nope"}})
        log.append("finish", {"passed": True})
    assert verify_run_log(path)["valid"] is True
    text = path.read_text()
    assert "never-store-me" not in text and "nope" not in text
    assert text.count("[REDACTED]") == 2


def test_run_log_detects_tampering(tmp_path):
    path = tmp_path / "run.jsonl"
    with EvidenceRunLog(path, run_id="RUN-1") as log:
        log.append("result", {"passed": True})
    row = json.loads(path.read_text())
    row["payload"]["passed"] = False
    path.write_text(json.dumps(row) + "\n")
    assert verify_run_log(path)["valid"] is False
