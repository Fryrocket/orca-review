"""Fry-authenticated Master Developer sessions and technical action broker."""
from __future__ import annotations

from datetime import datetime, timezone
import fnmatch
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from threading import RLock
from urllib.request import urlopen
from uuid import uuid4

from .security import redact_text
from .tools import ToolRequest


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class MasterDeveloperSessionStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve() / "master-developer-sessions"
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()

    def _path(self, session_id: str) -> Path:
        if not isinstance(session_id, str) or not session_id.startswith("master_") or len(session_id) != 31:
            raise ValueError("Master Developer session id is invalid")
        return self.root / f"{session_id}.json"

    def _save(self, value: dict) -> None:
        target = self._path(value["session_id"])
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(target)

    def create(self) -> dict:
        now = _now()
        value = {"session_id": f"master_{uuid4().hex[:24]}", "created_at": now,
                 "updated_at": now, "state": "idle", "messages": [],
                 "capabilities": MasterDeveloperBroker.capabilities()}
        with self.lock:
            self._save(value)
        return value

    def read(self, session_id: str) -> dict:
        path = self._path(session_id)
        if not path.is_file():
            raise FileNotFoundError(session_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def list(self) -> list[dict]:
        result = []
        for path in sorted(self.root.glob("master_*.json"), reverse=True):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                result.append({key: item.get(key) for key in (
                    "session_id", "created_at", "updated_at", "state")})
            except (OSError, json.JSONDecodeError):
                continue
        return result

    def append(self, session_id: str, role: str, content: str, **metadata) -> dict:
        if role not in {"user", "assistant", "activity", "tool"}:
            raise ValueError("Master Developer message role is invalid")
        if not isinstance(content, str) or not content.strip() or len(content) > 64_000:
            raise ValueError("Master Developer message is invalid")
        clean = redact_text(content)
        if role == "user" and clean != content:
            raise ValueError("Master Developer prompt contains secret-shaped data")
        with self.lock:
            value = self.read(session_id)
            message = {"message_id": f"msg_{uuid4().hex[:20]}", "role": role,
                       "content": clean, "created_at": _now(), **metadata}
            value["messages"].append(message)
            value["messages"] = value["messages"][-1500:]
            value["updated_at"] = message["created_at"]
            self._save(value)
            return value

    def set_state(self, session_id: str, state: str) -> dict:
        if state not in {"idle", "planning", "running_tool", "blocked", "failed"}:
            raise ValueError("Master Developer state is invalid")
        with self.lock:
            value = self.read(session_id)
            value["state"] = state
            value["updated_at"] = _now()
            self._save(value)
            return value

    def context(self, session_id: str) -> list[dict]:
        selected, size = [], 0
        for item in reversed(self.read(session_id)["messages"]):
            if item.get("role") not in {"user", "assistant"}:
                continue
            content = item.get("content", "")[:8000]
            if size + len(content) > 16_000 or len(selected) >= 24:
                break
            selected.append({"role": item["role"], "content": content})
            size += len(content)
        return list(reversed(selected))


class MasterDeveloperBroker:
    """Executes explicit technical and connector actions in a rollbackable staging tree."""
    allowed_suffixes = {".py", ".js", ".html", ".css", ".md", ".json", ".toml",
                        ".yaml", ".yml", ".service", ".sh", ".txt"}

    def __init__(self, runtime_gateway, artifact_root: Path):
        self.gateway = runtime_gateway
        self.source = Path(os.environ.get("ORCA_MASTER_SOURCE_ROOT", Path.cwd())).resolve()
        self.workspace = Path(os.environ.get(
            "ORCA_MASTER_WORKSPACE", artifact_root.parent / "master-workspace")).resolve()
        self.rollback = artifact_root / "master-developer-rollback"
        self.rollback.mkdir(parents=True, exist_ok=True)
        self._bootstrap()

    @staticmethod
    def capabilities() -> list[str]:
        return ["ORCA/FORGE repository read, search, edit and diff", "focused and full tests",
                "service and fleet health", "ORCA restart, immutable deploy and rollback",
                "Google Drive search and read", "Notion and Linear lookup when connected",
                "public web search and fetch", "KILN governed browser handoff",
                "audited evidence and rollback snapshots"]

    def _bootstrap(self) -> None:
        if self.workspace.exists():
            return
        ignore = shutil.ignore_patterns(".git", ".venv", "__pycache__", "*.pyc")
        shutil.copytree(self.source, self.workspace, ignore=ignore)

    def _file(self, raw: object) -> Path:
        if not isinstance(raw, str) or not raw or len(raw) > 500:
            raise ValueError("path is invalid")
        candidate = (self.workspace / raw).resolve()
        if self.workspace not in candidate.parents or candidate.suffix not in self.allowed_suffixes:
            raise PermissionError("path is outside the Master Developer workspace")
        return candidate

    def execute(self, name: str, arguments: dict) -> dict:
        if not isinstance(arguments, dict):
            raise ValueError("action arguments must be an object")
        if name == "workspace.summary":
            files = [str(path.relative_to(self.workspace)) for path in self.workspace.rglob("*")
                     if path.is_file() and ".git" not in path.parts]
            return {"workspace": str(self.workspace), "files": files[:500],
                    "truncated": len(files) > 500}
        if name == "file.read":
            path = self._file(arguments.get("path"))
            text = path.read_text(encoding="utf-8")
            return {"path": str(path.relative_to(self.workspace)), "content": text[:64_000],
                    "truncated": len(text) > 64_000}
        if name == "file.search":
            query = arguments.get("query")
            pattern = arguments.get("glob", "*")
            if not isinstance(query, str) or not query or len(query) > 500:
                raise ValueError("search query is invalid")
            matches = []
            for path in self.workspace.rglob("*"):
                if not path.is_file() or not fnmatch.fnmatch(str(path.relative_to(self.workspace)), pattern):
                    continue
                try: text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError): continue
                for number, line in enumerate(text.splitlines(), 1):
                    if query.casefold() in line.casefold():
                        matches.append({"path": str(path.relative_to(self.workspace)),
                                        "line": number, "text": line[:1000]})
                        if len(matches) == 200: return {"matches": matches, "truncated": True}
            return {"matches": matches, "truncated": False}
        if name == "file.write":
            path = self._file(arguments.get("path")); content = arguments.get("content")
            if not isinstance(content, str) or len(content.encode()) > 256_000:
                raise ValueError("file content is invalid or too large")
            if path.exists():
                backup = self.rollback / f"{uuid4().hex}-{path.name}"
                shutil.copy2(path, backup)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(content, encoding="utf-8"); temporary.replace(path)
            (self.workspace / ".master-test.json").unlink(missing_ok=True)
            return {"path": str(path.relative_to(self.workspace)), "bytes": len(content.encode()),
                    "rollback": "preserved"}
        if name == "git.diff":
            result = subprocess.run(["git", "diff", "--no-index", "--", str(self.source),
                                     str(self.workspace)], capture_output=True, text=True, timeout=60)
            return {"diff": result.stdout[-64_000:], "different": result.returncode == 1}
        if name == "tests.run":
            target = arguments.get("target", "focused")
            tests = ["tests_v1"] if target == "focused" else ["tests", "tests_v1"]
            result = subprocess.run([sys.executable, "-m", "pytest", "-q", *tests],
                                    cwd=self.workspace, capture_output=True, text=True, timeout=900)
            output = {"passed": result.returncode == 0, "returncode": result.returncode,
                      "output": (result.stdout + result.stderr)[-64_000:]}
            if output["passed"]:
                (self.workspace / ".master-test.json").write_text(json.dumps({
                    "passed": True, "completed_at": _now(), "target": target}) + "\n",
                    encoding="utf-8")
            return output
        if name == "health.check":
            with urlopen("http://127.0.0.1:8787/api/health", timeout=10) as response:
                return json.load(response)
        if name in {"drive.search", "drive.read", "notion.read", "linear.read",
                    "web.search", "web.fetch", "node.observe", "studio.capabilities"}:
            broker = getattr(self.gateway, "tool_broker", None)
            if broker is None:
                raise RuntimeError("connector broker is unavailable")
            result = broker.execute(bot_id="orca", requests=[ToolRequest(name, arguments)])[0]
            return {"connector": name, "output": result.output}
        if name == "browser.open":
            url = arguments.get("url")
            if not isinstance(url, str) or not url.startswith("https://") or len(url) > 2000:
                raise ValueError("browser URL must be a bounded HTTPS URL")
            return {"state": "ready_for_kiln_browser", "url": url,
                    "instruction": "Open through the native KILN Studio governed browser bridge"}
        if name in {"service.restart", "release.deploy", "release.rollback"}:
            return self._operator(name, arguments)
        raise PermissionError(f"Master Developer action is not registered: {name}")

    def _operator(self, name: str, arguments: dict) -> dict:
        request_dir = self.workspace.parent / "master-operator-requests"
        request_dir.mkdir(parents=True, exist_ok=True)
        request_id = f"request-{uuid4().hex}.json"
        target = request_dir / request_id
        target.write_text(json.dumps({"action": name, "arguments": arguments,
                                     "workspace": str(self.workspace), "created_at": _now()},
                                    sort_keys=True) + "\n", encoding="utf-8")
        result = request_dir / request_id.replace("request-", "result-")
        for _ in range(180):
            if result.is_file():
                return json.loads(result.read_text(encoding="utf-8"))
            time.sleep(1)
        return {"state": "submitted", "request_id": request_id,
                "evidence": "owner-authenticated operator request recorded; result pending"}


def master_developer_turn(store: MasterDeveloperSessionStore, runtime_gateway,
                          artifact_root: Path, session_id: str, prompt: str) -> dict:
    if runtime_gateway is None or not hasattr(runtime_gateway, "master_developer_plan"):
        raise RuntimeError("Master Developer runtime is unavailable")
    prior = store.context(session_id)
    store.append(session_id, "user", prompt.strip())
    store.set_state(session_id, "planning")
    broker = MasterDeveloperBroker(runtime_gateway, artifact_root)
    evidence = []
    for _iteration in range(6):
        plan = runtime_gateway.master_developer_plan(prompt=prompt, history=prior, evidence=evidence)
        store.append(session_id, "activity", plan["reason"], activity_state="planned")
        for action in plan["actions"]:
            name, arguments = action["name"], action["arguments"]
            if name == "respond":
                message = arguments.get("message")
                if not isinstance(message, str) or not message.strip():
                    raise ValueError("Master Developer response is invalid")
                store.append(session_id, "assistant", message, evidence=evidence[-12:])
                return store.set_state(session_id, "idle")
            store.set_state(session_id, "running_tool")
            store.append(session_id, "tool", f"Running {name}", tool_name=name,
                         arguments=arguments)
            try:
                output = broker.execute(name, arguments)
                item = {"name": name, "status": "completed", "output": output}
            except Exception as exc:
                item = {"name": name, "status": "blocked", "error": type(exc).__name__}
            evidence.append(item)
            store.append(session_id, "tool", f"{name}: {item['status']}", tool_name=name,
                         tool_result=item)
        store.set_state(session_id, "planning")
    store.append(session_id, "assistant",
                 "The bounded technical loop reached its six-iteration ceiling. All evidence is preserved; no unverified success was recorded.",
                 evidence=evidence[-12:])
    return store.set_state(session_id, "blocked")
