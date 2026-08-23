"""Orca web dashboard — team, privileges, cost, bus, live human gate."""

from __future__ import annotations

import json
import os
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from mao.agent import Agent, Role
from mao.blackboard import Blackboard
from mao.bus import MessageBus
from mao.cost_store import DayCostStore
from mao.costguard import UsageTrackerCostGuard
from mao.errors import GateTimeoutError, OrcaConfigError, OrcaError
from mao.human import GateDecision, GateResult, HumanGate
from mao.models import get_default_model
from mao.orchestrator import Orchestrator
from mao.roles import AMPERE, CLAUDE, GROK, Privilege, PrivilegeBroker, RELAY
from mao.tracking import UsageTracker
from mao.web_ui.auth import authorized, dashboard_token, validate_bind

STATIC = Path(__file__).parent / "static"

_GATE_TIMEOUT = float(os.environ.get("ORCA_GATE_TIMEOUT_SEC", "300"))


def _publish(bus: MessageBus, topic: str, content: Any) -> None:
    bus.publish("ui", content, topic=topic)


class DashboardGate(HumanGate):
    def __init__(self, state: "DashboardState"):
        super().__init__(prompt="dashboard")
        self.state = state

    def ask(self, payload: Any, context: str = "") -> GateResult:
        self.state._gate_payload = payload
        self.state._gate_context = context
        self.state._gate_result = None
        self.state._gate_pending = True
        self.state._gate_event.clear()
        _publish(self.state.bus, "gate.pending", {"context": context})
        ok = self.state._gate_event.wait(timeout=_GATE_TIMEOUT)
        self.state._gate_pending = False
        if not ok:
            _publish(self.state.bus, "gate.timeout", {"context": context})
            raise GateTimeoutError(
                f"human gate timed out after {_GATE_TIMEOUT}s — fail CLOSED (deny)"
            )
        result = self.state._gate_result
        if result is None:
            return GateResult(GateDecision.REJECT, note="no decision — fail closed")
        return result


class DashboardState:
    def __init__(self):
        root = os.environ.get("ORCA_REPO_ROOT") or os.getcwd()
        self.broker = PrivilegeBroker()
        self.bus = MessageBus()
        self.memory = Blackboard(
            guard=lambda writer, key: self.broker.require(writer, Privilege.WRITE)
        )
        self.tracker = UsageTracker(
            per_run_ceiling_usd=float(os.environ.get("ORCA_RUN_CEILING", "5")),
            per_day_ceiling_usd=float(os.environ.get("ORCA_DAY_CEILING", "20")),
            day_store=DayCostStore(Path(root) / "runs" / "cost_day.json"),
        )
        self.cost_guard = UsageTrackerCostGuard(
            record_usage=self.tracker.record,
            hard_ceiling_usd=self.tracker.per_run_ceiling_usd,
        )
        self.model = get_default_model()
        self.agents = [
            Agent(Role(d.name, d.title), d.system_prompt, model=self.model)
            for d in (GROK, CLAUDE, AMPERE, RELAY)
        ]
        self._gate_payload: Any = None
        self._gate_context = ""
        self._gate_pending = False
        self._gate_result: Optional[GateResult] = None
        self._gate_event = threading.Event()
        self.gate = DashboardGate(self)
        self.orch = Orchestrator(
            agents=self.agents,
            bus=self.bus,
            memory=self.memory,
            cost_guard=self.cost_guard,
            default_model=self.model,
            broker=self.broker,
            human_gate=self.gate,
        )

    def snapshot(self) -> dict:
        return {
            "privileges": self.broker.status(),
            "usage": {
                "total_tokens": self.tracker.total_tokens(),
                "total_cost_usd": self.tracker.total_cost(),
                "by_agent": self.tracker.by_agent(),
            },
            "bus": [
                {
                    "id": m.msg_id,
                    "topic": m.topic,
                    "sender": m.sender,
                    "content": m.content,
                    "timestamp": m.timestamp,
                }
                for m in self.bus.history(limit=120)
            ],
            "gate": {
                "pending": self._gate_pending,
                "context": self._gate_context,
                "payload": self._gate_payload,
            },
            "model": getattr(self.model, "name", "unknown"),
            "platform": "pi" if Path("/proc/device-tree/model").exists() else "host",
            "auth_required": bool(dashboard_token()),
        }


STATE: Optional[DashboardState] = None


def _state() -> DashboardState:
    global STATE
    if STATE is None:
        STATE = DashboardState()
    return STATE


def _json_response(handler: SimpleHTTPRequestHandler, code: int, obj: Any):
    data = json.dumps(obj, default=str).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _read_json(handler: SimpleHTTPRequestHandler) -> dict:
    n = int(handler.headers.get("Content-Length") or 0)
    if n <= 0:
        return {}
    return json.loads(handler.rfile.read(n).decode() or "{}")


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _require_auth(self) -> bool:
        if authorized(self.headers.get("Authorization")):
            return True
        _json_response(self, 401, {"ok": False, "error": "unauthorized"})
        return False

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._file(STATIC / "index.html", "text/html")
        if path.startswith("/static/"):
            name = path.split("/", 2)[-1]
            f = STATIC / name
            if not f.exists():
                self.send_error(404)
                return
            ctype = (
                "text/css"
                if name.endswith(".css")
                else "application/javascript"
                if name.endswith(".js")
                else "text/plain"
            )
            return self._file(f, ctype)
        if path == "/api/state":
            if not self._require_auth():
                return
            return _json_response(self, 200, _state().snapshot())
        self.send_error(404)

    def do_POST(self):
        if not self._require_auth():
            return
        path = urlparse(self.path).path
        body = _read_json(self)
        st = _state()
        try:
            if path == "/api/turn/start":
                agent = body.get("agent") or "claude"
                st.broker.start_turn(agent)
                _publish(st.bus, "ui.turn.start", {"agent": agent})
                return _json_response(self, 200, {"ok": True})

            if path == "/api/turn/end":
                st.broker.end_turn("grok")
                _publish(st.bus, "ui.turn.end", {})
                return _json_response(self, 200, {"ok": True})

            if path == "/api/grant":
                agent = body.get("agent")
                privs = {Privilege(p) for p in body.get("privs") or []}
                note = body.get("note") or ""
                human_approved = bool(body.get("human_approved"))
                st.broker.grant(
                    "grok",
                    agent,
                    privs,
                    note=note,
                    human_approved=human_approved,
                )
                _publish(
                    st.bus,
                    "ui.grant",
                    {
                        "agent": agent,
                        "privs": [p.value for p in privs],
                        "note": note,
                        "human_approved": human_approved,
                    },
                )
                return _json_response(self, 200, {"ok": True})

            if path == "/api/revoke":
                agent = body.get("agent")
                st.broker.revoke("grok", agent)
                _publish(st.bus, "ui.revoke", {"agent": agent})
                return _json_response(self, 200, {"ok": True})

            if path == "/api/gate/decide":
                decision = body.get("decision") or "reject"
                note = body.get("note") or ""
                edited = body.get("edited") or ""
                if decision == "approve":
                    st._gate_result = GateResult(
                        GateDecision.APPROVE, content=st._gate_payload, note=note
                    )
                elif decision == "edit":
                    st._gate_result = GateResult(
                        GateDecision.EDIT,
                        content=edited or st._gate_payload,
                        note=note,
                    )
                else:
                    st._gate_result = GateResult(GateDecision.REJECT, note=note or decision)
                st._gate_pending = False
                st._gate_event.set()
                return _json_response(self, 200, {"ok": True, "decision": decision})

            if path == "/api/run":
                if "enforce_privileges" in body:
                    raise OrcaConfigError(
                        "client cannot toggle enforce_privileges"
                    )
                text = body.get("input") or "Hello"
                require_human = bool(body.get("require_human"))
                results = [
                    {
                        "agent": r.agent,
                        "text": r.text,
                        "run_id": r.run_id,
                        "tokens_in": r.tokens_in,
                        "tokens_out": r.tokens_out,
                        "cost_usd": r.cost_usd,
                    }
                    for r in st.orch.run_sequential(
                        text, human_approved=require_human
                    )
                ]
                return _json_response(
                    self,
                    200,
                    {
                        "results": results,
                        "usage": {
                            "total_tokens": st.tracker.total_tokens(),
                            "total_cost_usd": st.tracker.total_cost(),
                            "by_agent": st.tracker.by_agent(),
                        },
                    },
                )

            self.send_error(404)
        except OrcaError as e:
            return _json_response(self, 400, {"ok": False, "error": str(e)})
        except Exception as e:
            return _json_response(self, 400, {"ok": False, "error": str(e)})

    def _file(self, path: Path, ctype: str):
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve(host: str | None = None, port: int | None = None):
    host = host or os.environ.get("ORCA_HOST", "127.0.0.1")
    port = int(port or os.environ.get("ORCA_PORT", "8787"))
    validate_bind(host)
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"Orca dashboard → http://{host}:{port}")
    if dashboard_token():
        print("Bearer token required (ORCA_DASHBOARD_TOKEN)")
    print("Default bind is 127.0.0.1. LAN needs ORCA_DASHBOARD_LAN=1 + token.")
    httpd.serve_forever()


if __name__ == "__main__":
    serve()
