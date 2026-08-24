"""R11-F51: `enforce` was a plain public instance attribute on
PrivilegeBroker. Any code holding a reference to a broker could do
`broker.enforce = False` and disable all privilege checking instantly —
none of __init__'s fail-closed gates (ORCA_PROFILE=pi5 refusal, the R11-F50
Pi 5 hardware check) apply to a direct attribute reassignment, since those
only run once, at construction. `enforce` is now a read-only property
backed by `_enforce`; there is no supported way to flip it after
construction."""

import pytest

from mao.errors import HardPrivilegeError
from mao.roles import Privilege, PrivilegeBroker


def test_enforce_cannot_be_reassigned_after_construction():
    """The exact F51 bug: this used to silently succeed."""
    b = PrivilegeBroker(enforce=True)
    with pytest.raises(AttributeError):
        b.enforce = False
    assert b.enforce is True


def test_enforce_reassignment_blocked_does_not_weaken_actual_enforcement():
    """Confirms the property fix isn't just cosmetic — can()/require()
    still see the real, unchanged value after a blocked mutation attempt."""
    b = PrivilegeBroker(enforce=True)
    try:
        b.enforce = False
    except AttributeError:
        pass
    assert b.can("relay", Privilege.ORCHESTRATE) is False
    with pytest.raises(HardPrivilegeError):
        b.require("relay", Privilege.ORCHESTRATE)


def test_enforce_still_readable_normally():
    """The fix must not break the many internal/external reads of
    broker.enforce (status(), can(), require(), grant(), etc.)."""
    b_on = PrivilegeBroker(enforce=True)
    b_off = PrivilegeBroker(enforce=False)
    assert b_on.enforce is True
    assert b_off.enforce is False
    assert b_on.status()["enforce"] is True
    assert b_off.status()["enforce"] is False


def test_private_enforce_attribute_can_still_be_set_at_construction():
    """Sanity: __init__ itself (the only sanctioned path) still works —
    this isn't accidentally frozen shut entirely."""
    assert PrivilegeBroker(enforce=True).enforce is True
    assert PrivilegeBroker(enforce=False).enforce is False
