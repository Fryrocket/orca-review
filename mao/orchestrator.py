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
  F31 SENSITIVE_GRANTS includes WRITE + ORCHESTRATE (landed 2026-08-23)
  F56 run_sequential no longer swallows FATAL_ERRORS (landed 2026-08-23)
  F57 run_sequential(human_approved=True) requires a HumanGate (landed 2026-08-24)
  F58 begin_task grants re-established after each turn (landed 2026-08-24)
  F59 string-returning adapters approximate tokens so CostGuard bills (landed 2026-08-24)
  F62/F63 bare run_* must not persist _active_run_id (landed 2026-08-24)
  F67 run_debate excludes moderator from roster even when agents= is set (landed 2026-08-24)
  F19 chat-path tool_calls ignored unless a schema was actually handed (landed 2026-08-24)
  Critical: _invoke uses user= (not prompt=), ModelResponse attrs, tool schemas
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
        self._task_grants: Dict[str, Set] = {}
        self._task_human_approved: bool = False

    @contextmanager
    def _turn(self, agent: str):
        self.broker.start_turn(agent)
        try:
            yield
        finally:
            self.broker.end_turn(self._runner)
            # R11-F58: re-establish task-level grants after end_turn's
            # per-turn revoke, if the task is still active. See
            # TO_GROK_F58_task_grants_survive_turns_2026-08-24 for the
            # full writeup.
            if self._active_run_id is not None and agent in self._task_grants:
                self.broker.grant(
                    self._runner,
                    agent,
                    self._task_grants[agent],
                    note=f"task {self._active_run_id} turn-carry",
                    human_approved=self._task_human_approved,
                )

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
        tool_schemas = None
        if tools_allowed and self.tools is not None and agent.tools:
            tool_proxy = AgentToolProxy(self.tools, agent.role.name, run_id)
            tool_schemas = []
            for tname in agent.tools:
                try:
                    t = self.tools.get(tname)
                except KeyError:
                    continue
                tool_schemas.append(
                    {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    }
                )

        text = ""
        tin = tout = 0
        reported_cost = 0.0
        schema_given = False
        try:
            if hasattr(model, "complete"):
                # CRITICAL (2026-08-23): ModelAdapter.complete expects user=, not prompt=
                raw = model.complete(
                    system=agent.system_prompt,
                    user=prompt,
                    tools=tool_schemas,
                )
                schema_given = tool_schemas is not None
            elif hasattr(model, "chat"):
                # R11-F19: .chat() is never handed tool_schemas (system+user
                # messages only), so this model has no legitimate basis for
                # producing a tool_calls entry. schema_given stays False.
                raw = model.chat(
                    [
                        {"role": "system", "content": agent.system_prompt},
                        {"role": "user", "content": prompt},
                    ]
                )
            else:
                raw = f"[{agent.role.name}] {prompt[:200]}"

            tool_calls: list = []
            if isinstance(raw, dict):
                text = raw.get("text") or raw.get("content") or str(raw)
                tin = int(raw.get("input_tokens") or raw.get("tokens_in") or 0)
                tout = int(raw.get("output_tokens") or raw.get("tokens_out") or 0)
                reported_cost = float(raw.get("cost_usd") or 0.0)
                if schema_given:
                    tool_calls = list(raw.get("tool_calls") or [])
            elif hasattr(raw, "text"):
                # ModelAdapter.complete returns ModelResponse, not a dict
                text = raw.text
                tin = int(getattr(raw, "input_tokens", 0) or 0)
                tout = int(getattr(raw, "output_tokens", 0) or 0)
                if schema_given:
                    tool_calls = list(getattr(raw, "tool_calls", None) or [])
            else:
                # R11-F59: adapter returned neither a dict nor a ModelResponse
                # — no structured usage at all. Do NOT leave tin/tout at their
                # 0 default: CostGuard.record() reads tin==0 and tout==0 as
                # "genuinely free," so a string-returning adapter would bill
                # $0 forever. Approximate from what we actually have (same
                # char/4 heuristic preflight() already uses as its upper
                # bound) so CostGuard's existing estimate_cost fallback
                # (tin>0 or tout>0) engages instead of silently zeroing out.
                text = str(raw)
                tin = max(1, len(prompt) // 4)
                tout = max(1, len(text) // 4)

            if tool_calls and tool_proxy is not None:
                for call in tool_calls:
                    cname = call.get("name")
                    cargs = call.get("arguments") or {}
                    if cname:
                        tool_proxy.call(cname, **cargs)
        except FATAL_ERRORS:
            raise
        except Exception as e:
            if self.on_step_error == "stop":
                raise
            text = f"[error] {type(e).__name__}: {e}"

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
        # R11-F62/F63: see TO_GROK_F62_F63_run_id_poisons_task_2026-08-24 —
        # must not persist an invented id into self._active_run_id for a
        # bare run with no begin_task(), or begin_task() refuses forever.
        if self._active_run_id:
            return self._active_run_id
        return str(uuid.uuid4())[:12]

    def run_sequential(
        self,
        objective: str,
        *,
        agents: Optional[Sequence[Agent]] = None,
        human_approved: bool = False,
    ) -> Generator[StepResult, None, None]:
        run_id = self._ensure_run_id()
        self.cost_guard.reset_run()
        roster = list(agents) if agents is not None else self.agents

        if human_approved:
            if self.human_gate is None:
                raise OrcaConfigError(
                    "human_approved=True requires a HumanGate on the Orchestrator. "
                    "Refusing to assert approval with no human in the loop (R11-F57)."
                )
            gr = self.human_gate.ask(objective, context="begin sequential run")
            if gr.decision != GateDecision.APPROVE:
                raise HardPrivilegeError(
                    f"Human gate denied sequential run: {gr.decision} ({gr.note})"
                )

        for agent in roster:
            # R11-F56: do NOT catch OrcaError here — FATAL_ERRORS must propagate
            with self._turn(agent.role.name):
                result = self._invoke(
                    agent, objective, run_id=run_id, tools_allowed=True
                )
            yield result

    def run_parallel(
        self,
        objective: str,
        *,
        agents: Optional[Sequence[Agent]] = None,
    ) -> Generator[StepResult, None, None]:
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
        run_id = self._ensure_run_id()
        self.cost_guard.reset_run()
        # R11-F67: the moderator exclusion only applied when agents= was
        # omitted (defaulting to self.agents). Callers who passed agents=
        # explicitly and happened to include the same Agent object as
        # moderator got that agent invoked twice per round — once as a
        # roster debater, once as moderator — with no error, no warning.
        # Exclude moderator from the roster the same way regardless of
        # where the agent list came from.
        base = list(agents) if agents is not None else list(self.agents)
        roster = [a for a in base if a is not moderator]
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

    def begin_task(
        self,
        objective: str,
        *,
        human_approved: bool = False,
        grant: Optional[Dict[str, set]] = None,
    ) -> str:
        if self._active_run_id is not None:
            raise OrcaConfigError(
                f"task {self._active_run_id} already active; call end_task() first"
            )

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
            approved = True

        run_id = str(uuid.uuid4())[:12]
        self._active_run_id = run_id
        self._task_grants = {}
        self._task_human_approved = approved

        if grant:
            try:
                for target, privs in grant.items():
                    self._task_grants[target] = set(privs)
                    self.broker.grant(
                        self._runner,
                        target,
                        privs,
                        note=f"begin_task {run_id}",
                        human_approved=approved,
                    )
            except BaseException:
                try:
                    self.end_task()
                except Exception:
                    pass
                raise
        return run_id

    def end_task(self) -> None:
        if self._active_run_id is None and not self._task_grants:
            raise OrcaConfigError(
                "end_task() called with no active task "
                "(begin_task was never called, or end_task already ran)"
            )
        for target, privs in list(self._task_grants.items()):
            try:
                self.broker.revoke(self._runner, target, privs)
            except Exception:
                pass
        self._task_grants.clear()
        self._active_run_id = None
