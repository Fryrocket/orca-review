"""Explicit, offline-safe maintenance ticks for the ORCA control plane.

There is intentionally no scheduler, background thread, service integration,
or transport in this module.  An operator or future reviewed scheduler must
call :meth:`MaintenanceTicker.tick` explicitly.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

from .control_plane import ControlPlane
from .registry import NODES


_REPORT_SCHEMA_VERSION = 1
_MAX_TICK_EPOCH = (1 << 63) - 1
_EXPIRY_STATES = frozenset({"unproven", "degraded", "offline"})


@dataclass(frozen=True)
class NodeExpiry:
    """One bounded node-state transition produced by a maintenance tick."""

    node_id: str
    state: str

    def to_dict(self) -> dict[str, str]:
        return {"node_id": self.node_id, "state": self.state}


@dataclass(frozen=True)
class MaintenanceReport:
    """Deterministic result of one explicit maintenance tick."""

    tick_epoch: int
    degraded_after: int
    offline_after: int
    evaluated_nodes: int
    changes: tuple[NodeExpiry, ...]
    state_revision: int
    schema_version: int = _REPORT_SCHEMA_VERSION

    @property
    def changed(self) -> bool:
        return bool(self.changes)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "tick_epoch": self.tick_epoch,
            "degraded_after": self.degraded_after,
            "offline_after": self.offline_after,
            "evaluated_nodes": self.evaluated_nodes,
            "changed": self.changed,
            "changed_count": len(self.changes),
            "changes": [change.to_dict() for change in self.changes],
            "state_revision": self.state_revision,
        }


class MaintenanceTicker:
    """Run bounded control-plane upkeep only when ``tick`` is called."""

    def __init__(
        self,
        control_plane: ControlPlane,
        *,
        clock: Callable[[], int],
        degraded_after: int = 180,
        offline_after: int = 600,
    ) -> None:
        if not isinstance(control_plane, ControlPlane):
            raise TypeError("maintenance requires a ControlPlane")
        if not callable(clock):
            raise TypeError("maintenance clock must be callable")
        if (type(degraded_after) is not int
                or type(offline_after) is not int
                or degraded_after <= 0
                or offline_after <= degraded_after):
            raise ValueError("maintenance thresholds must be positive and ordered")

        self._control_plane = control_plane
        self._clock = clock
        self.degraded_after = degraded_after
        self.offline_after = offline_after
        self._last_tick_epoch: int | None = None
        self._lock = Lock()

    @property
    def last_tick_epoch(self) -> int | None:
        return self._last_tick_epoch

    def _durable_epoch_floor(self) -> int | None:
        """Infer the earliest safe time from durable heartbeat/health state.

        The exact prior tick is intentionally not a separate scheduler record.
        A degraded/offline state marked by the expiry reducer nevertheless
        proves that receiver time crossed its corresponding threshold. Reusing
        an earlier clock after restart therefore fails closed instead of making
        health look newer.
        """

        floor: int | None = None
        for node_id, enrollment in self._control_plane.node_enrollments.items():
            if node_id not in NODES or not isinstance(enrollment, dict):
                raise RuntimeError("fleet enrollment is invalid")
            last_seen = enrollment.get("last_seen_epoch")
            if last_seen is None:
                continue
            if type(last_seen) is not int or last_seen < 0:
                raise RuntimeError("fleet enrollment contains an invalid acceptance time")
            health = self._control_plane.node_health[node_id]
            state = health["state"]
            expired = health.get("detail") == "authenticated heartbeat stale"
            if state == "offline" and expired:
                candidate = last_seen + self.offline_after
            elif state == "degraded" and expired:
                candidate = last_seen + self.degraded_after
            elif state in {"healthy", "degraded", "offline", "unproven"}:
                candidate = last_seen
            else:
                raise RuntimeError("fleet health contains an invalid state")
            floor = candidate if floor is None else max(floor, candidate)
        return floor

    def tick(self) -> MaintenanceReport:
        """Evaluate heartbeat staleness once and return a bounded report.

        Repeating a tick at the same time is idempotent: the control plane's
        existing expiry reducer emits no duplicate transition, evidence event,
        or state revision for nodes already at their target stale state.
        """

        with self._lock:
            tick_epoch = self._clock()
            if (type(tick_epoch) is not int
                    or tick_epoch < 0
                    or tick_epoch > _MAX_TICK_EPOCH):
                raise ValueError(
                    "maintenance clock must return a bounded non-negative integer")
            # Keep expiry and every field copied into the report under the same
            # reentrant control-plane lock.  This prevents a concurrent heartbeat
            # or operator mutation from producing a report that mixes revisions.
            with self._control_plane._mutation_lock:
                durable_floor = self._durable_epoch_floor()
                floors = [value for value in (
                    self._last_tick_epoch, durable_floor) if value is not None]
                if floors and tick_epoch < max(floors):
                    raise ValueError("maintenance clock moved backwards")
                changed_nodes = self._control_plane.expire_stale_nodes(
                    now=tick_epoch,
                    degraded_after=self.degraded_after,
                    offline_after=self.offline_after,
                )
                if (not isinstance(changed_nodes, list)
                        or len(changed_nodes) > len(NODES)
                        or len(changed_nodes) != len(set(changed_nodes))
                        or any(node_id not in NODES for node_id in changed_nodes)):
                    raise RuntimeError("stale-node expiry returned an invalid result")

                changes = []
                for node_id in sorted(changed_nodes):
                    state = self._control_plane.node_health[node_id]["state"]
                    if state not in _EXPIRY_STATES:
                        raise RuntimeError("stale-node expiry returned an invalid state")
                    changes.append(NodeExpiry(node_id=node_id, state=state))

                evaluated_nodes = len(self._control_plane.node_enrollments)
                if not 0 <= evaluated_nodes <= len(NODES):
                    raise RuntimeError("fleet enrollment count exceeds the node registry")
                state_revision = self._control_plane.state_revision

            self._last_tick_epoch = tick_epoch
            return MaintenanceReport(
                tick_epoch=tick_epoch,
                degraded_after=self.degraded_after,
                offline_after=self.offline_after,
                evaluated_nodes=evaluated_nodes,
                changes=tuple(changes),
                state_revision=state_revision,
            )
