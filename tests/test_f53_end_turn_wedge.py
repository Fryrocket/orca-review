"""R11-F53: end_turn(granter) previously only cleared _active_turn AFTER
self.revoke(granter, ...) returned. revoke() raises HardPrivilegeError for
an unauthorized granter (anyone but "grok"), so a single end_turn() call
with a wrong granter left _active_turn permanently set — every subsequent
start_turn() for ANY other agent then raised "turn already active" with no
way to recover except calling end_turn() again with the correct granter.
end_turn() now clears turn state unconditionally before attempting the
revoke, so a bad revoke attempt still raises (the caller still learns about
it) but no longer wedges the broker's turn tracking."""

import pytest

from mao.errors import HardPrivilegeError
from mao.roles import PrivilegeBroker


def test_end_turn_with_wrong_granter_still_raises():
    """The revoke authorization failure itself must still surface — this
    fix is about not wedging state, not about silencing the error."""
    b = PrivilegeBroker(enforce=True)
    b.start_turn("claude")
    with pytest.raises(HardPrivilegeError, match="Only Grok can revoke"):
        b.end_turn("not_grok")


def test_end_turn_with_wrong_granter_does_not_wedge_turn_state():
    """The exact F53 bug: this used to stay stuck forever."""
    b = PrivilegeBroker(enforce=True)
    b.start_turn("claude")
    with pytest.raises(HardPrivilegeError):
        b.end_turn("not_grok")
    assert b._active_turn is None
    # A different agent's turn must be startable right away, no wedge.
    b.start_turn("grok")
    assert b._active_turn == "grok"


def test_end_turn_with_correct_granter_still_works_normally():
    b = PrivilegeBroker(enforce=True)
    b.grant("grok", "claude", set(), human_approved=True)
    b.start_turn("claude")
    b.end_turn("grok")
    assert b._active_turn is None


def test_end_turn_with_no_active_turn_is_a_noop():
    b = PrivilegeBroker(enforce=True)
    b.end_turn("grok")
    assert b._active_turn is None


def test_repeated_wrong_granter_end_turn_does_not_compound():
    """Calling end_turn() with a wrong granter twice in a row must behave
    the same both times — no leftover state from the first bad call."""
    b = PrivilegeBroker(enforce=True)
    b.start_turn("claude")
    with pytest.raises(HardPrivilegeError):
        b.end_turn("not_grok")
    # Second start_turn + wrong-granter end_turn should behave identically.
    b.start_turn("ampere")
    with pytest.raises(HardPrivilegeError):
        b.end_turn("still_not_grok")
    assert b._active_turn is None
