"""R11-F15/F64/F68/F69 ("blackboard").

Blackboard.commit() always constructed BoardEntry with no explicit
timestamp, so BoardEntry's field default_factory (datetime.now()) fired
every time — including during persist.py's load_blackboard() replay.
save_blackboard() faithfully serializes each entry's real commit
timestamp to disk, but load_blackboard()'s replay had no way to pass it
back through commit(), so every reloaded entry silently got "now" instead
of its true original commit time. A saved blackboard's history lost
timestamp fidelity on every reload.

commit() now accepts an optional timestamp= (defaults to "now" exactly as
before for every live caller); load_blackboard() passes the saved
timestamp through."""

import tempfile
import time
from pathlib import Path

from mao.blackboard import Blackboard
from mao.persist import load_blackboard, save_blackboard


def _board():
    return Blackboard(guard=lambda writer, key: None)


def test_commit_defaults_to_now_when_no_timestamp_given():
    """Normal live commits must be completely unaffected by this fix."""
    b = _board()
    entry = b.commit("k", "v", writer="grok")
    assert entry.timestamp  # non-empty, real timestamp
    assert entry.timestamp == b.get_entry("k").timestamp


def test_commit_preserves_explicit_timestamp_when_given():
    b = _board()
    entry = b.commit("k", "v", writer="grok", timestamp="2020-01-01T00:00:00+00:00")
    assert entry.timestamp == "2020-01-01T00:00:00+00:00"


def test_save_load_roundtrip_preserves_original_timestamp(tmp_path):
    """The exact F15/F64/F68/F69 bug: this used to change on reload."""
    board = _board()
    board.commit("k1", "v1", writer="grok")
    original_timestamp = board.get_entry("k1").timestamp

    time.sleep(1.1)  # ensure a reload's "now" would visibly differ

    path = tmp_path / "board.json"
    save_blackboard(board, path)

    restored = _board()
    load_blackboard(path, restored)
    assert restored.get_entry("k1").timestamp == original_timestamp


def test_save_load_roundtrip_preserves_timestamps_across_multiple_entries(tmp_path):
    board = _board()
    board.commit("a", 1, writer="grok")
    time.sleep(0.05)
    board.commit("b", 2, writer="grok")
    time.sleep(0.05)
    board.commit("a", 3, writer="grok")  # second commit to same key
    original_history = [(e.key, e.timestamp) for e in board.history()]

    path = tmp_path / "board.json"
    save_blackboard(board, path)

    restored = _board()
    load_blackboard(path, restored)
    restored_history = [(e.key, e.timestamp) for e in restored.history()]
    assert restored_history == original_history


def test_load_blackboard_with_missing_timestamp_key_falls_back_to_now(tmp_path):
    """Backward compat: old saved files without a timestamp field must not
    crash — they should just get a fresh timestamp like before this fix."""
    import json

    path = tmp_path / "board.json"
    path.write_text(json.dumps({"entries": [
        {"key": "k", "value": "v", "writer": "grok", "meta": {}}
    ]}))
    restored = _board()
    load_blackboard(path, restored)
    assert restored.get_entry("k").timestamp  # non-empty, didn't crash
