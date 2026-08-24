"""R11-F70 ("human gate timeout") — a crisp finding.

human.py's own module docstring promises "Unknown / timeout fail CLOSED
(deny)." HumanGate.__init__ accepts and stores `timeout_sec`, but
`ask()` never used it anywhere — the approve/reject/edit prompt called
plain `input()`, which blocks indefinitely no matter what `timeout_sec`
was configured to. `fail_closed_timeout()` (which raises GateTimeoutError)
was defined but never called by anything in the codebase.

orchestrator.py calls `self.human_gate.ask(...)` directly for any run with
`human_approved=True` (F25/F57 — the gate that authorizes SENSITIVE_GRANTS
privilege elevation). An unattended run that reaches that gate with no
human present would hang forever instead of failing closed after the
configured timeout, exactly contradicting this module's own stated
guarantee.

Fix: HumanGate._read_line() runs input() in a daemon thread and bounds
the wait with a Queue.get(timeout=self.timeout_sec); on timeout it calls
fail_closed_timeout() (raises GateTimeoutError) instead of returning
normally. Only the primary approve/reject/edit prompt is bounded — the
follow-up rejection-note/edit-content prompts only run after a human has
already engaged with the gate, which is a different situation than an
absent human never showing up at all.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mao.errors import GateTimeoutError
from mao.human import GateDecision, HumanGate


def test_timeout_fails_closed_promptly():
    """The bug: a slow/absent human must not be able to block past
    timeout_sec. Must raise GateTimeoutError near timeout_sec, not near
    however long input() actually takes to return."""

    def slow_input(prompt=""):
        time.sleep(0.3)
        return "y"

    gate = HumanGate(timeout_sec=0.05)
    t0 = time.monotonic()
    with patch("builtins.input", side_effect=slow_input):
        with pytest.raises(GateTimeoutError):
            gate.ask("do the sensitive thing", context="test")
    elapsed = time.monotonic() - t0
    assert elapsed < 0.2, (
        f"ask() took {elapsed:.3f}s to raise — timeout_sec=0.05 was not enforced "
        "promptly (it waited for the slow input() call instead)"
    )


def test_fast_response_within_timeout_still_works():
    """Regression: a human who responds in time still gets a normal result —
    the timeout machinery must not interfere with the happy path."""

    def fast_input(prompt=""):
        return "a"

    gate = HumanGate(timeout_sec=5.0)
    with patch("builtins.input", side_effect=fast_input):
        result = gate.ask("do the thing", context="test")
    assert result.decision == GateDecision.APPROVE


def test_no_timeout_configured_is_unaffected():
    """Regression: timeout_sec=None (the default) must behave exactly as
    before — plain input(), no thread, no behavior change."""

    def fast_input(prompt=""):
        return "r"

    gate = HumanGate(timeout_sec=None)
    with patch("builtins.input", side_effect=fast_input):
        result = gate.ask("do the thing", context="test")
    assert result.decision == GateDecision.REJECT


def test_eof_still_fails_closed_with_timeout_configured():
    """Regression: EOF (e.g. piped-empty stdin) must still fail closed even
    when a timeout is configured, not raise GateTimeoutError instead."""

    def eof_input(prompt=""):
        raise EOFError()

    gate = HumanGate(timeout_sec=5.0)
    with patch("builtins.input", side_effect=eof_input):
        result = gate.ask("do the thing", context="test")
    assert result.decision == GateDecision.REJECT
    assert "eof" in result.note
