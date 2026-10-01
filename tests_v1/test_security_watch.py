import sys
from pathlib import Path

repository = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repository / "deploy" / "kiln"))
from orca_security_watch import evaluate, inspect_units


def test_expected_exposure_is_healthy_and_advisory_only(tmp_path):
    unit = tmp_path / "safe.service"
    unit.write_text("NoNewPrivileges=true\nProtectSystem=strict\nProtectHome=true\n", encoding="utf-8")
    report = evaluate(
        [{"address": "0.0.0.0", "port": 3000}, {"address": "127.0.0.1", "port": 9999}],
        inspect_units([unit]),
        {3000},
        now=1000,
    )
    assert report["state"] == "healthy"
    assert report["secret_content_read"] is False
    assert report["changes_applied"] is False


def test_unexpected_public_listener_degrades():
    report = evaluate([{"address": "::", "port": 4444}], [], set(), now=1000)
    assert report["state"] == "degraded"
    assert report["findings"][0]["kind"] == "unexpected_public_listener"


def test_world_writable_unit_is_critical(tmp_path):
    unit = tmp_path / "bad.service"
    unit.write_text("NoNewPrivileges=true\n", encoding="utf-8")
    unit.chmod(0o666)
    report = evaluate([], inspect_units([unit]), set(), now=1000)
    assert report["state"] == "degraded"
    assert any(item["severity"] == "critical" for item in report["findings"])
