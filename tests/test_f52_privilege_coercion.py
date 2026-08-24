"""R11-F52: Privilege subclasses str, so raw strings hash/compare equal to
real Privilege members — set ops (in, &, -) silently accept either. But
code that calls .value on a stored privilege (status(), require()'s deny
message, grant()'s sensitive-grant message) crashed with AttributeError if
a raw string ever entered _grants, and grant() accepted completely bogus
privilege strings with zero validation. Entry points now coerce to real
Privilege enum members."""

import pytest

from mao.errors import HardPrivilegeError
from mao.roles import Privilege, PrivilegeBroker


def test_grant_rejects_unknown_privilege_string():
    b = PrivilegeBroker(enforce=True)
    with pytest.raises(HardPrivilegeError, match="unknown privilege"):
        b.grant("grok", "claude", {"super_admin_bypass_everything"}, human_approved=False)
    assert "claude" not in b._grants


def test_grant_with_raw_string_sensitive_privilege_still_denied_cleanly():
    """Previously crashed with AttributeError instead of HardPrivilegeError."""
    b = PrivilegeBroker(enforce=True)
    with pytest.raises(HardPrivilegeError, match="Sensitive grant"):
        b.grant("grok", "claude", {"code_edit"}, human_approved=False)
    assert "claude" not in b._grants


def test_grant_with_raw_string_nonsensitive_privilege_is_canonicalized():
    b = PrivilegeBroker(enforce=True)
    b.grant("grok", "claude", {"read"}, human_approved=False)
    assert b._grants["claude"] == {Privilege.READ}
    assert all(isinstance(p, Privilege) for p in b._grants["claude"])


def test_status_does_not_crash_after_raw_string_grant():
    """Previously crashed with AttributeError: 'str' object has no attribute 'value'."""
    b = PrivilegeBroker(enforce=True)
    b.grant("grok", "claude", {"read"}, human_approved=False)
    status = b.status()
    assert status["agents"]["claude"]["granted"] == ["read"]


def test_require_deny_path_with_raw_string_priv_does_not_crash():
    """Previously crashed with AttributeError instead of a clean deny."""
    b = PrivilegeBroker(enforce=True)
    with pytest.raises(HardPrivilegeError, match="claude lacks code_edit"):
        b.require("claude", "code_edit")


def test_can_with_raw_string_priv_matches_enum_priv():
    b = PrivilegeBroker(enforce=True)
    b.grant("grok", "claude", {Privilege.CODE_EDIT}, human_approved=True)
    assert b.can("claude", "code_edit") is True
    assert b.can("claude", Privilege.CODE_EDIT) is True


def test_can_rejects_unknown_privilege_string_even_when_not_enforcing():
    b = PrivilegeBroker(enforce=False)
    with pytest.raises(HardPrivilegeError, match="unknown privilege"):
        b.can("claude", "not_a_real_privilege")
