"""R11-F76 ("kicad_gen cwd out_dir escape") — a crisp finding.

register_kicad_gen_tools exposes kicad_gen(description, name=...) which
calls generate_from_nl with the default out_dir="runs/kicad_projects".
That path is cwd-relative and is not a tool argument, so ToolRegistry
write-path checks never see it.

F73 made `name` a single path segment. A safe name still wrote
cwd/runs/kicad_projects/<name>/ when cwd was not repo_root — outside
the write allowlist.

Fix: the tool pins out_dir to registry.repo_root/runs/kicad_projects.
The library generate_from_nl(out_dir=...) API is unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mao.errors import HardPrivilegeError
from mao.kicad_gen import generate_from_nl, register_kicad_gen_tools
from mao.roles import PrivilegeBroker
from mao.tools import ToolRegistry


def test_tool_writes_under_repo_root_not_cwd(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    cwd = tmp_path / "elsewhere"
    for d in ("runs", "mao", "orca-out", "examples"):
        (repo / d).mkdir(parents=True)
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setenv("ORCA_PROFILE", "test")
    monkeypatch.setenv("ORCA_REPO_ROOT", str(repo))

    broker = PrivilegeBroker(enforce=True)
    reg = ToolRegistry(broker=broker, repo_root_path=repo)
    register_kicad_gen_tools(reg)
    broker.start_turn("ampere")
    out = reg.call("kicad_gen", agent="ampere", description="xiao esp32-c3")

    board = repo / "runs" / "kicad_projects" / "orca_board"
    assert (board / "orca_board.kicad_sch").is_file()
    assert str(board) in out
    leaked = cwd / "runs" / "kicad_projects" / "orca_board"
    assert not leaked.exists()


def test_library_out_dir_still_honoured(tmp_path):
    r = generate_from_nl("xiao esp32-c3", name="lib_board", out_dir=str(tmp_path))
    sch = Path(r["schematic"])
    assert sch.exists()
    assert sch.parent == tmp_path / "lib_board"


def test_safe_name_still_required_via_tool(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    for d in ("runs", "mao", "orca-out", "examples"):
        (repo / d).mkdir(parents=True)
    monkeypatch.setenv("ORCA_PROFILE", "test")
    monkeypatch.setenv("ORCA_REPO_ROOT", str(repo))
    broker = PrivilegeBroker(enforce=True)
    reg = ToolRegistry(broker=broker, repo_root_path=repo)
    register_kicad_gen_tools(reg)
    broker.start_turn("ampere")
    with pytest.raises(HardPrivilegeError, match="single path segment"):
        # ToolRegistry.call(name, ...) owns the `name` kwarg; pass the
        # project name positionally as kicad_gen(description, name).
        reg.call("kicad_gen", "xiao esp32-c3", "../pwn", agent="ampere")
    assert not list(tmp_path.rglob("pwn.kicad_sch"))
