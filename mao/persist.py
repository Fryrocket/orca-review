"""Persistence for blackboard and message bus."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .memory import Blackboard, MemoryEntry
from .bus import MessageBus, Message


def save_blackboard(bb: Blackboard, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "entries": [
            {
                "key": e.key,
                "value": e.value,
                "author": e.author,
                "timestamp": e.timestamp,
                "meta": e.meta,
            }
            for e in bb.history()
        ]
    }
    path.write_text(json.dumps(data, indent=2, default=str))


def load_blackboard(path: str | Path) -> Blackboard:
    path = Path(path)
    bb = Blackboard()
    if not path.exists():
        return bb
    data = json.loads(path.read_text())
    for item in data.get("entries", []):
        bb.set(
            key=item["key"],
            value=item["value"],
            author=item.get("author", "system"),
            **item.get("meta", {}),
        )
    return bb


def save_bus(bus: MessageBus, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "messages": [
            {
                "id": m.msg_id if hasattr(m, "msg_id") else getattr(m, "id", ""),
                "topic": m.topic,
                "sender": m.sender,
                "content": m.content,
                "timestamp": m.timestamp,
                "meta": m.meta,
            }
            for m in bus.history()
        ]
    }
    path.write_text(json.dumps(data, indent=2, default=str))


def load_bus_log(path: str | Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return data.get("messages", [])
