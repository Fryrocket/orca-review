#!/usr/bin/env python3
"""Root-side narrow operator for authenticated Master Developer release actions."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import time


REQUESTS = Path("/var/lib/orca/master-operator-requests")
WORKSPACE = Path("/var/lib/orca/master-workspace")
RELEASES = Path("/opt/orca/releases")
CURRENT = Path("/opt/orca/current")
STATE = Path("/var/lib/orca/master-operator-state.json")


def _run(command, timeout=180):
    completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    return completed.returncode, (completed.stdout + completed.stderr)[-16000:]


def _restart() -> dict:
    code, output = _run(["/usr/bin/systemctl", "restart", "orca.service"])
    return {"state": "completed" if code == 0 else "failed", "action": "service.restart",
            "returncode": code, "evidence": output or "systemd restart returned successfully"}


def _deploy() -> dict:
    marker = WORKSPACE / ".master-test.json"
    if not marker.is_file() or not json.loads(marker.read_text()).get("passed"):
        return {"state": "blocked", "action": "release.deploy",
                "reason": "the current candidate has no passing Master Developer test marker"}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    release = RELEASES / f"master-developer-{stamp}"
    previous = str(CURRENT.resolve())
    shutil.copytree(WORKSPACE, release, ignore=shutil.ignore_patterns(
        ".master-test.json", "__pycache__", "*.pyc", "._*", ".DS_Store"))
    temporary = CURRENT.with_name("current.master-next")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(release)
    temporary.replace(CURRENT)
    code, output = _run(["/usr/bin/systemctl", "restart", "orca.service"])
    if code:
        CURRENT.unlink(missing_ok=True); CURRENT.symlink_to(previous)
        _run(["/usr/bin/systemctl", "restart", "orca.service"])
        return {"state": "rolled_back", "action": "release.deploy", "returncode": code,
                "reason": "restart failed", "rollback": previous, "evidence": output}
    STATE.write_text(json.dumps({"previous": previous, "current": str(release),
                                 "deployed_at": stamp}, sort_keys=True) + "\n")
    return {"state": "completed", "action": "release.deploy", "release": str(release),
            "rollback": previous, "evidence": output or "immutable release activated"}


def _rollback() -> dict:
    if not STATE.is_file():
        return {"state": "blocked", "action": "release.rollback", "reason": "no rollback state"}
    state = json.loads(STATE.read_text())
    previous = Path(state.get("previous", ""))
    if RELEASES not in previous.parents or not previous.is_dir():
        return {"state": "blocked", "action": "release.rollback", "reason": "rollback target invalid"}
    CURRENT.unlink(missing_ok=True); CURRENT.symlink_to(previous)
    code, output = _run(["/usr/bin/systemctl", "restart", "orca.service"])
    return {"state": "completed" if code == 0 else "failed", "action": "release.rollback",
            "release": str(previous), "returncode": code, "evidence": output}


def process(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if set(value) != {"action", "arguments", "workspace", "created_at"}:
        raise ValueError("operator request schema invalid")
    if Path(value["workspace"]).resolve() != WORKSPACE.resolve():
        raise PermissionError("operator workspace is not allowlisted")
    action = value["action"]
    if action == "service.restart":
        if value["arguments"].get("service", "orca") != "orca":
            raise PermissionError("only orca.service may be restarted")
        return _restart()
    if action == "release.deploy": return _deploy()
    if action == "release.rollback": return _rollback()
    raise PermissionError("operator action is not allowlisted")


def main() -> None:
    REQUESTS.mkdir(parents=True, exist_ok=True)
    while True:
        for path in sorted(REQUESTS.glob("request-*.json")):
            result = path.with_name(path.name.replace("request-", "result-"))
            if result.exists(): continue
            try: payload = process(path)
            except Exception as exc:
                payload = {"state": "failed", "error": type(exc).__name__}
            temporary = result.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
            temporary.replace(result)
        time.sleep(1)


if __name__ == "__main__":
    main()
