"""Smoke tests for privilege and turn gating."""

import pytest

from mao.errors import HardPrivilegeError
from mao.roles import Privilege, PrivilegeBroker, TEAM


def test_team_has_four_agents():
    assert set(TEAM.keys()) == {"grok", "claude", "ampere", "relay"}


def test_claude_cannot_code_edit_by_default():
    b = PrivilegeBroker(enforce=True)
    assert not b.can("claude", Privilege.CODE_EDIT)


def test_grok_can_grant_and_revoke():
    b = PrivilegeBroker(enforce=True)
    b.grant("grok", "claude", {Privilege.CODE_EDIT}, note="t1", human_approved=True)
    assert b.can("claude", Privilege.CODE_EDIT)
    b.revoke("grok", "claude")
    assert not b.can("claude", Privilege.CODE_EDIT)


def test_only_grok_can_grant():
    b = PrivilegeBroker(enforce=True)
    with pytest.raises(HardPrivilegeError, match=r"Only Grok can propose grants"):
        b.grant("claude", "relay", {Privilege.FIRMWARE_EDIT}, human_approved=True)


def test_unknown_grant_target_refused():
    b = PrivilegeBroker(enforce=True)
    with pytest.raises(HardPrivilegeError, match=r"unknown grant target"):
        b.grant("grok", "not-an-agent", {Privilege.READ})


def test_turn_gating():
    b = PrivilegeBroker(enforce=True)
    b.start_turn("claude")
    b.require_turn("claude")
    with pytest.raises(HardPrivilegeError, match=r"no active turn"):
        b.require_turn("relay")
    b.end_turn()


def test_ampere_has_hardware_design():
    b = PrivilegeBroker(enforce=True)
    assert b.can("ampere", Privilege.HARDWARE_DESIGN)
