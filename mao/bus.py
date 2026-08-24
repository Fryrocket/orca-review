"""Message bus for inter-agent communication (Round-7 + R11).

Push-based. Fatal errors from subscribers are re-raised (E4).
Handlers are snapshotted under the lock and dispatched outside it (R11-F12).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
import threading
import uuid

from .errors import OrcaError


# Exceptions that must never be swallowed by bus dispatch (E4).
FATAL_ERRORS = (
    SystemExit,
    KeyboardInterrupt,
    GeneratorExit,
    MemoryError,
    OrcaError,  # includes HardPrivilegeError, CostCapExceeded, etc.
)


@dataclass
class Message:
    sender: str
    content: Any
    topic: str = "default"
    run_id: str = ""
    msg_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "msg_id": self.msg_id,
            "sender": self.sender,
            "topic": self.topic,
            "run_id": self.run_id,
            "content": self.content,
            "timestamp": self.timestamp,
            "meta": self.meta,
        }


class MessageBus:
    """Simple in-process pub/sub with history and fatal-error propagation."""

    def __init__(self):
        self._subs: Dict[str, List[Callable[[Message], None]]] = {}
        self._history: List[Message] = []
        self._lock = threading.RLock()
        self._closed = False

    def subscribe(self, topic: str, handler: Callable[[Message], None]) -> None:
        with self._lock:
            self._subs.setdefault(topic, []).append(handler)

    def publish(
        self,
        sender: str,
        content: Any,
        topic: str = "default",
        *,
        run_id: str = "",
        **meta,
    ) -> Message:
        if self._closed:
            raise OrcaError("MessageBus is closed")
        msg = Message(
            sender=sender,
            content=content,
            topic=topic,
            run_id=run_id,
            meta=dict(meta),
        )
        # Snapshot under lock; dispatch outside (R11-F12)
        with self._lock:
            self._history.append(msg)
            handlers = list(self._subs.get(topic, [])) + list(self._subs.get("*", []))
        for h in handlers:
            try:
                h(msg)
            except FATAL_ERRORS:
                raise
            except Exception:
                # Non-fatal subscriber errors are not logged here.
                # Orchestrator may observe via its own handlers if desired.
                pass
        return msg

    def history(
        self,
        topic: Optional[str] = None,
        run_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Message]:
        with self._lock:
            items = self._history
            if topic is not None:
                items = [m for m in items if m.topic == topic]
            if run_id is not None:
                items = [m for m in items if m.run_id == run_id]
            if limit is not None:
                # R11-F13/F65/F66: items[-limit:] with limit=0 is items[-0:]
                # which is the whole list. Negative limits get the same empty.
                items = items[-limit:] if limit > 0 else []
            return list(items)

    def close(self) -> None:
        with self._lock:
            self._closed = True

    def __len__(self) -> int:
        with self._lock:
            return len(self._history)
