from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping

from .crucible import evaluate_crucible_acceptance
from .registry import NODES


@dataclass(frozen=True)
class AIServiceProfile:
    """One bounded cognitive service in the four-host ORCA fabric.

    ``runtime_enabled`` describes ORCA invocation authority, not whether an
    independently managed process is already listening on the host.
    """

    id: str
    node_id: str | None
    duty: str
    model: str
    backend: str
    accelerator: str
    context_tokens: int
    max_parallel: int
    ram_budget_gib: int
    vram_budget_gib: int = 0
    deployment_state: str = "planned"
    runtime_enabled: bool = False
    may_author: bool = False
    may_review: bool = False


AI_SERVICES = {
    "forge_policy": AIServiceProfile(
        "forge_policy", "forge",
        "authoritative routing, evidence, policy, shared context and memory",
        "deterministic ORCA control plane", "python", "cpu",
        0, 1, 4, deployment_state="live",
    ),
    "anvil_reflex": AIServiceProfile(
        "anvil_reflex", "anvil",
        "fast private operator triage, summarization and prompt preparation",
        "llama3.2:3b", "ollama", "Apple Metal / unified memory",
        8_192, 1, 4, deployment_state="installed",
    ),
    "forge_smith": AIServiceProfile(
        "forge_smith", "forge",
        "deep coding, synthesis, planning and general-purpose local reasoning",
        "Qwen3-Coder-30B-A3B-Instruct-Q4_K_M", "llama.cpp", "CPU / AVX2",
        16_384, 1, 28, deployment_state="planned_migration", may_author=True,
    ),
    "forge_deepseek": AIServiceProfile(
        "forge_deepseek", "forge",
        "architecture, difficult debugging, mathematics, planning and second-opinion reasoning",
        "DeepSeek-R1-Distill-Qwen-32B-Q4_K_M", "llama.cpp", "CRUCIBLE / AMD ROCm",
        16_384, 1, 12, vram_budget_gib=24,
        deployment_state="pending_model_runtime",
    ),
    "forge_embeddings": AIServiceProfile(
        "forge_embeddings", "forge",
        "document ingestion, embeddings, retrieval and reranking",
        "embedding model pending acceptance", "llama.cpp", "CPU / AVX2",
        8_192, 4, 6, deployment_state="planned",
    ),
    "kiln_quench": AIServiceProfile(
        "kiln_quench", "kiln",
        "independent technical review, verification and adversarial challenge",
        "Ministral-3-8B-Instruct-2512-IQ4_XS", "llama.cpp", "CUDA",
        4_096, 1, 2, vram_budget_gib=5,
        deployment_state="live_external", may_review=True,
    ),
    "ember_sentinel": AIServiceProfile(
        "ember_sentinel", "ember",
        "always-on health, UPS, watchdog, backup observation and wake signals",
        "deterministic rules only", "python", "cpu",
        0, 1, 2, deployment_state="planned",
    ),
    "forge_crucible": AIServiceProfile(
        "forge_crucible", "forge",
        "gated CRUCIBLE runtime supervisor and acceptance surface",
        "pinned llama.cpp HIP runtime pending acceptance", "llama.cpp", "CRUCIBLE / AMD ROCm 7.2.1",
        0, 1, 0, deployment_state="pending_model_runtime",
    ),
}


# Ordered from cheapest/fastest sufficient local step to deeper or independent
# processing. These are advisory routes; ORCA model invocation remains disabled.
AI_LADDERS = {
    "orchestration": ("forge_policy",),
    "interactive": ("anvil_reflex", "forge_deepseek", "forge_smith", "fry"),
    "coding": ("forge_deepseek", "forge_smith", "kiln_quench", "fry"),
    "documentation": ("anvil_reflex", "forge_deepseek", "forge_smith", "kiln_quench", "fry"),
    "operations_plan": ("forge_deepseek", "forge_smith", "kiln_quench", "fry"),
    "review": ("kiln_quench", "fry"),
    "security_review": ("kiln_quench", "fry"),
    "verification": ("kiln_quench", "fry"),
    "embeddings": ("forge_embeddings",),
    "monitoring": ("ember_sentinel", "forge_policy", "fry"),
    "large_inference": ("forge_smith", "fry"),
    "large_gpu_inference": ("forge_deepseek", "forge_crucible", "fry"),
}


COGNITIVE_FABRIC = {
    "identity": "one ORCA mind with specialized execution surfaces",
    "authoritative_writer": "forge",
    "shared_memory_owner": "forge",
    "operator_surface": "anvil",
    "independent_review_surface": "kiln",
    "sentinel_surface": "ember",
    "memory_pooling": False,
    "automatic_execution": False,
    "cloud_fallback": False,
}


def ladder_snapshot(
    node_health: Mapping[str, Mapping[str, object]] | None = None,
) -> dict:
    services = {}
    for service_id, service in AI_SERVICES.items():
        row = asdict(service)
        if service.node_id is None:
            row["node_health"] = "not_applicable"
        elif node_health is None:
            row["node_health"] = "unobserved"
        else:
            row["node_health"] = str(
                node_health.get(service.node_id, {}).get("state", "unproven"))
        row["hardware"] = (
            asdict(NODES[service.node_id]) if service.node_id is not None else None)
        services[service_id] = row

    ladders = {}
    for job_type, steps in AI_LADDERS.items():
        rows = []
        for order, service_id in enumerate(steps, start=1):
            if service_id == "fry":
                rows.append({
                    "order": order,
                    "service_id": "fry",
                    "node_id": None,
                    "state": "human_gate",
                    "runtime_enabled": True,
                })
                continue
            service = AI_SERVICES[service_id]
            health = services[service_id]["node_health"]
            rows.append({
                "order": order,
                "service_id": service_id,
                "node_id": service.node_id,
                "state": service.deployment_state,
                "node_health": health,
                "runtime_enabled": service.runtime_enabled,
            })
        ladders[job_type] = rows

    return {
        "fabric": dict(COGNITIVE_FABRIC),
        "services": services,
        "ladders": ladders,
        "crucible_acceptance": evaluate_crucible_acceptance(),
        "model_invocation_enabled": False,
    }


def validate_ai_stack() -> None:
    ram_by_node: dict[str, int] = {}
    vram_by_node: dict[str, int] = {}
    for service in AI_SERVICES.values():
        if service.node_id is not None and service.node_id not in NODES:
            raise ValueError(f"AI service references unknown node: {service.id}")
        if service.context_tokens < 0 or service.max_parallel < 1:
            raise ValueError(f"AI service has invalid limits: {service.id}")
        if service.ram_budget_gib < 0 or service.vram_budget_gib < 0:
            raise ValueError(f"AI service has invalid memory budget: {service.id}")
        if service.node_id is not None:
            node = NODES[service.node_id]
            if service.deployment_state != "blocked_hardware":
                ram_by_node[service.node_id] = (
                    ram_by_node.get(service.node_id, 0) + service.ram_budget_gib)
                vram_by_node[service.node_id] = (
                    vram_by_node.get(service.node_id, 0) + service.vram_budget_gib)
            if node.memory_gib is not None and service.ram_budget_gib > node.memory_gib:
                raise ValueError(f"AI service exceeds node RAM: {service.id}")
            if (service.vram_budget_gib and node.gpu_vram_gib is not None
                    and service.vram_budget_gib > node.gpu_vram_gib):
                raise ValueError(f"AI service exceeds node VRAM: {service.id}")
    for node_id, ram_budget_gib in ram_by_node.items():
        node = NODES[node_id]
        if node.memory_gib is not None and ram_budget_gib > node.memory_gib:
            raise ValueError(f"AI services overcommit node RAM: {node_id}")
    for node_id, vram_budget_gib in vram_by_node.items():
        node = NODES[node_id]
        if node.gpu_vram_gib is not None and vram_budget_gib > node.gpu_vram_gib:
            raise ValueError(f"AI services overcommit node VRAM: {node_id}")
    for job_type, ladder in AI_LADDERS.items():
        if not ladder:
            raise ValueError(f"AI ladder is empty: {job_type}")
        unknown = [step for step in ladder if step != "fry" and step not in AI_SERVICES]
        if unknown:
            raise ValueError(f"AI ladder references unknown services: {job_type}")
    if AI_SERVICES["forge_smith"].node_id == AI_SERVICES["kiln_quench"].node_id:
        raise ValueError("author and independent reviewer must use different hosts")


validate_ai_stack()
