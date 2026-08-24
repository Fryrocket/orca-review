"""R11-F78 ("persist corrupt JSON kills load") — a crisp finding.

save_blackboard used path.write_text (not atomic). A crash mid-write
left truncated JSON; load_blackboard then raised JSONDecodeError.
meta keys that collide with commit() kwargs (e.g. timestamp) TypeError'd.
entries not a list AttributeError'd.

Fix: atomic tmp+replace save; soft-load JSON/shape errors; strip reserved
meta keys; skip rows that still cannot commit. HardPrivilegeError still
raises (denied writer must not silently skip).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mao.blackboard import Blackboard
from mao.errors import HardPrivilegeError
from mao.persist import load_blackboard, save_blackboard
from mao.roles import Privilege, PrivilegeBroker


def test_truncated_json_does_not_kill(tmp_path):
    src = Blackboard(guard=lambda w, k: None)
    src.commit("k", "v", writer="grok")
    path = tmp_path / "board.json"
    save_blackboard(src, path)
    path.write_text(path.read_text()[:40])
    dst = Blackboard(guard=lambda w, k: None)
    load_blackboard(path, dst)
    assert "k" not in dst


def test_meta_timestamp_collision_still_loads(tmp_path):
    path = tmp_path / "board.json"
    path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "key": "k",
                        "value": "v",
                        "writer": "grok",
                        "timestamp": "2026-08-24T00:00:00+00:00",
                        "meta": {"timestamp": "pwn", "note": "ok"},
                    }
                ]
            }
        )
    )
    dst = Blackboard(guard=lambda w, k: None)
    load_blackboard(path, dst)
    assert dst.get("k") == "v"
    assert dst.get_entry("k").meta.get("note") == "ok"
    assert "timestamp" not in dst.get_entry("k").meta


def test_entries_not_a_list_does_not_kill(tmp_path):
    path = tmp_path / "board.json"
    path.write_text(json.dumps({"entries": "nope"}))
    dst = Blackboard(guard=lambda w, k: None)
    load_blackboard(path, dst)
    assert list(dst.keys()) == []


def test_denied_writer_still_raises(tmp_path):
    src = Blackboard(guard=lambda w, k: None)
    src.commit("secret", "x", writer="claude")
    path = tmp_path / "board.json"
    save_blackboard(src, path)
    broker = PrivilegeBroker(enforce=True)
    dst = Blackboard(guard=lambda w, k: broker.require(w, Privilege.WRITE))
    with pytest.raises(HardPrivilegeError):
        load_blackboard(path, dst)
    assert "secret" not in dst
