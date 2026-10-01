from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ember_tunnel_is_loopback_only_and_recovers_from_boot_network_races():
    unit = (ROOT / "deploy/ember/orca-forge-tunnel.service").read_text()
    assert "127.0.0.1:18787:127.0.0.1:18787" in unit
    assert "0.0.0.0:18787" not in unit
    assert "ConnectTimeout=8" in unit
    assert "ConnectionAttempts=1" in unit
    assert "Restart=always" in unit
    assert "After=network-online.target tailscaled.service" in unit
    assert "NoNewPrivileges=true" in unit
    assert "ProtectSystem=strict" in unit
    assert "CapabilityBoundingSet=" in unit
