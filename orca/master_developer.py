"""Fry-authenticated Master Developer sessions and technical action broker."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import difflib
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


def _planner_evidence(evidence: list[dict]) -> list[dict]:
    """Keep iterative model context bounded while preserving durable full evidence."""
    keyed = {}
    for index, item in enumerate(evidence):
        key = item.get("name", "unknown")
        output = item.get("output")
        if isinstance(output, dict):
            nested = output.get("output") if isinstance(output.get("output"), dict) else output
            path = nested.get("path") if isinstance(nested, dict) else None
            if isinstance(path, str):
                key = f"{key}:{path}"
        keyed[key] = (index, item)
    selected = [item for _index, item in sorted(keyed.values())[-18:]]
    compact = []
    budget = 0
    for item in selected:
        raw = json.dumps(item, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False)
        if len(raw) <= 6_000 and budget + len(raw) <= 32_000:
            compact.append(item)
            budget += len(raw)
            continue
        bounded = {
            "name": item.get("name"),
            "status": item.get("status"),
            "truncated_for_planning": True,
            "original_chars": len(raw),
            "evidence_excerpt": redact_text(raw[:1_450] + "\n...[bounded]...\n" + raw[-1_450:]),
        }
        compact.append(bounded)
        budget += len(json.dumps(bounded))
    return compact


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
        return sorted(result, key=lambda item: item.get("updated_at") or "", reverse=True)

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
        self.artifact_root = Path(artifact_root).resolve()
        self.source = Path(os.environ.get("ORCA_MASTER_SOURCE_ROOT", Path.cwd())).resolve()
        self.workspace = Path(os.environ.get(
            "ORCA_MASTER_WORKSPACE", artifact_root.parent / "master-workspace")).resolve()
        self.rollback = artifact_root / "master-developer-rollback"
        self.baseline = self.artifact_root / "master-workspace-baseline.json"
        self.rollback.mkdir(parents=True, exist_ok=True)
        self._bootstrap()

    @staticmethod
    def capabilities() -> list[str]:
        return ["ORCA/FORGE repository read, search, edit and diff", "focused and full tests",
                "service and fleet health", "ORCA restart, immutable deploy and rollback",
                "Google Drive search and read", "Notion and Linear lookup when connected",
                "public web search and fetch", "KILN governed browser handoff",
                "audited evidence and rollback snapshots"]

    @staticmethod
    def _link_state(path: Path) -> dict:
        try:
            return {"path": str(path), "exists": path.exists(),
                    "target": str(path.resolve(strict=True))}
        except (OSError, RuntimeError):
            return {"path": str(path), "exists": False, "target": None}

    def _session_index(self, directory: str, prefix: str, limit: int = 12) -> dict:
        root = self.artifact_root / directory
        items = []
        for path in root.glob(f"{prefix}*.json") if root.is_dir() else ():
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            messages = value.get("messages") if isinstance(value.get("messages"), list) else []
            recent = []
            for message in messages:
                if message.get("role") not in {"user", "assistant"}:
                    continue
                content = message.get("content")
                if isinstance(content, str):
                    recent.append({"role": message.get("role"),
                                   "content_excerpt": content[:500]})
            items.append({
                "session_id": value.get("session_id"),
                "created_at": value.get("created_at"),
                "updated_at": value.get("updated_at"),
                "state": value.get("state"),
                "message_count": len(messages),
                "last_role": messages[-1].get("role") if messages else None,
                "recent_conversation": recent[-2:],
            })
        items.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
        return {"count": len(items), "sessions": items[:limit],
                "truncated": len(items) > limit}

    def _sessions_inspect(self, *, kind: str = "all", limit: int = 12) -> dict:
        if kind not in {"all", "master", "administrator"}:
            raise ValueError("session kind must be all, master or administrator")
        if type(limit) is not int or not 1 <= limit <= 25:
            raise ValueError("session limit must be 1-25")
        result = {"kind": kind}
        if kind in {"all", "master"}:
            result["master"] = self._session_index(
                "master-developer-sessions", "master_", limit)
        if kind in {"all", "administrator"}:
            result["administrator"] = self._session_index(
                "administrator-sessions", "admin_", limit)
        return result

    def _repository_inspect(self) -> dict:
        diff = subprocess.run(
            ["git", "diff", "--no-index", "--stat", "--", str(self.source),
             str(self.workspace)], capture_output=True, text=True, timeout=60)
        github = subprocess.run(
            ["git", "ls-remote", "--heads",
             "https://github.com/Fryrocket/orca-review.git", "main",
             "agent/orca-rebuild-v1"], capture_output=True, text=True, timeout=30,
            env={"PATH": "/usr/bin:/bin", "GIT_TERMINAL_PROMPT": "0"})
        heads = {}
        if github.returncode == 0:
            for line in github.stdout.splitlines():
                fields = line.split()
                if len(fields) == 2:
                    heads[fields[1].removeprefix("refs/heads/")] = fields[0]
        return {
            "source_release": self._link_state(Path("/opt/orca/current")),
            "previous_release": self._link_state(Path("/var/lib/orca/previous-release")),
            "workspace": str(self.workspace),
            "workspace_differs": diff.returncode == 1,
            "diff_stat": (diff.stdout + diff.stderr)[-12_000:],
            "github": {"reachable": github.returncode == 0, "heads": heads},
            "gitea": {"source": "timestamped external-record snapshot",
                      "direct_from_forge": "network path unavailable"},
        }

    def _audit_snapshot(self) -> dict:
        snapshot = {"generated_at": _now(), "mutated": False}
        try:
            with urlopen("http://127.0.0.1:8787/api/health", timeout=10) as response:
                snapshot["health"] = json.load(response)
        except Exception as exc:
            snapshot["health"] = {"status": "unavailable", "error": type(exc).__name__}
        broker = getattr(self.gateway, "tool_broker", None)
        for key, name, arguments in (
            ("fleet", "node.observe", {"node_id": "all"}),
            ("studio", "studio.capabilities", {"area": "tools"}),
        ):
            try:
                result = broker.execute(
                    bot_id="orca", requests=[ToolRequest(name, arguments)])[0]
                output = result.output
                if key == "fleet" and isinstance(output, dict):
                    output = {
                        "evidence_chain_valid": output.get("evidence_chain_valid"),
                        "emergency_stop": output.get("emergency_stop"),
                        "paused_nodes": output.get("paused_nodes", []),
                        "paused_lanes": output.get("paused_lanes", []),
                        "nodes": [{field: node.get(field) for field in (
                            "id", "name", "state", "last_verified", "paused",
                            "pause_reasons", "detail", "remote_execution_enabled")}
                            for node in output.get("nodes", []) if isinstance(node, dict)],
                    }
                if key == "studio" and isinstance(output, dict):
                    tools = output.get("read_tools", {})
                    connectors = output.get("connectors", [])
                    output = {
                        "read_tools": sorted(tools) if isinstance(tools, dict) else tools,
                        "connectors": [{
                            "connector": connector.get("connector"),
                            "operations": connector.get("operations", []),
                            "writes_enabled": connector.get("writes_enabled"),
                        } for connector in connectors if isinstance(connector, dict)],
                        "governance": output.get("governance"),
                        "core_authority": output.get("core_authority"),
                    }
                snapshot[key] = output
            except Exception as exc:
                snapshot[key] = {"status": "unavailable", "error": type(exc).__name__}
        external_path = "cc-bridge/CC_ORCA_external_records_2026-10-03.md"
        try:
            result = broker.execute(bot_id="orca", requests=[
                ToolRequest("drive.read", {"path": external_path})])[0]
            raw = json.dumps(result.output, sort_keys=True, ensure_ascii=False)
            snapshot["external_records"] = {
                "status": "available", "path": external_path,
                "sha256": hashlib.sha256(raw.encode()).hexdigest(),
                "chars": len(raw),
                "instruction": "Use drive.read on this path for the full timestamped Notion, Linear, GitHub and Gitea index.",
            }
        except Exception as exc:
            snapshot["external_records"] = {
                "status": "unavailable", "path": external_path,
                "error": type(exc).__name__,
            }
        snapshot["releases"] = {
            "current": self._link_state(Path("/opt/orca/current")),
            "previous": self._link_state(Path("/var/lib/orca/previous-release")),
        }
        snapshot["sessions"] = self._sessions_inspect(kind="all", limit=8)
        return snapshot

    @staticmethod
    def _tree_manifest(root: Path) -> dict[str, str]:
        manifest = {}
        for path in root.rglob("*"):
            if (not path.is_file() or ".git" in path.parts or "__pycache__" in path.parts
                    or path.name == ".master-test.json" or path.suffix == ".pyc"):
                continue
            relative = str(path.relative_to(root))
            try:
                manifest[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                continue
        return manifest

    def _write_baseline(self, manifest: dict[str, str]) -> None:
        temporary = self.baseline.with_suffix(".tmp")
        temporary.write_text(json.dumps({"created_at": _now(), "manifest": manifest},
                                        sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(self.baseline)

    def _diff_evidence(self) -> dict:
        source_manifest = self._tree_manifest(self.source)
        workspace_manifest = self._tree_manifest(self.workspace)
        changed = sorted(
            path for path in set(source_manifest) | set(workspace_manifest)
            if source_manifest.get(path) != workspace_manifest.get(path)
        )
        chunks = []
        for relative in changed:
            source = self.source / relative
            workspace = self.workspace / relative
            try:
                before = source.read_text(encoding="utf-8").splitlines(keepends=True) \
                    if source.is_file() else []
                after = workspace.read_text(encoding="utf-8").splitlines(keepends=True) \
                    if workspace.is_file() else []
            except (OSError, UnicodeDecodeError):
                chunks.append(f"Binary files differ: {relative}\n")
                continue
            chunks.extend(difflib.unified_diff(
                before, after, fromfile=f"a/{relative}", tofile=f"b/{relative}"))
        receipts_path = self.artifact_root / "master-test-receipts" / "latest.json"
        try:
            receipts = json.loads(receipts_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            receipts = None
        return {"diff": "".join(chunks)[-64_000:], "different": bool(changed),
                "files": changed, "test_receipts": receipts}

    def _bootstrap(self) -> None:
        ignore = shutil.ignore_patterns(".git", ".venv", "__pycache__", "*.pyc")
        source_manifest = self._tree_manifest(self.source)
        if self.workspace.exists():
            try:
                baseline = json.loads(self.baseline.read_text(encoding="utf-8"))["manifest"]
            except (OSError, KeyError, TypeError, json.JSONDecodeError):
                return
            workspace_manifest = self._tree_manifest(self.workspace)
            if workspace_manifest != baseline or source_manifest == baseline:
                return
            archive = self.rollback / f"workspace-refresh-{uuid4().hex}"
            self.workspace.replace(archive)
            shutil.copytree(self.source, self.workspace, ignore=ignore)
            self._write_baseline(source_manifest)
            return
        shutil.copytree(self.source, self.workspace, ignore=ignore)
        self._write_baseline(source_manifest)

    def _file(self, raw: object) -> Path:
        if not isinstance(raw, str) or not raw or len(raw) > 500:
            raise ValueError("path is invalid")
        candidate = (self.workspace / raw).resolve()
        if self.workspace not in candidate.parents or candidate.suffix not in self.allowed_suffixes:
            raise PermissionError("path is outside the Master Developer workspace")
        return candidate

    def _test_python(self) -> Path:
        configured = os.environ.get("ORCA_MASTER_TEST_PYTHON")
        if configured:
            candidate = Path(configured)
            if not candidate.is_file() or not os.access(candidate, os.X_OK):
                raise RuntimeError("configured Master Developer test Python is unavailable")
            return candidate
        candidates = (
            self.workspace / ".venv/bin/python",
            self.source / ".venv/bin/python",
            Path("/var/lib/orca/test-venv/bin/python"),
            Path(sys.executable),
        )
        for candidate in candidates:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                probe = subprocess.run(
                    [str(candidate), "-c", "import pytest"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, timeout=15,
                )
                if probe.returncode == 0:
                    return candidate
        raise RuntimeError("no verified pytest-capable Master Developer test Python is available")

    def _test_environment(self) -> dict[str, str]:
        test_home = self.artifact_root / "master-test-home"
        test_home.mkdir(parents=True, exist_ok=True)
        environment = {
            "HOME": str(test_home),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONPATH": str(self.workspace),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_ADDOPTS": "-p no:cacheprovider",
        }
        for name in ("LANG", "LC_ALL", "TMPDIR"):
            value = os.environ.get(name)
            if value:
                environment[name] = value
        return environment

    def execute(self, name: str, arguments: dict) -> dict:
        if not isinstance(arguments, dict):
            raise ValueError("action arguments must be an object")
        if name == "workspace.summary":
            files = [str(path.relative_to(self.workspace)) for path in self.workspace.rglob("*")
                     if path.is_file() and ".git" not in path.parts]
            return {"workspace": str(self.workspace), "files": files[:500],
                    "truncated": len(files) > 500}
        if name == "audit.snapshot":
            return self._audit_snapshot()
        if name == "sessions.inspect":
            return self._sessions_inspect(
                kind=arguments.get("kind", "all"), limit=arguments.get("limit", 12))
        if name == "repository.inspect":
            return self._repository_inspect()
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
            (self.artifact_root / "master-test-receipts" / "latest.json").unlink(
                missing_ok=True)
            return {"path": str(path.relative_to(self.workspace)), "bytes": len(content.encode()),
                    "rollback": "preserved"}
        if name == "git.diff":
            return self._diff_evidence()
        if name == "tests.run":
            target = arguments.get("target", "focused")
            if target not in {"focused", "full"}:
                raise ValueError("test target must be focused or full")
            tests = ["tests_v1"] if target == "focused" else ["tests", "tests_v1"]
            test_python = self._test_python()
            result = subprocess.run([str(test_python), "-m", "pytest", "-q", *tests],
                                    cwd=self.workspace, capture_output=True, text=True, timeout=900,
                                    env=self._test_environment())
            output = {"passed": result.returncode == 0, "returncode": result.returncode,
                      "output": (result.stdout + result.stderr)[-64_000:],
                      "runner": str(test_python), "target": target}
            if output["passed"]:
                receipts = self.artifact_root / "master-test-receipts"
                receipts.mkdir(parents=True, exist_ok=True)
                receipt_path = receipts / "latest.json"
                try:
                    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    receipt = {"results": {}}
                receipt.setdefault("results", {})[target] = {
                    "passed": True, "completed_at": _now(), "target": target,
                    "workspace": str(self.workspace), "output": output["output"][-4000:],
                }
                receipt.update({"passed": True, "completed_at": _now(), "target": target,
                                "workspace": str(self.workspace)})
                receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n",
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
        request_dir.chmod(0o770)
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


def _completed_output(evidence: list[dict], name: str) -> object:
    for item in reversed(evidence):
        if item.get("name") == name and item.get("status") == "completed":
            return item.get("output")
    return None


def _acceptance_followup(prompt: str, evidence: list[dict]) -> dict | None:
    normalized = prompt.casefold()
    if not ("focused" in normalized and "full" in normalized
            and "final diff" in normalized):
        return None
    completed = [
        (index, item.get("name"), item.get("output"))
        for index, item in enumerate(evidence)
        if item.get("status") == "completed"
    ]
    focused = [
        index for index, name, output in completed
        if name == "tests.run" and isinstance(output, dict)
        and output.get("target") == "focused" and output.get("passed") is True
    ]
    if not focused:
        return {"name": "tests.run", "arguments": {"target": "focused"}}
    full = [
        index for index, name, output in completed
        if index > focused[-1] and name == "tests.run" and isinstance(output, dict)
        and output.get("target") == "full" and output.get("passed") is True
    ]
    if not full:
        return {"name": "tests.run", "arguments": {"target": "full"}}
    final_diffs = [
        output for index, name, output in completed
        if index > full[-1] and name == "git.diff" and isinstance(output, dict)
    ]
    if not final_diffs:
        return {"name": "git.diff", "arguments": {}}
    receipts = final_diffs[-1].get("test_receipts")
    results = receipts.get("results", {}) if isinstance(receipts, dict) else {}
    if not all(isinstance(results.get(target), dict)
               and results[target].get("passed") is True
               for target in ("focused", "full")):
        return {"name": "git.diff", "arguments": {}}
    return None


def _deterministic_audit_checkpoint(evidence: list[dict]) -> str:
    snapshot = _completed_output(evidence, "audit.snapshot")
    repository = _completed_output(evidence, "repository.inspect")
    sessions = _completed_output(evidence, "sessions.inspect")
    state_record = _completed_output(evidence, "file.read")
    external = _completed_output(evidence, "drive.read")
    health = _completed_output(evidence, "health.check")
    fleet = _completed_output(evidence, "node.observe")
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    repository = repository if isinstance(repository, dict) else {}
    health = health if isinstance(health, dict) else snapshot.get("health", {})
    fleet = fleet if isinstance(fleet, dict) else snapshot.get("fleet", {})
    if isinstance(fleet, dict) and isinstance(fleet.get("output"), dict):
        fleet = fleet["output"]
    if isinstance(external, dict) and isinstance(external.get("output"), dict):
        external = external["output"]
    nodes = fleet.get("nodes", []) if isinstance(fleet, dict) else []
    node_lines = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_lines.append(
            f"- {node.get('name') or node.get('id', 'unknown')}: "
            f"{node.get('state', 'unproven')}; paused={bool(node.get('paused'))}; "
            f"last verified {node.get('last_verified') or 'unavailable'}; "
            f"{node.get('detail') or 'no detail'}")
    current = repository.get("source_release", {})
    previous = repository.get("previous_release", {})
    github = repository.get("github", {})
    gitea = repository.get("gitea", {})
    external_path = snapshot.get("external_records", {}).get("path", "unavailable")
    state_read = isinstance(state_record, dict) and isinstance(
        state_record.get("content"), str)
    external_read = isinstance(external, dict) and isinstance(
        external.get("text"), str)
    session_count = "unavailable"
    if isinstance(sessions, dict):
        session_count = sum(
            value.get("count", 0) for key, value in sessions.items()
            if key in {"master", "administrator"} and isinstance(value, dict))
    paused = fleet.get("paused_nodes", []) if isinstance(fleet, dict) else []
    return "\n".join([
        "Consolidated ORCA/FORGE checkpoint — deterministic evidence recovery",
        "",
        "1. Current-state briefing",
        f"ORCA health is {health.get('status', 'unproven')} with integrity_valid="
        f"{health.get('integrity_valid', 'unproven')}. The current immutable release is "
        f"{current.get('target', 'unavailable')}; rollback points to "
        f"{previous.get('target', 'unavailable')}. This checkpoint used only completed "
        "read-only tool evidence and performed no mutation.",
        "",
        "2. Completed and proven",
        f"- Repository inspection completed. workspace_differs="
        f"{repository.get('workspace_differs', 'unproven')}.",
        f"- GitHub reachable={github.get('reachable', 'unproven')}; heads="
        f"{json.dumps(github.get('heads', {}), sort_keys=True)}.",
        f"- STATE_v12_upload.md read completed={state_read}.",
        f"- External records read completed={external_read} from {external_path}.",
        f"- Master/Administrator session histories inspected; session count={session_count}.",
        "",
        "3. Actively running / observed fleet",
        *(node_lines or ["- No completed signed node observation was available."]),
        "",
        "4. Unfinished",
        "- Planned, staged and historical claims still require their own acceptance evidence; "
        "repository presence and record entries are not proof of live completion.",
        "- Physical hardware, power-loss, fit, thermal and fabrication checks remain physical "
        "gates wherever the inspected records require them.",
        "",
        "5. Blocked and why",
        f"- Paused nodes: {json.dumps(paused)}. Resume only after a fresh authenticated healthy "
        "heartbeat proves the reported cause has cleared.",
        f"- Direct Gitea inspection from FORGE: {gitea.get('direct_from_forge', 'unproven')}; "
        "the timestamped external record is the available corroborating source.",
        "- Any source not marked read-completed above remains unproven, not silently complete.",
        "",
        "6. Ordered master task list",
        "1) Restore and re-verify any degraded or paused node without weakening safeguards.",
        "2) Reconcile STATE, Drive, Notion and Linear against the inspected release and evidence.",
        "3) Resolve direct Gitea observability or keep timestamped external push evidence explicit.",
        "4) Run the appropriate software acceptance suite for the deployed commit and preserve results.",
        "5) Complete remaining physical acceptance gates with owner-present evidence.",
        "6) Deduplicate stale or contradictory records only after verified reconciliation.",
        "",
        "7. Safest autonomous next action",
        "Perform bounded read-only health verification for every node and service, then reconcile "
        "the resulting evidence into the existing records without creating duplicates.",
        "",
        "8. What genuinely requires you",
        "Only owner-present physical tests, credential or account authorization, money, legal "
        "acceptance, publishing, permission changes, and any other existing R3 approval gate.",
        "",
        "Provider JSON failed repeatedly, so ORCA completed this audit through its deterministic "
        "read-only recovery path rather than returning a false success or asking you to retry.",
    ])


def master_developer_turn(store: MasterDeveloperSessionStore, runtime_gateway,
                          artifact_root: Path, session_id: str, prompt: str) -> dict:
    if runtime_gateway is None or not hasattr(runtime_gateway, "master_developer_plan"):
        raise RuntimeError("Master Developer runtime is unavailable")
    prior = store.context(session_id)
    store.append(session_id, "user", prompt.strip())
    store.set_state(session_id, "planning")
    broker = MasterDeveloperBroker(runtime_gateway, artifact_root)
    evidence = []
    audit_request = any(phrase in prompt.casefold() for phrase in (
        "catch yourself up", "ecosystem audit", "reconcile all"))
    for _iteration in range(10):
        planning_evidence = _planner_evidence(evidence)
        plan, planning_error = None, None
        for attempt in range(2):
            retry_note = (
                "\n\nContract retry: return only one valid action-plan JSON object matching "
                "the supplied schema; do not add prose outside it."
                if attempt else ""
            )
            try:
                plan = runtime_gateway.master_developer_plan(
                    prompt=prompt + retry_note, history=prior,
                    evidence=planning_evidence, final=_iteration == 5)
                break
            except Exception as exc:
                planning_error = exc
        if plan is None and not evidence and _iteration == 0 and audit_request:
            plan = {
                "reason": (
                    "The model planning contract failed twice before evidence collection; "
                    "start the requested read-only ecosystem audit through the deterministic "
                    "bounded evidence actions."
                ),
                "actions": [
                    {"name": "audit.snapshot", "arguments": {}},
                    {"name": "repository.inspect", "arguments": {}},
                    {"name": "sessions.inspect", "arguments": {
                        "kind": "all", "limit": 12}},
                ],
            }
        elif plan is None and audit_request:
            attempted = {item.get("name") for item in evidence}
            supplemental = []
            if "file.read" not in attempted:
                supplemental.append({"name": "file.read", "arguments": {
                    "path": "docs/STATE_v12_upload.md"}})
            if "drive.read" not in attempted:
                supplemental.append({"name": "drive.read", "arguments": {
                    "path": "cc-bridge/CC_ORCA_external_records_2026-10-03.md"}})
            if "health.check" not in attempted:
                supplemental.append({"name": "health.check", "arguments": {}})
            if "node.observe" not in attempted:
                supplemental.append({"name": "node.observe", "arguments": {}})
            if supplemental:
                plan = {
                    "reason": (
                        "The provider planning contract remained malformed after the initial "
                        "audit evidence. Continue the same read-only audit through the remaining "
                        "deterministic authoritative sources before synthesis."
                    ),
                    "actions": supplemental[:6],
                }
            else:
                plan = {
                    "reason": (
                        "The provider planning contract remained malformed after authoritative "
                        "evidence collection. Return the deterministic evidence checkpoint so "
                        "the audit completes truthfully instead of stalling."
                    ),
                    "actions": [{"name": "respond", "arguments": {
                        "message": _deterministic_audit_checkpoint(evidence)}}],
                }
        elif plan is None:
            exc = planning_error
            store.append(
                session_id, "assistant",
                "Master Developer could not complete the next planning pass. "
                f"The provider stopped with {type(exc).__name__}; completed tool evidence is "
                "preserved and no unverified success was recorded. Retry this request to resume "
                "from the durable session evidence.",
                evidence=planning_evidence,
            )
            return store.set_state(session_id, "failed")
        store.append(session_id, "activity", plan["reason"], activity_state="planned")
        if any(action.get("name") == "respond" for action in plan["actions"]):
            followup = _acceptance_followup(prompt, evidence)
            if followup is not None:
                plan = {
                    "reason": (
                        "The deterministic acceptance controller requires a passing focused "
                        "suite, then a passing full suite, then a fresh final diff carrying "
                        "both receipts before a completion response is allowed."
                    ),
                    "actions": [followup],
                }
        for action in plan["actions"]:
            name = action["name"]
            arguments = action.get("arguments")
            if arguments is None:
                arguments = json.loads(action.get("arguments_json", "{}"))
            if not isinstance(arguments, dict):
                raise ValueError("Master Developer action arguments are invalid")
            if name == "respond":
                message = arguments.get("message")
                if not isinstance(message, str) or not message.strip():
                    raise ValueError("Master Developer response is invalid")
                store.append(session_id, "assistant", message,
                             evidence=_planner_evidence(evidence))
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
                 "The bounded technical loop reached its ten-iteration ceiling. All evidence is preserved; no unverified success was recorded.",
                 evidence=_planner_evidence(evidence))
    return store.set_state(session_id, "blocked")
