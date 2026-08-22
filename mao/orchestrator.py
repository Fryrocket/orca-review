"""Orca Orchestrator — Round-7 + R11 fixes.

Single-runner, turn-gated, cost-guarded, privilege-aware multi-agent loop.
Parallel / debate modes are intentionally tool-less (E2 / D-2).

R11 fixes applied:
  F1  begin_task: gate first, then grant; revoke on deny/exception
  F2  end_task + tracked grants
  F3  FATAL_ERRORS re-raised before general except
  F4  AgentToolProxy no longer passes run_id= into ToolRegistry.call
  F5  StepResult.cost_usd comes from CostGuard.record return value
  F11 cost_guard.reset_run() at run boundaries
  F12 (bus side) already handled
  F16 run_* reuse _active_run_id from begin_task when set
  F17 turn does not span yield (invoke fully inside with, then yield)
  F18 parallel/debate refuse agents that declare tools
  F20 debate prompt uses actual loop bound
  F22 end_task clears _active_run_id
  F24 runner must be GROK.name (granter identity)
  F25 never forge human_approved without a HumanGate
  F26 end_task raises if no active task
  F27 no state mutation before gate; refuse re-entry
  F28/F29 cleanup catches BaseException, never masks original
  F30 track grants before broker.grant (over-revoke safe)
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, List, Optional, Sequence, Set
import uuid

from .agent import Agent
from .blackboard import Blackboard
from .bus import FATAL_ERRORS, MessageBus
from .costguard import CostGuard
from .errors import HardPrivilegeError, OrcaConfigError, OrcaError
from .human import GateDecision, HumanGate
from .roles import Privilege, PrivilegeBroker, TEAM, GROK
from .tools import ToolRegistry


@dataclass
class StepResult:
    agent: str
    text: Any
    run_id: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    meta: dict = field(default_factory=dict)


class AgentToolProxy:
    """Thin proxy that forces agent= into every tool call (E7).

    R11-F4: does NOT pass run_id= into ToolRegistry.call (registry has no
    such parameter; it would be silently swallowed by **kwargs).
    """

    def __init__(self, registry: ToolRegistry, agent: str, run_id: str = ""):
        self._reg = registry
        self._agent = agent
        self._run_id = run_id  # kept for future / logging only

    def call(self, name: str, *args, **kwargs):
        return self._reg.call(name, *args, agent=self._agent, **kwargs)

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        def _caller(*args, **kwargs):
            return self.call(name, *args, **kwargs)
        return _caller


class Orchestrator:
    """Coordinates agents under a fixed runner (usually 'grok')."""

    def __init__(
        self,
        agents: Sequence[Agent],
        *,
        bus: Optional[MessageBus] = None,
        memory: Optional[Blackboard] = None,
        tools: Optional[ToolRegistry] = None,
        broker: Optional[PrivilegeBroker] = None,
        cost_guard: Optional[CostGuard] = None,
        human_gate: Optional[HumanGate] = None,
        default_model: Any = None,
        runner: str = GROK.name,  # must match F24 constant, not a bare literal
        on_step_error: str = "stop",  # "stop" | "continue"
        max_rounds: int = 8,
    ):
        if not agents:
            raise OrcaConfigError("Orchestrator requires at least one agent")
        # R11-F24: granter/runner identity must agree. PrivilegeBroker.grant
        # hard-requires granter == GROK.name. Fail closed at construction.
        if runner != GROK.name:
            raise OrcaConfigError(
                f"Orchestrator runner must be {GROK.name!r} (got {runner!r}). "
                "PrivilegeBroker.grant only accepts GROK as granter; "
                "a non-Grok runner would open turns cleanly then die on any "
                "begin_task(grant=...). Fail early."
            )
        self.agents = list(agents)
        self.bus = bus or MessageBus()
        self.tools = tools
        self.broker = broker or PrivilegeBroker()
        self.human_gate = human_gate
        self.default_model = default_model
        self._runner = runner
        self.on_step_error = on_step_error
        self.max_rounds = max_rounds

        if memory is None:
            def _guard(writer: str, key: str) -> None:
                self.broker.require(writer, Privilege.WRITE)
            self.memory = Blackboard(guard=_guard)
        else:
            self.memory = memory

        if cost_guard is None:
            raise OrcaConfigError(
                "CostGuard is required (E6). Construct UsageTrackerCostGuard "
                "with a real estimate_cost and pass it as cost_guard=."
            )
        self.cost_guard = cost_guard

        self._active_run_id: Optional[str] = None
        # Grants issued by the current begin_task (for end_task / revoke-on-deny)
        self._task_grants: Dict[str, Set] = {}  # target -> privs

    # ------------------------------------------------------------------
    # Turn context (E1)
    # ------------------------------------------------------------------
    @contextmanager
    def _turn(self, agent: str):
        """Open a turn for `agent`, always close via granter=self._runner."""
        self.broker.start_turn(agent)
        try:
            yield
        finally:
            self.broker.end_turn(self._runner)

    # ------------------------------------------------------------------
    # Model invocation helper
    # ------------------------------------------------------------------
    def _invoke(
        self,
        agent: Agent,
        prompt: str,
        *,
        run_id: str,
        tools_allowed: bool = True,
    ) -> StepResult:
        model = agent.model or self.default_model
        if model is None:
            raise OrcaConfigError(f"Agent {agent.role.name} has no model bound")

        self.cost_guard.preflight(
            getattr(model, "name", "unknown"), prompt, agent=agent.role.name
        )

        tool_proxy = None
        if tools_allowed and self.tools is not None and agent.tools:
            tool_proxy = AgentToolProxy(self.tools, agent.role.name, run_id)

        text = ""
        tin = tout = 0
        reported_cost = 0.0
        try:
            if hasattr(model, "complete"):
                raw = model.complete(
                    system=agent.system_prompt,
                    prompt=prompt,
                    tools=tool_proxy,
                )
            elif hasattr(model, "chat"):
                # chat path does not receive tools (R11-F19 noted; adapters differ)
                raw = model.chat(
                    [
                        {"role": "system", "content": agent.system_prompt},
                        {"role": "user", "content": prompt},
                    ]
                )
            else:
                raw = f"[{agent.role.name}] {prompt[:200]}"
            if isinstance(raw, dict):
                text = raw.get("text") or raw.get("content") or str(raw)
                tin = int(raw.get("input_tokens") or raw.get("tokens_in") or 0)
                tout = int(raw.get("output_tokens") or raw.get("tokens_out") or 0)
                reported_cost = float(raw.get("cost_usd") or 0.0)
            else:
                text = str(raw)
        except FATAL_ERRORS:
            # R11-F3: privilege / cost / config errors must not become prose
            raise
        except Exception as e:
            if self.on_step_error == "stop":
                raise
            text = f"[error] {type(e).__name__}: {e}"

        # R11-F5: use the float the guard actually billed
        billed = self.cost_guard.record(
            getattr(model, "name", "unknown"),
            tin,
            tout,
            agent=agent.role.name,
            cost_usd=reported_cost,
        )

        result = StepResult(
            agent=agent.role.name,
            text=text,
            run_id=run_id,
            tokens_in=tin,
            tokens_out=tout,
            cost_usd=billed,
        )
        self.bus.publish(
            sender=agent.role.name,
            content=text,
            topic="step",
            run_id=run_id,
            agent=agent.role.name,
        )
        return result

    def _ensure_run_id(self) -> str:
        """Reuse begin_task id when present; otherwise mint (R11-F16)."""
        if self._active_run_id:
            return self._active_run_id
        rid = str(uuid.uuid4())[:12]
        self._active_run_id = rid
        return rid

    # ------------------------------------------------------------------
    # Public run modes
    # ------------------------------------------------------------------
    def run_sequential(
        self,
        objective: str,
        *,
        agents: Optional[Sequence[Agent]] = None,
        human_approved: bool = False,
    ) -> Generator[StepResult, None, None]:
        """Run agents one after another under turn + privilege control."""
        run_id = self._ensure_run_id()
        self.cost_guard.reset_run()  # R11-F11
        roster = list(agents) if agents is not None else self.agents

        if human_approved and self.human_gate is not None:
            gr = self.human_gate.ask(objective, context="begin sequential run")
            if gr.decision != GateDecision.APPROVE:
                raise HardPrivilegeError(
                    f"Human gate denied sequential run: {gr.decision} ({gr.note})"
                )

        for agent in roster:
            # R11-F17: invoke fully inside the turn, then yield the result
            with self._turn(agent.role.name):
                try:
                    result = self._invoke(
                        agent, objective, run_id=run_id, tools_allowed=True
                    )
                except OrcaError:
                    if self.on_step_error == "stop":
                        raise
                    continue
            yield result

    def run_parallel(
        self,
        objective: str,
        *,
        agents: Optional[Sequence[Agent]] = None,
    ) -> Generator[StepResult, None, None]:
        """Parallel mode is deliberately tool-less and turn-less (E2 / D-2).

        R11-F18: agents that declare tools are refused, not silently stripped.
        """
        run_id = self._ensure_run_id()
        self.cost_guard.reset_run()
        roster = list(agents) if agents is not None else self.agents

        for agent in roster:
            if agent.tools:
                raise OrcaConfigError(
                    f"Parallel mode refuses tool-declaring agent {agent.role.name!r} "
                    f"(tools={agent.tools}). Use sequential or strip tools first."
                )
            yield self._invoke(agent, objective, run_id=run_id, tools_allowed=False)

    def run_debate(
        self,
        objective: str,
        *,
        rounds: int = 2,
        moderator: Optional[Agent] = None,
        agents: Optional[Sequence[Agent]] = None,
    ) -> Generator[StepResult, None, None]:
        """Structured multi-round debate. Tool-less."""
        run_id = self._ensure_run_id()
        self.cost_guard.reset_run()
        roster = list(agents) if agents is not None else [
            a for a in self.agents if a is not moderator
        ]
        if not roster:
            raise OrcaConfigError("Debate needs at least one debating agent")

        for a in roster + ([moderator] if moderator else []):
            if a and a.tools:
                raise OrcaConfigError(
                    f"Debate refuses tool-declaring agent {a.role.name!r}. "
                    "Strip tools or use sequential."
                )

        actual_rounds = min(rounds, self.max_rounds)
        history: List[str] = []
        for rnd in range(actual_rounds):
            for agent in roster:
                prompt = (
                    f"Debate round {rnd + 1}/{actual_rounds}. Objective: {objective}\n"
                    f"Prior points:\n" + "\n".join(history[-6:]) + "\n\nYour turn."
                )
                r = self._invoke(agent, prompt, run_id=run_id, tools_allowed=False)
                history.append(f"{agent.role.name}: {r.text}")
                yield r

            if moderator is not None:
                mod_prompt = (
                    f"As moderator, summarize round {rnd + 1} of the debate on:\n"
                    f"{objective}\n\n" + "\n".join(history[-len(roster) :])
                )
                r = self._invoke(moderator, mod_prompt, run_id=run_id, tools_allowed=False)
                history.append(f"moderator: {r.text}")
                yield r

    # ------------------------------------------------------------------
    # Task lifecycle
    # ------------------------------------------------------------------
    def begin_task(
        self,
        objective: str,
        *,
        human_approved: bool = False,
        grant: Optional[Dict[str, set]] = None,
    ) -> str:
        """Open a task. Gate FIRST, then grant. Tracks grants for end_task.

        R11-F25: if human_approved is requested and no HumanGate is configured,
        raise — never forge an approval flag with no human in the loop.
        The value passed downstream to grant() is derived from the GateResult,
        not echoed from the input flag.

        R11-F27: refuse re-entry; mutate _active_run_id / _task_grants only
        AFTER the gate has approved. Denied tasks leave no live run id and
        do not orphan prior grants.
        """
        # R11-F27 part 1: refuse re-entry (pair with F26)
        if self._active_run_id is not None:
            raise OrcaConfigError(
                f"task {self._active_run_id} already active; call end_task() first"
            )

        # Gate first — no observable state mutation above this point
        approved = False
        if human_approved:
            if self.human_gate is None:
                raise OrcaConfigError(
                    "human_approved=True requires a HumanGate on the Orchestrator. "
                    "Refusing to assert approval with no human in the loop (N1)."
                )
            gr = self.human_gate.ask(objective, context="begin_task")
            if gr.decision != GateDecision.APPROVE:
                raise HardPrivilegeError(
                    f"begin_task denied by gate: {gr.decision} ({gr.note})"
                )
            approved = True  # derived from GateResult, not the input flag

        # Only after gate: assign state (R11-F27 part 2)
        run_id = str(uuid.uuid4())[:12]
        self._active_run_id = run_id
        self._task_grants = {}

        if grant:
            try:
                for target, privs in grant.items():
                    # R11-F30: record tracking BEFORE the call so partial
                    # failures still get cleaned up (over-revoke is safe).
                    self._task_grants[target] = set(privs)
                    self.broker.grant(
                        self._runner,
                        target,
                        privs,
                        note=f"begin_task {run_id}",
                        human_approved=approved,
                    )
            except BaseException:
                # R11-F28/F29: cleanup must not mask the original cause;
                # catch BaseException so Ctrl-C / SystemExit still revoke.
                try:
                    self.end_task()
                except Exception:
                    pass  # never speak over the original
                raise
        return run_id

    def end_task(self) -> None:
        """Revoke all grants issued by the current begin_task (R11-F2).

        Also clears _active_run_id (R11-F22). Raises OrcaConfigError if no
        task is active (R11-F26) so double-call / out-of-order is visible.
        Caller is responsible for pairing begin_task / end_task; there is no
        automatic finally in the orchestrator itself.
        """
        if self._active_run_id is None and not self._task_grants:
            raise OrcaConfigError(
                "end_task() called with no active task "
                "(begin_task was never called, or end_task already ran)"
            )
        for target, privs in list(self._task_grants.items()):
            try:
                self.broker.revoke(self._runner, target, privs)
            except Exception:
                # Best-effort revoke; continue cleaning the rest
                pass
        self._task_grants.clear()
        self._active_run_id = None
