from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping

from .registry import NODES


@dataclass(frozen=True)
class WorkloadPlacement:
    id: str
    required_capabilities: tuple[str, ...]
    candidates: tuple[str, ...]
    reason: str


WORKLOAD_PLACEMENTS = {
    "operator_interactive": WorkloadPlacement(
        "operator_interactive", ("operator_interactive",), ("anvil",),
        "keep interactive control and human review on the operator worktop",
    ),
    "development": WorkloadPlacement(
        "development", ("development",), ("anvil",),
        "keep source editing and local verification on ANVIL",
    ),
    "control_plane": WorkloadPlacement(
        "control_plane", ("control_plane",), ("forge",),
        "keep one authoritative writer on FORGE",
    ),
    "cpu_batch": WorkloadPlacement(
        "cpu_batch", ("cpu_batch",), ("forge",),
        "use FORGE's 32 CPU threads and 62 GiB memory",
    ),
    "durable_storage": WorkloadPlacement(
        "durable_storage", ("durable_storage",), ("forge",),
        "use FORGE's dedicated model and data volumes",
    ),
    "small_inference": WorkloadPlacement(
        "small_inference", ("small_inference",), ("kiln",),
        "use KILN's dedicated 6 GiB GTX 1660 Ti services",
    ),
    "embeddings": WorkloadPlacement(
        "embeddings", ("embeddings",), ("kiln",),
        "keep lightweight inference on KILN",
    ),
    "local_review": WorkloadPlacement(
        "local_review", ("local_review",), ("kiln",),
        "use KILN for dedicated QUENCH review workloads",
    ),
    "large_inference": WorkloadPlacement(
        "large_inference", ("large_inference",), ("forge",),
        "blocked until FORGE's RX9700 is installed and runtime-accepted",
    ),
}


def recommend_placement(
    workload: str,
    node_health: Mapping[str, Mapping[str, object]] | None = None,
) -> dict:
    if workload not in WORKLOAD_PLACEMENTS:
        raise ValueError(f"unknown workload placement: {workload}")
    placement = WORKLOAD_PLACEMENTS[workload]
    evaluations = []
    selected = None
    for node_id in placement.candidates:
        node = NODES[node_id]
        missing = sorted(set(placement.required_capabilities) - set(node.capabilities))
        health = "unobserved" if node_health is None else str(
            node_health.get(node_id, {}).get("state", "unproven"))
        eligible = not missing and (node_health is None or health == "healthy")
        evaluations.append({
            "node_id": node_id,
            "eligible": eligible,
            "health": health,
            "missing_capabilities": missing,
        })
        if selected is None and eligible:
            selected = node_id
    return {
        "workload": workload,
        "selected_node": selected,
        "status": "recommended" if selected is not None else "blocked",
        "reason": placement.reason,
        "required_capabilities": list(placement.required_capabilities),
        "candidates": evaluations,
        "remote_execution_enabled": False,
    }


def placement_snapshot(
    node_health: Mapping[str, Mapping[str, object]] | None = None,
) -> dict:
    return {
        "profiles": {node_id: asdict(node) for node_id, node in NODES.items()},
        "workloads": {
            workload: recommend_placement(workload, node_health)
            for workload in WORKLOAD_PLACEMENTS
        },
        "automatic_execution": False,
    }
