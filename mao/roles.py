"""Orca team roles + PrivilegeBroker."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Set

from .errors import HardPrivilegeError


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

assert not any(Privilege.UNCLASSIFIED in d.privileges for d in TEAM.values())


class PrivilegeBroker:
    def __init__(self, enforce: Optional[bool] = None):
        profile = (os.environ.get("ORCA_PROFILE") or "").lower()
        if enforce is None:
            enforce = profile not in {"dev", "test", "local"}
        if profile in {"pi5", "pi", "power"} and not enforce:
            raise HardPrivilegeError("ORCA_PROFILE=pi5 refuses enforce=False")
        self.enforce = bool(enforce)
        self._grants: Dict[str, Set[Privilege]] = {}
        self._notes: Dict[str, str] = {}
        self._active_turn: Optional[str] = None
        self._human_approved_grants: Set[str] = set()
        self._bypassed: Set[str] = set()

    def start_turn(self, agent: str) -> None:
        if agent not in TEAM:
            raise HardPrivilegeError(f"unknown agent {agent!r}")
        if self._active_turn is not None and self._active_turn != agent:
            raise HardPrivilegeError(
                f"turn already active for {self._active_turn!r}; end_turn() first"
            )
        self._active_turn = agent

    def end_turn(self, granter: str = "grok") -> None:
        if self._active_turn:
            self.revoke(granter, self._active_turn)
        self._active_turn = None

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
        if not self.enforce:
            return True
        return priv in self.effective(agent)

    def require(self, agent: str, priv: Privilege) -> None:
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
                    "enforce_bypass": name in self._bypassed,
                }
                for name, duty in TEAM.items()
            },
        }
