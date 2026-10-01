from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_kiln_docker_firewall_is_scoped_and_fail_closed():
    script = (ROOT / "deploy/kiln/orca_kiln_docker_firewall.sh").read_text()
    assert "set -eu" in script
    assert "LAN=192.168.4.0/22" in script
    assert "--dport 6379 -j DROP" in script
    assert "-i tailscale0" in script
    assert "-i br+ -j RETURN" in script
    assert "if $IP6T -nL DOCKER-USER" in script
    assert "protected_public_ports" in script
    assert "-j DROP" in script
    assert "0.0.0.0/0 -j ACCEPT" not in script


def test_kiln_docker_firewall_service_has_narrow_capabilities():
    unit = (ROOT / "deploy/kiln/orca-kiln-docker-firewall.service").read_text()
    assert "NoNewPrivileges=true" in unit
    assert "ProtectSystem=strict" in unit
    assert "ProtectHome=true" in unit
    assert "CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_RAW" in unit
    assert "RemainAfterExit=yes" in unit
    assert "StateDirectory=orca-kiln-docker-firewall" in unit
    assert "RuntimeDirectory=orca-kiln-docker-firewall" not in unit
    assert "PartOf=docker.service" in unit


def test_docker_restart_reapplies_the_orca_filter():
    dropin = (ROOT / "deploy/kiln/20-orca-firewall.conf").read_text()
    assert "Wants=orca-kiln-docker-firewall.service" in dropin


def test_firewall_attestation_survives_runtime_directory_cleanup():
    script = (ROOT / "deploy/kiln/orca_kiln_docker_firewall.sh").read_text()
    watcher = (ROOT / "deploy/kiln/orca_security_watch.py").read_text()
    persistent_path = "/var/lib/orca-kiln-docker-firewall/protected-ports.json"
    assert persistent_path in script
    assert persistent_path in watcher
    assert "/run/orca-kiln-docker-firewall/protected-ports.json" not in script
    assert "/run/orca-kiln-docker-firewall/protected-ports.json" not in watcher
