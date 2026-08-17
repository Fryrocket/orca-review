"""Orchestrator with sequential/parallel/debate modes + privilege enforcement."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, List, Optional, Set
from concurrent.futures import ThreadPoolExecutor, as_completed

from .agent import Agent
from .bus import MessageBus
from .cost_store import DayCostStore
from .errors import HardPrivilegeError, OrcaConfigError, OrcaError
from .human import GateDecision, HumanGate
from .memory import Blackboard
from .models import ModelAdapter, ModelResponse, get_default_model
from .pricing import estimate_cost
from .roles import Privilege, PrivilegeBroker
from .tools import ToolRegistry
from .tracking import UsageTracker


def _pi_profile() -> bool:
    return (os.environ.get("ORCA_PROFILE") or "").lower() in {"pi5", "pi", "power"}


class Orchestrator:
    def __init__(
        self,
        agents: List[Agent],
        bus: Optional[MessageBus] = None,
        memory: Optional[Blackboard] = None,
        tools: Optional[ToolRegistry] = None,
        tracker: Optional[UsageTracker] = None,
        human_gate: Optional[HumanGate] = None,
        default_model: Optional[ModelAdapter] = None,
        broker: Optional[PrivilegeBroker] = None,
        max_tool_rounds: int = 3,
        enforce_privileges: bool = True,
    ):
        if _pi_profile() and not enforce_privileges:
            raise HardPrivilegeError("PI5 profile refuses enforce_privileges=False")
        self.agents = agents
        self.bus = bus or MessageBus()
        self.memory = memory or Blackboard()
        self.broker = broker or PrivilegeBroker(enforce=enforce_privileges)
        self.tools = tools or ToolRegistry(broker=self.broker)
        if self.tools.broker is None:
            self.tools.broker = self.broker
        if tracker is None:
            root = os.environ.get("ORCA_REPO_ROOT") or os.environ.get("MAO_REPO_ROOT")
            if root:
                store = DayCostStore(Path(root) / "runs" / "cost_day.json")
            elif _pi_profile():
                raise OrcaConfigError(
                    "PI5 profile requires ORCA_REPO_ROOT for UsageTracker"
                )
            else:
                store = DayCostStore(Path("runs") / "cost_day.json")
            tracker = UsageTracker(day_store=store)
        self.tracker = tracker
        self.human_gate = human_gate
        self.default_model = default_model or get_default_model()
        self.max_tool_rounds = max(1, int(max_tool_rounds))
        self._step = 0

        for a in self.agents:
            if a.model is None:
                a.model = self.default_model

    @property
    def enforce_privileges(self) -> bool:
        return self.broker.enforce

    @enforce_privileges.setter
    def enforce_privileges(self, value: bool) -> None:
        if _pi_profile() and not value:
            raise HardPrivilegeError("PI5 profile refuses enforce_privileges=False")
        self.broker.enforce = bool(value)

    def _agent_name(self, agent: Agent) -> str:
        return agent.role.name

    def _check_write_privileges(
        self,
        agent: Agent,
        touching_code: bool = False,
        touching_firmware: bool = False,
        touching_hardware: bool = False,
    ) -> None:
        name = self._agent_name(agent)
        if touching_code or touching_firmware or touching_hardware:
            self.broker.require_turn(name)
        if touching_code:
            self.broker.require(name, Privilege.CODE_EDIT)
        if touching_firmware:
            self.broker.require(name, Privilege.FIRMWARE_EDIT)
        if touching_hardware:
            self.broker.require(name, Privilege.HARDWARE_DESIGN)

    def begin_task(
        self,
        agent_name: str,
        privs: Optional[Set[Privilege]] = None,
        note: str = "",
        human_approved: bool = False,
    ) -> None:
        """Start a turn. Sensitive grants require human_approved=True (Fry)."""
        self.broker.start_turn(agent_name)
        if privs:
            self.broker.grant(
                "grok",
                agent_name,
                privs,
                note=note,
                human_approved=human_approved,
            )
        self.bus.publish(
            "task.begin",
            sender="grok",
            content={
                "agent": agent_name,
                "privs": [p.value for p in (privs or [])],
                "note": note,
                "human_approved": human_approved,
            },
        )

    def end_task(self, agent_name: str, revoke: bool = True) -> None:
        self.broker.end_turn()
        if revoke:
            self.broker.revoke("grok", agent_name)
        self.bus.publish(
            "task.end", sender="grok", content={"agent": agent_name, "revoked": revoke}
        )

    def _tool_schemas_for(self, agent: Agent) -> list[dict]:
        schemas = []
        for name in agent.tools:
            try:
                t = self.tools.get(name)
                schemas.append(
                    {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    }
                )
            except KeyError:
                continue
        return schemas

    def _preflight_prompt(self, model: ModelAdapter, system: str, user: str) -> None:
        approx_in = max(1, (len(system) + len(user)) // 4)
        est = estimate_cost(model.name, approx_in, 512)
        self.tracker.preflight(est)

    def run_turn(
        self,
        agent: Agent,
        input_content: Any,
        require_human: bool = False,
        touching_code: bool = False,
        touching_firmware: bool = False,
        touching_hardware: bool = False,
        tools_enabled: bool = True,
    ) -> Any:
        name = self._agent_name(agent)
        self._check_write_privileges(
            agent,
            touching_code=touching_code,
            touching_firmware=touching_firmware,
            touching_hardware=touching_hardware,
        )

        self._step += 1
        self.bus.publish(
            topic="agent.input",
            sender="orchestrator",
            content=input_content,
            agent=name,
            step=self._step,
        )

        system = agent.system_prompt
        user = str(input_content)
        model: ModelAdapter = agent.model or self.default_model
        tool_schemas = self._tool_schemas_for(agent) if tools_enabled else []

        final_text = ""
        for _ in range(self.max_tool_rounds):
            self._preflight_prompt(model, system, user)
            response: ModelResponse = model.complete(
                system=system, user=user, tools=tool_schemas or None
            )
            cost = estimate_cost(model.name, response.input_tokens, response.output_tokens)
            self.tracker.record(
                agent=name,
                model=model.name,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                cost_usd=cost,
            )

            if not response.tool_calls:
                final_text = response.text
                break

            if not tools_enabled:
                raise HardPrivilegeError(
                    f"tools disabled in this mode (agent={name!r})"
                )

            tool_results = []
            for tc in response.tool_calls:
                tname = tc.get("name")
                args = tc.get("arguments") or {}
                self.bus.publish(
                    "tool.call", sender=name, content={"name": tname, "args": args}
                )
                try:
                    if isinstance(args, dict):
                        result = self.tools.call(tname, agent=name, **args)
                    else:
                        result = self.tools.call(tname, args, agent=name)
                except OrcaError:
                    raise
                except Exception as e:
                    self.bus.publish(
                        "tool.error", sender=tname or "tool", content=str(e)
                    )
                    raise
                self.bus.publish("tool.result", sender=tname or "tool", content=result)
                tool_results.append({"tool": tname, "result": result})

            user = (
                f"Original request: {input_content}\n"
                f"Tool results: {tool_results}\n"
                f"Continue or give your final answer."
            )
            final_text = response.text or str(tool_results)
        else:
            final_text = final_text or "(max tool rounds reached)"

        output = {
            "agent": name,
            "text": final_text,
            "model": model.name,
        }

        if require_human:
            if self.human_gate is None:
                raise HardPrivilegeError(
                    "require_human=True but no human_gate configured — fail closed"
                )
            result = self.human_gate.ask(output, context=f"Agent: {name}")
            if result.decision in (GateDecision.REJECT, GateDecision.SKIP):
                self.bus.publish("agent.rejected", sender="human", content=result.note)
                return {"agent": name, "rejected": True, "note": result.note}
            if result.decision == GateDecision.EDIT:
                output["text"] = result.content
                output["edited"] = True

        self.bus.publish(
            topic="agent.output",
            sender=name,
            content=output,
            step=self._step,
        )
        self.memory.set(f"last_output:{name}", output, author=name)
        return output

    def run_sequential(self, initial_input: Any, human_every_step: bool = False) -> list:
        current = initial_input
        results = []
        for agent in self.agents:
            current = self.run_turn(agent, current, require_human=human_every_step)
            results.append(current)
            if isinstance(current, dict) and "text" in current:
                current = current["text"]
        return results

    def run_parallel(self, input_content: Any, max_workers: int = 4) -> list:
        """Read-only fan-out. No tool calls — single-slot broker cannot own N turns."""
        results = []

        def _run(agent: Agent):
            return self.run_turn(agent, input_content, tools_enabled=False)

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_run, a): a for a in self.agents}
            for fut in as_completed(futures):
                results.append(fut.result())

        self.memory.set("parallel_results", results, author="orchestrator")
        return results

    def run_debate(
        self,
        topic: str,
        rounds: int = 2,
        moderator: Optional[Agent] = None,
    ) -> list:
        """Read-only debate. No tool calls."""
        debaters = [a for a in self.agents if moderator is None or a.id != moderator.id]
        history: list[dict] = []

        for r in range(1, rounds + 1):
            round_outputs = []
            for agent in debaters:
                prompt = (
                    f"Debate topic: {topic}\n"
                    f"Round {r}/{rounds}\n"
                    f"Previous points:\n{self._format_history(history)}\n\n"
                    f"Give your argument or rebuttal. Be concise."
                )
                out = self.run_turn(agent, prompt, tools_enabled=False)
                round_outputs.append(out)
                history.append(out)

            if moderator:
                mod_prompt = (
                    f"You are the moderator. Topic: {topic}\n"
                    f"Round {r} arguments:\n{self._format_history(round_outputs)}\n\n"
                    f"Summarize the state of the debate and note strongest points."
                )
                mod_out = self.run_turn(moderator, mod_prompt, tools_enabled=False)
                history.append(mod_out)

        self.memory.set("debate_history", history, author="orchestrator")
        return history

    @staticmethod
    def _format_history(items: list) -> str:
        lines = []
        for i, item in enumerate(items, 1):
            if isinstance(item, dict):
                agent = item.get("agent", "?")
                text = item.get("text", str(item))
            else:
                agent, text = "?", str(item)
            lines.append(f"{i}. [{agent}] {text[:300]}")
        return "\n".join(lines) if lines else "(none yet)"
