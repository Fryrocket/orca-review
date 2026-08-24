"""R11-F50: ORCA_PROFILE is a spoofable env var and must not be the sole
fail-closed gate for privilege enforcement on real Pi 5 hardware."""

import pytest

from mao import roles
from mao.errors import HardPrivilegeError
from mao.roles import PrivilegeBroker


def test_looks_like_pi5_hardware_true_on_matching_model(monkeypatch):
    monkeypatch.setattr(roles, "_read_device_model", lambda: "raspberry pi 5 model b rev 1.0")
    assert roles._looks_like_pi5_hardware() is True


def test_looks_like_pi5_hardware_false_on_other_model(monkeypatch):
    monkeypatch.setattr(roles, "_read_device_model", lambda: "raspberry pi 4 model b rev 1.4")
    assert roles._looks_like_pi5_hardware() is False


def test_looks_like_pi5_hardware_false_when_unreadable(monkeypatch):
    monkeypatch.setattr(roles, "_read_device_model", lambda: "")
    assert roles._looks_like_pi5_hardware() is False


def test_broker_refuses_enforce_false_on_detected_pi5_hardware_via_dev_profile(monkeypatch):
    """The exact F50 scenario: ORCA_PROFILE=dev on real Pi 5 hardware must
    not silently disable enforcement."""
    monkeypatch.setenv("ORCA_PROFILE", "dev")
    monkeypatch.setattr(roles, "_looks_like_pi5_hardware", lambda: True)
    with pytest.raises(HardPrivilegeError, match="Raspberry Pi 5 hardware"):
        PrivilegeBroker()


def test_broker_refuses_explicit_enforce_false_on_detected_pi5_hardware(monkeypatch):
    monkeypatch.delenv("ORCA_PROFILE", raising=False)
    monkeypatch.setattr(roles, "_looks_like_pi5_hardware", lambda: True)
    with pytest.raises(HardPrivilegeError, match="Raspberry Pi 5 hardware"):
        PrivilegeBroker(enforce=False)


def test_broker_allows_dev_profile_when_hardware_check_negative(monkeypatch):
    """Normal dev machines / CI (not a Pi) are unaffected."""
    monkeypatch.setenv("ORCA_PROFILE", "dev")
    monkeypatch.setattr(roles, "_looks_like_pi5_hardware", lambda: False)
    broker = PrivilegeBroker()
    assert broker.enforce is False


def test_broker_enforce_true_unaffected_by_hardware_check(monkeypatch):
    """enforce=True never triggers the hardware check at all."""
    monkeypatch.delenv("ORCA_PROFILE", raising=False)
    monkeypatch.setattr(
        roles, "_looks_like_pi5_hardware",
        lambda: (_ for _ in ()).throw(AssertionError("should not be called when enforce=True")),
    )
    broker = PrivilegeBroker(enforce=True)
    assert broker.enforce is True
