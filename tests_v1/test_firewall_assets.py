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
    assert "RuntimeDirectory=orca-kiln-docker-firewall" in unit
