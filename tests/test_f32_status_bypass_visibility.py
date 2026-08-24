"""R11-F32: PARTIAL — "grant-when-unenforced + status exposing bypass".

Investigated broadly (see TO_GROK_F32_status_bypass_2026-08-24 for the full
writeup of what was checked and ruled out). The concrete, testable gap: when
enforce=False, can()/require() give EVERY agent unconditional access
regardless of _grants — not just agents that had grant() called on them. But
status()'s old `enforce_bypass` field only reported True for agents present
in the internal _bypassed set (populated only by grant() calls), so an
agent with zero grants showed `enforce_bypass: False` and
`effective: ["read"]` — reading as "restricted to read" — while
can(agent, ANYTHING) was actually True. status() now reports enforce_bypass
per-agent as `not self.enforce`, since the bypass is global, not per-target.
Do NOT re-close this by removing/hiding the field — the fix here is to make
it MORE accurate, not less visible."""

from mao.roles import Privilege, PrivilegeBroker


def test_ungranted_agent_shows_enforce_bypass_true_when_unenforced():
    """The exact gap: an agent nobody ever called grant() on must still show
    enforce_bypass=True when enforce=False, because can() actually gives it
    full access regardless."""
    b = PrivilegeBroker(enforce=False)
    assert b.can("relay", Privilege.ORCHESTRATE) is True
    assert b.status()["agents"]["relay"]["enforce_bypass"] is True


def test_enforce_bypass_true_for_every_agent_when_unenforced():
    b = PrivilegeBroker(enforce=False)
    for name in ("grok", "claude", "ampere", "relay"):
        assert b.status()["agents"][name]["enforce_bypass"] is True


def test_enforce_bypass_false_for_every_agent_when_enforced_and_ungranted():
    b = PrivilegeBroker(enforce=True)
    for name in ("grok", "claude", "ampere", "relay"):
        assert b.status()["agents"][name]["enforce_bypass"] is False


def test_grant_with_human_approval_still_shows_false_bypass_when_enforced():
    """Confirms the fix didn't accidentally make enforce_bypass track
    "was ever granted" instead of "is enforcement actually off"."""
    b = PrivilegeBroker(enforce=True)
    b.grant("grok", "claude", {Privilege.CODE_EDIT}, human_approved=True)
    assert b.status()["agents"]["claude"]["enforce_bypass"] is False
    assert b.status()["agents"]["claude"]["human_approved"] is True


def test_preexisting_unenforced_grant_behavior_unchanged():
    """Regression guard for the existing test_enforce_false_does_not_forge_
    human_approved in test_round6.py — same scenario, must keep passing."""
    b = PrivilegeBroker(enforce=False)
    b.grant("grok", "claude", {Privilege.CODE_EDIT}, human_approved=False)
    st = b.status()
    assert st["agents"]["claude"]["human_approved"] is False
    assert st["agents"]["claude"]["enforce_bypass"] is True
