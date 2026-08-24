"""Human-in-the-loop gates. Unknown / timeout fail CLOSED (deny)."""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Any
from enum import Enum

from .errors import GateTimeoutError


class GateDecision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    EDIT = "edit"
    SKIP = "skip"  # treated as reject by Orchestrator (fail closed)


@dataclass
class GateResult:
    decision: GateDecision
    content: Any = None
    note: str = ""


class HumanGate:
    """CLI gate. Unknown input is REJECT, never an implicit pass."""

    def __init__(self, prompt: str = "Approve this step?", timeout_sec: float | None = None):
        self.prompt = prompt
        self.timeout_sec = timeout_sec

    def ask(self, payload: Any, context: str = "") -> GateResult:
        print("\n========== HUMAN GATE ==========")
        if context:
            print(f"Context: {context}")
        print(f"Payload:\n{payload}")
        print("================================")
        print("[a]pprove  [r]eject  [e]dit")
        try:
            choice = self._read_line("> ").strip().lower()
        except EOFError:
            return GateResult(GateDecision.REJECT, note="eof fail-closed")

        if choice in ("a", "approve", "y", "yes"):
            return GateResult(GateDecision.APPROVE, content=payload)
        if choice in ("r", "reject", "n", "no"):
            try:
                note = input("Rejection note (optional): ").strip()
            except EOFError:
                note = "eof"
            return GateResult(GateDecision.REJECT, note=note)
        if choice in ("e", "edit"):
            print("Enter edited content (end with empty line):")
            lines = []
            while True:
                try:
                    line = input()
                except EOFError:
                    break
                if line == "":
                    break
                lines.append(line)
            return GateResult(GateDecision.EDIT, content="\n".join(lines))
        return GateResult(
            GateDecision.REJECT, note=f"unknown choice {choice!r} — fail closed"
        )

    def _read_line(self, prompt_str: str) -> str:
        """input(), bounded by self.timeout_sec when set.

        R11-F70: timeout_sec was accepted by __init__ and stored but never
        enforced anywhere — ask() called plain input() and blocked
        indefinitely regardless of the configured timeout, contradicting
        this module's own docstring ("Unknown / timeout fail CLOSED").
        An unattended run with human_approved=True (F25/F57) would hang
        forever instead of failing closed. Runs input() in a daemon thread
        so an unanswered prompt cannot leak a foreground thread; on timeout,
        calls fail_closed_timeout() (raises GateTimeoutError) rather than
        returning a GateResult — a timeout is an exceptional non-decision,
        not an implicit reject the caller could quietly proceed past.
        """
        if self.timeout_sec is None:
            return input(prompt_str)

        result: "queue.Queue[tuple[str, Any]]" = queue.Queue(maxsize=1)

        def _worker() -> None:
            try:
                result.put(("ok", input(prompt_str)))
            except EOFError:
                result.put(("eof", None))
            except Exception as e:  # pragma: no cover - defensive
                result.put(("error", e))

        threading.Thread(target=_worker, daemon=True).start()
        try:
            kind, value = result.get(timeout=self.timeout_sec)
        except queue.Empty:
            fail_closed_timeout(
                f"no response within {self.timeout_sec}s"
            )  # always raises GateTimeoutError
        if kind == "eof":
            raise EOFError()
        if kind == "error":
            raise value
        return value


def fail_closed_timeout(note: str = "human gate timed out") -> GateResult:
    raise GateTimeoutError(f"{note} — fail CLOSED (deny)")
