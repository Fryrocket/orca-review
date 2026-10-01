import sys
from pathlib import Path

repository = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repository / "deploy" / "kiln"))
from orca_security_watch import (
    evaluate,
    inspect_units,
    read_protected_public_ports,
    read_ufw_enabled,
)


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


def test_protected_docker_listener_is_accepted_when_firewall_active():
    report = evaluate(
        [{"address": "0.0.0.0", "port": 6379}], [],
        firewall_active=True, protected_public_ports={6379}, now=1,
    )
    assert report["state"] == "healthy"
    assert report["public_listeners"] == [
        {"port": 6379, "accepted": True, "protected": True},
    ]


def test_read_protected_public_ports_requires_valid_attestation(tmp_path):
    attestation = tmp_path / "ports.json"
    attestation.write_text(
        '{"firewall":"ORCA-DOCKER-FILTER","protected_public_ports":[6379],"schema_version":1}'
    )
    assert read_protected_public_ports(attestation) == {6379}


def test_world_writable_unit_is_critical(tmp_path):
    unit = tmp_path / "bad.service"
    unit.write_text("NoNewPrivileges=true\n", encoding="utf-8")
    unit.chmod(0o666)
    report = evaluate([], inspect_units([unit]), set(), now=1000)
    assert report["state"] == "degraded"
    assert any(item["severity"] == "critical" for item in report["findings"])


def test_inactive_firewall_cannot_report_wildcard_listener_healthy():
    report = evaluate(
        [{"address": "0.0.0.0", "port": 3000}], [], {3000}, now=1000,
        firewall_active=False,
    )
    assert report["state"] == "degraded"
    assert report["firewall_active"] is False
    assert report["public_listeners"] == [
        {"port": 3000, "accepted": False, "protected": False},
    ]
    assert any(item["kind"] == "firewall_inactive" for item in report["findings"])


def test_ufw_config_read_is_fail_closed(tmp_path):
    config = tmp_path / "ufw.conf"
    config.write_text("# fixture\nENABLED=yes\n", encoding="utf-8")
    assert read_ufw_enabled(config) is True
    config.write_text("ENABLED=no\n", encoding="utf-8")
    assert read_ufw_enabled(config) is False
    assert read_ufw_enabled(tmp_path / "missing") is False
