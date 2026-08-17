"""Human-in-the-loop gates. Unknown / timeout fail CLOSED (deny)."""

from __future__ import annotations

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
            choice = input("> ").strip().lower()
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


def fail_closed_timeout(note: str = "human gate timed out") -> GateResult:
    raise GateTimeoutError(f"{note} — fail CLOSED (deny)")
