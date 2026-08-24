"""Persistence for blackboard and message bus.

Uses the Round-7 guarded Blackboard (commit/writer). load_blackboard
replays into a caller-constructed board so construction cannot skip the
guard. Does not import mao.memory — that module is a legacy ungated store.
"""

from __future__ import annotations

import json
from pathlib import Path

from .blackboard import Blackboard
from .bus import MessageBus
from .errors import HardPrivilegeError, OrcaConfigError

_META_RESERVED = {"key", "value", "writer", "timestamp"}


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def save_blackboard(bb: Blackboard, path: str | Path) -> None:
    path = Path(path)
    data = {
        "entries": [
            {
                "key": e.key,
                "value": e.value,
                "writer": e.writer,
                "timestamp": e.timestamp,
                "meta": e.meta,
            }
            for e in bb.history()
        ]
    }
    _atomic_write(path, json.dumps(data, indent=2, default=str))


def load_blackboard(path: str | Path, board: Blackboard) -> Blackboard:
    """Replay saved entries into an already-constructed (guarded) board."""
    if board is None:
        raise OrcaConfigError(
            "load_blackboard requires a guarded Blackboard; refusing to "
            "construct one without a guard"
        )
    path = Path(path)
    if not path.exists():
        return board
    # R11-F78: save was a non-atomic write_text, so a crash mid-write left
    # truncated JSON. load() then raised JSONDecodeError. meta keys that
    # collide with commit() kwargs (timestamp/writer/…) TypeError'd.
    # Soft-load corrupt files; still fail-closed on HardPrivilegeError.
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return board
    if not isinstance(data, dict):
        return board
    raw = data.get("entries", [])
    if not isinstance(raw, list):
        return board
    for item in raw:
        if not isinstance(item, dict) or "key" not in item:
            continue
        writer = item.get("writer") or item.get("author") or "system"
        meta = dict(item.get("meta") or {})
        for reserved in _META_RESERVED:
            meta.pop(reserved, None)
        try:
            board.commit(
                item["key"], item.get("value"), writer=writer,
                timestamp=item.get("timestamp"), **meta,
            )
        except HardPrivilegeError:
            raise
        except (TypeError, KeyError, ValueError, OrcaConfigError):
            continue
    return board


def save_bus(bus: MessageBus, path: str | Path) -> None:
    path = Path(path)
    data = {"messages": [m.to_dict() for m in bus.history()]}
    _atomic_write(path, json.dumps(data, indent=2, default=str))


def load_bus_log(path: str | Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, dict):
        return []
    msgs = data.get("messages", [])
    return msgs if isinstance(msgs, list) else []
