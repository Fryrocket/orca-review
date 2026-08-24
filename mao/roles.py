"""Orca team roles + PrivilegeBroker."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Set

from .errors import HardPrivilegeError, OrcaConfigError

_PI5_MODEL_PATHS = ("/proc/device-tree/model", "/sys/firmware/devicetree/base/model")


def _read_device_model() -> str:
    """Best-effort read of the Linux device-tree model string.

    Returns "" on any failure (wrong OS, no permission, not a Pi) — callers
    must treat that as "unknown", not "confirmed non-Pi".
    """
    for path in _PI5_MODEL_PATHS:
        try:
            with open(path, "rb") as f:
                return f.read().decode("utf-8", "ignore").strip("\x00").lower()
        except OSError:
            continue
    return ""


def _looks_like_pi5_hardware() -> bool:
    """Independent hardware check — ORCA_PROFILE is a self-reported env var
    and must not be the only fail-closed gate (R11-F50): setting
    ORCA_PROFILE=dev/test must not be able to silently disable enforcement
    on hardware that is actually a Pi 5.
    """
    return "raspberry pi 5" in _read_device_model()


class Privilege(str, Enum):
    READ = "read"
    WRITE = "write"
    CODE_EDIT = "code_edit"
    FIRMWARE_EDIT = "firmware_edit"
    HARDWARE_DESIGN = "hardware_design"
    APPROVE_WRITE = "approve_write"
    ORCHESTRATE = "orchestrate"
    UNCLASSIFIED = "unclassified"  # sentinel: held by nobody, grantable by nobody


SENSITIVE_GRANTS = {
    Privilege.WRITE,          # R11-F31: Blackboard default guard checks this
    Privilege.CODE_EDIT,
    Privilege.FIRMWARE_EDIT,
    Privilege.APPROVE_WRITE,
    Privilege.HARDWARE_DESIGN,
    Privilege.ORCHESTRATE,    # R11-F31
}


def _coerce_privilege(p) -> Privilege:
    """Canonicalize a privilege to a real Privilege enum member (R11-F52).

    Because Privilege subclasses str, a raw string like "write" hashes and
    compares equal to Privilege.WRITE, so set ops (`in`, `&`, `-`) silently
    accept either — but code that calls `.value` on a stored privilege
    (status(), require()'s deny message, grant()'s own sensitive-grant
    message) crashes with AttributeError if a raw string ever got stored.
    Coercing at the entry point means _grants only ever holds real enum
    members, and a bogus/unknown privilege string is rejected outright
    instead of being silently accepted as if it were a real grant.
    """
    if isinstance(p, Privilege):
        return p
    try:
        return Privilege(p)
    except ValueError as e:
        raise HardPrivilegeError(f"unknown privilege {p!r}") from e


@dataclass
class JobDuty:
    name: str
    title: str
    talent: str = ""
    description: str = ""
    privileges: Set[Privilege] = field(default_factory=set)
    system_prompt: str = ""
    tools_allowed: list = field(default_factory=list)


GROK = JobDuty(
    name="grok",
    title="Head / PM / Architect",
    privileges={
        Privilege.READ,
        Privilege.WRITE,
        Privilege.CODE_EDIT,
        Privilege.FIRMWARE_EDIT,
        Privilege.HARDWARE_DESIGN,
        Privilege.APPROVE_WRITE,
        Privilege.ORCHESTRATE,
    },
    system_prompt="You are Grok — Head. Propose grants; Fry approves sensitive ones.",
    tools_allowed=["*"],
)
CLAUDE = JobDuty(
    name="claude",
    title="Application & Tooling Engineer",
    privileges={Privilege.READ},
    system_prompt="You are Claude — coding specialist.",
    tools_allowed=["read_file", "search_code", "run_tests"],
)
AMPERE = JobDuty(
    name="ampere",
    title="Electronics Design Lead",
    privileges={Privilege.READ, Privilege.HARDWARE_DESIGN},
    system_prompt="You are Ampere — hardware. UNVERIFIED drafts only.",
    tools_allowed=["read_file", "write_design", "kicad_note", "kicad_gen", "bom_update"],
)
RELAY = JobDuty(
    name="relay",
    title="Embedded Firmware & Bring-up",
    privileges={Privilege.READ},
    system_prompt="You are Relay — firmware.",
    tools_allowed=["read_file", "search_code", "flash_note", "pinout_check"],
)
TEAM: Dict[str, JobDuty] = {d.name: d for d in (GROK, CLAUDE, AMPERE, RELAY)}

# R11-F54: was a bare `assert`, which `python -O` / PYTHONOPTIMIZE strips
# entirely — this invariant (nobody holds the UNCLASSIFIED sentinel) would
# silently stop being checked on an optimized run. Use a real conditional
# raise so it can't be compiled away.
if any(Privilege.UNCLASSIFIED in d.privileges for d in TEAM.values()):
    raise OrcaConfigError(
        "UNCLASSIFIED is a sentinel privilege and must not be held by any "
        "JobDuty in TEAM — check the TEAM role definitions above"
    )


class PrivilegeBroker:
    def __init__(self, enforce: Optional[bool] = None):
        profile = (os.environ.get("ORCA_PROFILE") or "").lower()
        if enforce is None:
            enforce = profile not in {"dev", "test", "local"}
        if profile in {"pi5", "pi", "power"} and not enforce:
            raise HardPrivilegeError("ORCA_PROFILE=pi5 refuses enforce=False")
        if not enforce and _looks_like_pi5_hardware():
            raise HardPrivilegeError(
                "detected Raspberry Pi 5 hardware via device-tree model — "
                "refusing enforce=False regardless of ORCA_PROFILE; a "
                "spoofable env var must not disable privilege enforcement "
                "on real Pi hardware (R11-F50)"
            )
        self._enforce = bool(enforce)
        self._grants: Dict[str, Set[Privilege]] = {}
        self._notes: Dict[str, str] = {}
        self._active_turn: Optional[str] = None
        self._human_approved_grants: Set[str] = set()
        self._bypassed: Set[str] = set()

    @property
    def enforce(self) -> bool:
        """Read-only (R11-F51): `enforce` was a plain public attribute, so
        any code holding a broker reference could do `broker.enforce = False`
        and disable all privilege checking instantly — no HardPrivilegeError,
        no ORCA_PROFILE=pi5 refusal, no Pi 5 hardware check (R11-F50), none
        of __init__'s fail-closed gates apply to a direct reassignment.
        Fixed at construction; there is no supported way to flip it later.
        """
        return self._enforce

    def start_turn(self, agent: str) -> None:
        if agent not in TEAM:
            raise HardPrivilegeError(f"unknown agent {agent!r}")
        if self._active_turn is not None and self._active_turn != agent:
            raise HardPrivilegeError(
                f"turn already active for {self._active_turn!r}; end_turn() first"
            )
        self._active_turn = agent

    def end_turn(self, granter: str = "grok") -> None:
        # R11-F53: previously `self._active_turn = None` only ran after
        # revoke() returned. revoke() raises HardPrivilegeError for an
        # unauthorized granter, so a single wrong-granter end_turn() call
        # left _active_turn permanently set — every future start_turn() for
        # any other agent then raised "turn already active" with no way to
        # recover short of calling end_turn() again with the right granter.
        # Turn bookkeeping must not depend on the revoke succeeding: clear
        # it first, then attempt revoke (whose own failure still propagates
        # to the caller — this only stops it from wedging turn state).
        target = self._active_turn
        self._active_turn = None
        if target:
            self.revoke(granter, target)

    def grant(
        self,
        granter: str,
        target: str,
        privs: Set[Privilege],
        note: str = "",
        human_approved: bool = False,
    ) -> None:
        if granter != GROK.name:
            raise HardPrivilegeError("Only Grok can propose grants")
        if target not in TEAM:
            raise HardPrivilegeError(f"unknown grant target {target!r}")
        privs = {_coerce_privilege(p) for p in privs}
        if Privilege.UNCLASSIFIED in privs:
            raise HardPrivilegeError(
                "UNCLASSIFIED is a sentinel, not a grantable privilege"
            )
        if not self.enforce:
            self._bypassed.add(target)
        else:
            sensitive = privs & SENSITIVE_GRANTS
            if sensitive and not human_approved:
                raise HardPrivilegeError(
                    f"Sensitive grant {sorted(p.value for p in sensitive)} requires "
                    f"HumanGate APPROVE from Fry (human_approved=True)"
                )
        self._grants.setdefault(target, set()).update(privs)
        self._notes[target] = note
        if human_approved and self.enforce:
            self._human_approved_grants.add(target)

    def revoke(self, granter: str, target: str, privs: Optional[Set[Privilege]] = None) -> None:
        if granter != GROK.name:
            raise HardPrivilegeError("Only Grok can revoke")
        if target not in self._grants:
            return
        if privs is None:
            self._grants.pop(target, None)
            self._notes.pop(target, None)
            self._human_approved_grants.discard(target)
            self._bypassed.discard(target)
            return
        self._grants[target] -= privs
        if not self._grants[target]:
            self._grants.pop(target, None)
            self._notes.pop(target, None)
        if not (self._grants.get(target, set()) & SENSITIVE_GRANTS):
            self._human_approved_grants.discard(target)
        if not self._grants.get(target):
            self._bypassed.discard(target)

    def effective(self, agent: str) -> Set[Privilege]:
        base = set(TEAM[agent].privileges) if agent in TEAM else set()
        return base | self._grants.get(agent, set())

    def can(self, agent: str, priv: Privilege) -> bool:
        priv = _coerce_privilege(priv)
        if not self.enforce:
            return True
        return priv in self.effective(agent)

    def require(self, agent: str, priv: Privilege) -> None:
        priv = _coerce_privilege(priv)
        if not self.can(agent, priv):
            raise HardPrivilegeError(
                f"{agent} lacks {priv.value}. effective="
                f"{[p.value for p in sorted(self.effective(agent), key=lambda x: x.value)]}"
            )

    def require_turn(self, agent: str) -> None:
        if not self.enforce:
            return
        if self._active_turn != agent:
            raise HardPrivilegeError(
                f"no active turn for {agent} (active={self._active_turn!r})"
            )

    def status(self) -> dict:
        return {
            "enforce": self.enforce,
            "active_turn": self._active_turn,
            "agents": {
                name: {
                    "title": duty.title,
                    "base": sorted(p.value for p in duty.privileges),
                    "granted": sorted(p.value for p in self._grants.get(name, set())),
                    "effective": sorted(p.value for p in self.effective(name)),
                    "grant_note": self._notes.get(name, ""),
                    "human_approved": name in self._human_approved_grants,
                    # R11-F32: when self.enforce is False, can()/require() give
                    # EVERY agent unconditional access regardless of _grants —
                    # not just targets that happened to have grant() called on
                    # them. Reporting `name in self._bypassed` here understates
                    # that: an agent with zero grants shows enforce_bypass=False
                    # and effective=["read"], which reads as "restricted" while
                    # can(agent, ANYTHING) is actually True. Bypass is global,
                    # not per-target, so report it that way.
                    "enforce_bypass": not self.enforce,
                }
                for name, duty in TEAM.items()
            },
        }
