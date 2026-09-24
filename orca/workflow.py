from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Callable, TYPE_CHECKING

from .domain import new_id
from .security import redact

if TYPE_CHECKING:
    from .control_plane import ControlPlane


@dataclass(frozen=True)
class AdvisoryStage:
    connector: str
    operation: str
    resource: str


ADVISORY_STAGES = (
    AdvisoryStage("notion", "read", "orca-operating-standards"),
    AdvisoryStage("linear", "read", "orca-work-and-acceptance"),
    AdvisoryStage("gitea", "read", "fry/orca-review"),
    AdvisoryStage("drive", "read", "cc-bridge/STATE.md"),
)


class AdvisoryWorkflow:
    """Read-only cross-system evidence workflow; it has no write operation path."""

    def run(self, control_plane: "ControlPlane",
            readers: dict[str, Callable[[str], object]]) -> dict:
        correlation_id = new_id("corr")
        results = []
        for stage in ADVISORY_STAGES:
            reader = readers.get(stage.connector)
            if reader is None:
                raise ValueError(f"missing advisory reader: {stage.connector}")
            prepared = control_plane.prepare_connector_read(
                actor="orca", connector=stage.connector,
                operation=stage.operation, resource=stage.resource)
            value = redact(reader(stage.resource))
            encoded = json.dumps(value, sort_keys=True, default=str).encode()
            results.append({
                "connector": stage.connector, "request_id": prepared["id"],
                "resource": stage.resource, "result_digest": sha256(encoded).hexdigest(),
                "status": "read_verified",
            })
        control_plane.record_advisory_read_completion(
            correlation_id=correlation_id, results=results,
        )
        return {"correlation_id": correlation_id, "write_count": 0, "results": results}
