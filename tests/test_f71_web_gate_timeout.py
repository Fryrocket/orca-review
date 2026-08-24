"""R11-F71 ("web human gate timeout") — a crisp finding.

F70 closed HumanGate.timeout_sec (CLI input()). WebHumanGate is a
separate class used by examples/web_gate_demo.py: ask() started a
local HTTP form and then called Event.wait() with no timeout and no
timeout_sec constructor argument. An unattended run that uses
WebHumanGate as Orchestrator.human_gate hangs forever instead of
failing closed — the same unattended-hang F70 named, on a different
gate implementation that F70 did not cover.

timeout_sec=None (default) still waits unbounded (interactive demo).
When timeout_sec is set, wait is bounded and timeout raises
GateTimeoutError via fail_closed_timeout() (fail CLOSED), matching
HumanGate.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mao.errors import GateTimeoutError
from mao.human import GateDecision
from mao.web_gate import WebHumanGate


def test_timeout_fails_closed_promptly():
    """Absent human must not block past timeout_sec."""
    gate = WebHumanGate(host="127.0.0.1", port=0, timeout_sec=0.05)
    t0 = time.monotonic()
    with pytest.raises(GateTimeoutError, match="fail CLOSED"):
        gate.ask({"step": "sensitive"}, context="test")
    elapsed = time.monotonic() - t0
    assert elapsed < 0.25, (
        f"ask() took {elapsed:.3f}s to raise — timeout_sec=0.05 was not enforced"
    )


def test_timeout_sec_none_wait_is_unbounded():
    """Regression: timeout_sec=None must still wait forever (demo path),
    not inherit a hidden default timeout."""
    gate = WebHumanGate(host="127.0.0.1", port=0, timeout_sec=None)
    seen = {}

    def fake_wait(timeout=None):
        seen["timeout"] = timeout
        return True

    with patch.object(gate._event, "wait", side_effect=fake_wait):
        result = gate.ask({"step": "x"}, context="test")
    assert seen["timeout"] is None
    assert result.decision == GateDecision.SKIP


def test_gate_timeout_error_is_orca_error():
    from mao.errors import OrcaError

    assert issubclass(GateTimeoutError, OrcaError)
