"""Privilege-aware Blackboard (Round-7 rewrite).

Writes are gated by an explicit guard callable before any mutation.
Fail-closed construction: guard is required.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
import threading

from .errors import OrcaConfigError


@dataclass(frozen=True)
class BoardEntry:
    key: str
    value: Any
    writer: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    meta: dict = field(default_factory=dict)


class Blackboard:
    """Thread-safe key-value store with privilege-gated commits and history."""

    def __init__(self, guard: Optional[Callable[[str, str], None]] = None):
        if guard is None:
            raise OrcaConfigError(
                "Blackboard requires an explicit guard (writer, key) -> None. "
                "Pass a lambda that calls PrivilegeBroker.require or equivalent."
            )
        self._guard = guard
        self._data: Dict[str, BoardEntry] = {}
        self._history: List[BoardEntry] = []
        self._lock = threading.RLock()

    def commit(
        self,
        key: str,
        value: Any,
        *,
        writer: str,
        timestamp: Optional[str] = None,
        **meta,
    ) -> BoardEntry:
        """Guard first, then mutate. Denied writes leave the board untouched.

        R11-F15/F64/F68/F69: timestamp= lets persist.py's load_blackboard
        replay preserve original commit times instead of stamping "now".
        """
        if not key or not isinstance(key, str):
            raise OrcaConfigError("blackboard key must be a non-empty string")
        # Guard *before* any mutation (ordering required by tests).
        self._guard(writer, key)
        kwargs = {"key": key, "value": value, "writer": writer, "meta": dict(meta)}
        if timestamp is not None:
            kwargs["timestamp"] = timestamp
        entry = BoardEntry(**kwargs)
        with self._lock:
            self._data[key] = entry
            self._history.append(entry)
        return entry

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            entry = self._data.get(key)
            return entry.value if entry is not None else default

    def get_entry(self, key: str) -> Optional[BoardEntry]:
        with self._lock:
            return self._data.get(key)

    def history(self, key: Optional[str] = None) -> Tuple[BoardEntry, ...]:
        with self._lock:
            if key is None:
                return tuple(self._history)
            return tuple(e for e in self._history if e.key == key)

    def keys(self) -> List[str]:
        with self._lock:
            return list(self._data.keys())

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def __contains__(self, key: str) -> bool:
        with self._lock:
            return key in self._data

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {k: e.value for k, e in self._data.items()}
