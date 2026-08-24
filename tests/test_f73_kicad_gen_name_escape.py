"""R11-F73 ("kicad_gen name path escape") — a crisp finding.

register_kicad_gen_tools exposes kicad_gen(description, name=...).
ToolRegistry write-path checks look at DEFAULT_PATH_PARAMS
(path/out/dest/…) but not `name`, which looks like a title.
generate_from_nl then does Path(out_dir) / name and writes
.kicad_sch / BOM / notes there.

An agent with HARDWARE_DESIGN can pass name="../outside" (or an
absolute path) and write files outside repo_root — the write
allowlist never sees it.

Fix: name must be a single path segment (no /, no .., not absolute).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mao.errors import HardPrivilegeError
from mao.kicad_gen import generate_from_nl, _safe_project_name


def test_dotdot_name_is_rejected(tmp_path):
    with pytest.raises(HardPrivilegeError, match="single path segment"):
        generate_from_nl("xiao esp32-c3", name="../pwn", out_dir=str(tmp_path))
    assert not (tmp_path.parent / "pwn").exists()
    assert not list(tmp_path.parent.glob("pwn.kicad_sch"))


def test_absolute_name_is_rejected(tmp_path):
    victim = tmp_path.parent / "orca_f73_abs"
    with pytest.raises(HardPrivilegeError, match="single path segment"):
        generate_from_nl("xiao esp32-c3", name=str(victim), out_dir=str(tmp_path))
    assert not victim.exists()


def test_nested_name_is_rejected(tmp_path):
    with pytest.raises(HardPrivilegeError, match="single path segment"):
        generate_from_nl("xiao esp32-c3", name="a/b", out_dir=str(tmp_path))


def test_plain_name_still_writes_under_out_dir(tmp_path):
    r = generate_from_nl("xiao esp32-c3", name="orca_board", out_dir=str(tmp_path))
    assert r["name"] == "orca_board"
    sch = Path(r["schematic"])
    assert sch.exists()
    assert sch.parent == tmp_path / "orca_board"
    assert tmp_path in sch.resolve().parents or sch.resolve().parent == (tmp_path / "orca_board").resolve()


def test_safe_project_name_accepts_simple():
    assert _safe_project_name("orca_board") == "orca_board"
