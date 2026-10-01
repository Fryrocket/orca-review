import pytest

from orca.autonomous_security import PROFILES, assess_node, firewall_plan


def test_profiles_cover_the_whole_verified_fleet():
    assert set(PROFILES) == {"anvil", "forge", "kiln", "ember", "temper"}


def test_healthy_forge_is_a_pass():
    assessment = assess_node(
        node_id="forge", firewall_active=True,
        listeners=[
            {"address": "192.168.7.30", "port": 22},
            {"address": "192.168.7.30", "port": 2222},
            {"address": "192.168.7.30", "port": 3000},
            {"address": "127.0.0.1", "port": 8787},
            {"address": "127.0.0.1", "port": 8790},
            {"address": "127.0.0.1", "port": 8188},
            {"address": "127.0.0.1", "port": 11436},
        ],
        sshd={"passwordauthentication": "no", "permitrootlogin": "no"},
        unattended_updates_active=True, intrusion_throttling_active=True,
    )
    assert assessment.disposition == "pass"
    assert not assessment.findings


def test_inactive_firewall_password_ssh_and_public_service_block_activation():
    assessment = assess_node(
        node_id="temper", firewall_active=False,
        listeners=[
            {"address": "0.0.0.0", "port": 22},
            {"address": "127.0.0.1", "port": 8088},
            {"address": "0.0.0.0", "port": 1883},
            {"address": "0.0.0.0", "port": 41883},
            {"address": "0.0.0.0", "port": 8501},
        ],
        sshd={"passwordauthentication": "yes", "permitrootlogin": "without-password"},
        unattended_updates_active=False, intrusion_throttling_active=False,
    )
    assert assessment.disposition == "block_activation"
    check_ids = {item.check_id for item in assessment.findings}
    assert {"firewall-inactive", "ssh-password-enabled", "listener-unapproved",
            "listener-overbroad"} <= check_ids


def test_loopback_unknown_service_is_not_treated_as_remote_exposure():
    assessment = assess_node(
        node_id="anvil", firewall_active=True,
        listeners=[
            {"address": "127.0.0.1", "port": 8788},
            {"address": "127.0.0.1", "port": 11434},
            {"address": "127.0.0.1", "port": 45678},
        ],
    )
    assert assessment.disposition == "pass"


def test_malformed_listener_fails_visibly():
    assessment = assess_node(
        node_id="ember", firewall_active=True,
        listeners=[{"address": "127.0.0.1"}],
        sshd={"passwordauthentication": "no", "permitrootlogin": "no"},
        unattended_updates_active=True, intrusion_throttling_active=True,
    )
    assert any(item.check_id == "listener-malformed" for item in assessment.findings)


def test_firewall_plan_is_deterministic_and_never_applies_changes():
    first = firewall_plan("kiln")
    second = firewall_plan("kiln")
    assert first == second
    assert first["changes_applied"] is False
    assert first["requires_verified_rollback"] is True
    assert any("Docker-USER" in action for action in first["actions"])
    with pytest.raises(ValueError, match="unknown"):
        firewall_plan("unknown")
