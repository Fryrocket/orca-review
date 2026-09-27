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
    "build_ci": WorkloadPlacement(
        "build_ci", ("build_ci",), ("forge",),
        "centralize repeatable builds and CI on FORGE's 16-core CPU and durable storage",
    ),
    "durable_storage": WorkloadPlacement(
        "durable_storage", ("durable_storage",), ("forge",),
        "use FORGE's dedicated model and data volumes",
    ),
    "model_storage": WorkloadPlacement(
        "model_storage", ("model_storage",), ("forge",),
        "keep canonical model artifacts on FORGE's dedicated 3.7 TiB model volume",
    ),
    "document_ingest": WorkloadPlacement(
        "document_ingest", ("document_ingest",), ("forge",),
        "use FORGE for ingestion, parsing, indexing and shared-context preparation",
    ),
    "fast_interactive_inference": WorkloadPlacement(
        "fast_interactive_inference", ("fast_local_inference",), ("anvil",),
        "use ANVIL's installed 3B local model for low-latency operator assistance",
    ),
    "small_inference": WorkloadPlacement(
        "small_inference", ("small_inference",), ("kiln",),
        "reserve KILN's dedicated 6 GiB GTX 1660 Ti for bounded GPU inference",
    ),
    "embeddings": WorkloadPlacement(
        "embeddings", ("embeddings",), ("forge",),
        "run retrieval and embeddings on FORGE so KILN's nearly full GPU remains isolated for review",
    ),
    "local_review": WorkloadPlacement(
        "local_review", ("local_review",), ("kiln",),
        "use KILN for dedicated QUENCH review workloads",
    ),
    "large_inference": WorkloadPlacement(
        "large_inference", ("large_cpu_inference",), ("forge",),
        "run the existing 30.5B Q4 SMITH model CPU-resident on FORGE's 32 threads and 62 GiB RAM",
    ),
    "large_gpu_inference": WorkloadPlacement(
        "large_gpu_inference", ("large_gpu_inference",), ("forge",),
        "CRUCIBLE hardware and ROCm are accepted; blocked until a model-serving runtime, reboot repeat, and independent review pass",
    ),
    "monitoring": WorkloadPlacement(
        "monitoring", ("monitoring",), ("ember",),
        "keep continuous fleet, UPS and watchdog observation on low-power always-on EMBER",
    ),
    "ups_watch": WorkloadPlacement(
        "ups_watch", ("ups_watch",), ("ember",),
        "use EMBER's directly attached CyberPower UPS interface",
    ),
    "backup_observer": WorkloadPlacement(
        "backup_observer", ("backup_observer",), ("ember",),
        "use EMBER for independent backup observation without making it an authoritative writer",
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
