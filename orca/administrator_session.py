"""Persistent Fry-only Administrator Screen conversations and governed tools."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from threading import RLock
from uuid import uuid4

from .engineering_console import run_acceptance
from .security import redact_text


_SESSION = re.compile(r"admin_[a-f0-9]{24}")
_TECHNICAL_TOOL = re.compile(
    r"\b(?:run|start|execute|build|create|verify|test|repair|rerun)\b.{0,160}"
    r"\b(?:acceptance|pi\s*5|active[- ]cooling|hat|workbench)\b|"
    r"\b(?:acceptance|pi\s*5|active[- ]cooling|hat|workbench)\b.{0,160}"
    r"\b(?:run|start|execute|build|create|verify|test|repair|rerun)\b",
    re.IGNORECASE | re.DOTALL,
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class AdministratorSessionStore:
    """Atomic, redacted session files kept separate from ordinary ORCA memory."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve() / "administrator-sessions"
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()

    def _path(self, session_id: str) -> Path:
        if not isinstance(session_id, str) or not _SESSION.fullmatch(session_id):
            raise ValueError("Administrator session id is invalid")
        return self.root / f"{session_id}.json"

    def _save(self, session: dict) -> None:
        path = self._path(session["session_id"])
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(session, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)

    def create(self) -> dict:
        now = _now()
        session = {"session_id": f"admin_{uuid4().hex[:24]}", "created_at": now,
                   "updated_at": now, "state": "idle", "cancel_requested": False,
                   "messages": [], "active_run_id": None}
        with self.lock:
            self._save(session)
        return session

    def read(self, session_id: str) -> dict:
        path = self._path(session_id)
        with self.lock:
            if not path.is_file():
                raise FileNotFoundError(session_id)
            return json.loads(path.read_text(encoding="utf-8"))

    def list(self) -> list[dict]:
        sessions = []
        with self.lock:
            for path in sorted(self.root.glob("admin_*.json"), reverse=True):
                try:
                    item = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                sessions.append({key: item.get(key) for key in (
                    "session_id", "created_at", "updated_at", "state", "active_run_id")})
        return sessions

    def append(self, session_id: str, role: str, content: str, **metadata) -> dict:
        if role not in {"user", "assistant", "activity", "tool"}:
            raise ValueError("Administrator message role is invalid")
        if not isinstance(content, str) or not content.strip() or len(content) > 24_000:
            raise ValueError("Administrator message is invalid")
        clean = redact_text(content)
        if role == "user" and clean != content:
            raise ValueError("Administrator prompt contains secret-shaped data")
        with self.lock:
            session = self.read(session_id)
            message = {"message_id": f"msg_{uuid4().hex[:20]}", "role": role,
                       "content": clean, "created_at": _now(), **metadata}
            session["messages"].append(message)
            session["messages"] = session["messages"][-1000:]
            session["updated_at"] = message["created_at"]
            self._save(session)
            return session

    def set_state(self, session_id: str, state: str, *, active_run_id=None) -> dict:
        if state not in {"idle", "thinking", "running_tool", "blocked", "failed", "cancelled"}:
            raise ValueError("Administrator session state is invalid")
        with self.lock:
            session = self.read(session_id)
            session["state"] = state
            session["updated_at"] = _now()
            if state == "thinking":
                session["cancel_requested"] = False
            if active_run_id is not None:
                session["active_run_id"] = active_run_id
            self._save(session)
            return session

    def cancel(self, session_id: str) -> dict:
        with self.lock:
            session = self.read(session_id)
            session["cancel_requested"] = True
            session["state"] = "cancelled"
            session["updated_at"] = _now()
            self._save(session)
            return session

    def context(self, session_id: str) -> list[dict]:
        messages = self.read(session_id)["messages"]
        selected, size = [], 0
        for item in reversed(messages):
            if item.get("role") not in {"user", "assistant"}:
                continue
            content = item.get("content", "")[:6000]
            if size + len(content) > 12_000 or len(selected) >= 20:
                break
            selected.append({"role": item["role"], "content": content})
            size += len(content)
        return list(reversed(selected))


def administrator_turn(store: AdministratorSessionStore, runtime_gateway, artifact_root: Path,
                       session_id: str, prompt: str) -> dict:
    """Complete one bounded turn; execute only the declared acceptance tool."""
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 12_000:
        raise ValueError("Administrator prompt must contain 1-12000 characters")
    prior = store.context(session_id)
    store.append(session_id, "user", prompt.strip())
    store.set_state(session_id, "thinking")
    if _TECHNICAL_TOOL.search(prompt):
        store.append(session_id, "activity", "Validating governed tool call",
                     activity_state="planned", tool_name="administrator.acceptance.run")
        session = store.read(session_id)
        if session.get("cancel_requested"):
            return store.set_state(session_id, "cancelled")
        store.set_state(session_id, "running_tool")
        store.append(session_id, "tool", "Administrator acceptance tool started",
                     tool_name="administrator.acceptance.run", arguments={"prompt": prompt.strip()})
        run = run_acceptance(prompt, artifact_root)
        store.append(session_id, "tool", "Administrator acceptance tool returned verified evidence",
                     tool_name="administrator.acceptance.run", tool_result={
                         "run_id": run["run_id"], "state": run["state"],
                         "iteration": run["iteration"], "blockers": run["blockers"],
                         "artifacts": run["artifacts"], "rollback": run["rollback"]})
        summary = (f"The governed acceptance tool completed run {run['run_id']} in state "
                   f"{run['state'].replace('_', ' ')} after iteration {run['iteration']}. ")
        summary += ("It is honestly blocked by " + ", ".join(run["blockers"]) + "."
                    if run["blockers"] else "It is Ready for Workbench.")
        store.append(session_id, "assistant", summary, evidence_run_id=run["run_id"])
        return store.set_state(session_id, "blocked" if run["state"] == "blocked" else "idle",
                               active_run_id=run["run_id"])
    if runtime_gateway is None:
        store.append(session_id, "assistant", "The KILN Codex bridge is unavailable. No work was claimed complete.")
        return store.set_state(session_id, "blocked")
    try:
        result = runtime_gateway.invoke(service_id="kiln_codex", bot_id="chatgpt", prompt=prompt,
                                        history=prior, use_tool_broker=False)
        answer = result["summary"]
    except Exception as exc:
        store.append(session_id, "assistant",
                     f"The KILN Codex bridge could not complete this turn ({type(exc).__name__}). No tool ran and no success was recorded.")
        return store.set_state(session_id, "blocked")
    store.append(session_id, "assistant", answer)
    return store.set_state(session_id, "idle")
