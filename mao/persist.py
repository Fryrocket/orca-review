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
from .errors import OrcaConfigError


def save_blackboard(bb: Blackboard, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
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
    path.write_text(json.dumps(data, indent=2, default=str))


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
    data = json.loads(path.read_text())
    for item in data.get("entries", []):
        writer = item.get("writer") or item.get("author") or "system"
        meta = dict(item.get("meta") or {})
        board.commit(
            item["key"], item["value"], writer=writer,
            timestamp=item.get("timestamp"), **meta,
        )
    return board


def save_bus(bus: MessageBus, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"messages": [m.to_dict() for m in bus.history()]}
    path.write_text(json.dumps(data, indent=2, default=str))


def load_bus_log(path: str | Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return data.get("messages", [])
