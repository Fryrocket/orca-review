"""R11-F72 ("read_file path escape") — a crisp finding.

ToolRegistry.call() ran _check_write_paths only when write_class is not
None. Read-only tools (read_file, search_code, …) were catalog-gated
via tools_allowed and then invoked with no path containment.

register_code_tools.read_file does `(root / path).resolve()` and reads
whatever exists — Path join with `../` or an absolute path escapes
repo_root. Writes were already blocked (test_escape_outside_repo_root_blocked);
reads were not. An agent whose tools_allowed includes read_file (Claude,
Ampere, Relay, Grok-*) can dump host files.

Fix: read-only tools still must resolve inside repo_root. WRITE_ALLOWLIST
must not apply to reads (D4 — docs/ and mao/ stay readable).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mao.errors import HardPrivilegeError
from mao.roles import PrivilegeBroker
from mao.tools import ToolRegistry


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("ORCA_PROFILE", "test")
    monkeypatch.delenv("ORCA_REPO_ROOT", raising=False)
    monkeypatch.delenv("MAO_REPO_ROOT", raising=False)
    return monkeypatch


@pytest.fixture
def repo(tmp_path, env):
    env.setenv("ORCA_REPO_ROOT", str(tmp_path))
    for d in ("runs", "mao", "orca-out", "examples", "docs"):
        (tmp_path / d).mkdir()
    return tmp_path


def _leaky_read(root: Path):
    def read_file(path: str) -> str:
        return (root / path).resolve().read_text(errors="replace")[:8000]

    return read_file


def test_relative_escape_on_read_is_blocked(repo):
    """The bug: ../secret.txt used to be returned as file contents."""
    secret = repo.parent / "orca_f72_secret.txt"
    secret.write_text("LEAKME")
    broker = PrivilegeBroker(enforce=True)
    reg = ToolRegistry(broker=broker, repo_root_path=repo)
    reg.register_function("read_file", "r", _leaky_read(reg.repo_root))
    with pytest.raises(HardPrivilegeError, match=r"path outside repo root"):
        reg.call("read_file", agent="claude", path=f"../{secret.name}")


def test_absolute_path_outside_repo_on_read_is_blocked(repo):
    secret = repo.parent / "orca_f72_abs_secret.txt"
    secret.write_text("LEAKABS")
    broker = PrivilegeBroker(enforce=True)
    reg = ToolRegistry(broker=broker, repo_root_path=repo)
    reg.register_function("read_file", "r", _leaky_read(reg.repo_root))
    with pytest.raises(HardPrivilegeError, match=r"path outside repo root"):
        reg.call("read_file", agent="claude", path=str(secret))


def test_in_repo_docs_read_still_allowed(repo):
    """D4 regression: WRITE_ALLOWLIST must not gate reads of docs/."""
    (repo / "docs" / "PI5.md").write_text("docs-ok")
    broker = PrivilegeBroker(enforce=True)
    reg = ToolRegistry(broker=broker, repo_root_path=repo)
    reg.register_function("read_file", "r", _leaky_read(reg.repo_root))
    assert reg.call("read_file", agent="claude", path="docs/PI5.md") == "docs-ok"


def test_in_repo_mao_read_still_allowed(repo):
    (repo / "mao" / "roles.py").write_text("# roles")
    broker = PrivilegeBroker(enforce=True)
    reg = ToolRegistry(broker=broker, repo_root_path=repo)
    reg.register_function("read_file", "r", _leaky_read(reg.repo_root))
    assert "# roles" in reg.call("read_file", agent="claude", path="mao/roles.py")
