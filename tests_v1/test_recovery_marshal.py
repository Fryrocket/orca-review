import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "deploy" / "ember"))
from recovery_marshal import evaluate

def write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")

def test_healthy_evidence(tmp_path):
    paths = {name: tmp_path / name for name in ("backup", "offsite", "restore")}
    write(paths["backup"], {"state":"healthy", "updated_epoch":900})
    write(paths["offsite"], {"state":"healthy", "updated_epoch":901})
    write(paths["restore"], {"state":"passed", "verified_epoch":902})
    report = evaluate(paths, now=1000, max_age=200)
    assert report["state"] == "healthy"
    assert report["alert_required"] is False
    assert report["alert_class"] is None

def test_missing_stale_malformed_and_failed_fail_closed(tmp_path):
    paths = {name: tmp_path / name for name in ("backup", "offsite", "restore")}
    write(paths["backup"], {"state":"healthy", "updated_epoch":1})
    paths["offsite"].write_text("not-json", encoding="utf-8")
    write(paths["restore"], {"state":"failed", "verified_epoch":999})
    report = evaluate(paths, now=1000, max_age=100)
    assert report["state"] == "degraded"
    assert not any(check["ok"] for check in report["checks"].values())
    assert report["alert_required"] is True
    assert report["alert_class"] == "backup_evidence_exception"
    assert report["authority"] == "read_only_evidence_observer"
