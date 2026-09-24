from __future__ import annotations

from dataclasses import dataclass

from .domain import AgentIdentity


AGENTS = {
    "orca": AgentIdentity("orca", "ORCA", "policy, routing, approvals, lane isolation"),
    "smith": AgentIdentity("smith", "SMITH", "coding and implementation", may_author=True),
    "quench": AgentIdentity("quench", "QUENCH", "independent technical review", may_review=True),
    "security_gate": AgentIdentity("security_gate", "Independent Security Gate",
                                   "advisory security findings and escalation only"),
    "fry": AgentIdentity("fry", "Fry", "human owner and approval authority", may_review=True, may_deploy=True),
}


@dataclass(frozen=True)
class Connector:
    id: str
    name: str
    authority: str
    writes_enabled: bool = False


CONNECTORS = {
    "notion": Connector("notion", "Notion", "durable knowledge and decisions"),
    "linear": Connector("linear", "Linear", "work, owners, dependencies, acceptance"),
    "github": Connector("github", "GitHub", "public code and review history"),
    "gitea": Connector("gitea", "Forge Gitea", "primary code/configuration history"),
    "slack": Connector("slack", "Slack", "urgent alerts, coordination, approvals"),
    "drive": Connector("drive", "Google Drive", "artifacts, reports, handoffs, recovery material"),
    "cloudflare": Connector("cloudflare", "Cloudflare", "edge inventory/control; approved actions only"),
}


@dataclass(frozen=True)
class FleetNode:
    id: str
    name: str
    lane: str
    kind: str
    duty: str
    address: str
    permission_floor: str = "R0"
    remote_execution_enabled: bool = False
    cpu: str = "unverified"
    cpu_threads: int | None = None
    memory_gib: int | None = None
    gpu: str = "unverified"
    gpu_vram_gib: int | None = None
    storage_gib: int | None = None
    capabilities: tuple[str, ...] = ()


# Inventory facts only. Runtime health starts unproven until a verified probe exists.
NODES = {
    "anvil": FleetNode("anvil", "ANVIL", "forge", "workstation",
                       "operator console, development and review", "local workstation",
                       cpu="Apple M4 (10 cores)", cpu_threads=10, memory_gib=16,
                       gpu="Apple M4 integrated GPU (10 cores)", storage_gib=460,
                       capabilities=("operator_interactive", "development",
                                     "interactive_review", "local_arm64")),
    "forge": FleetNode("forge", "FORGE", "forge", "server",
                       "authoritative control plane, storage and primary infrastructure",
                       "192.168.7.30", "R2",
                       cpu="AMD Ryzen 9 5900XT", cpu_threads=32, memory_gib=62,
                       gpu="Radeon 550-class display adapter; RX9700 pending",
                       storage_gib=10_350,
                       capabilities=("control_plane", "cpu_batch", "durable_storage",
                                     "model_storage", "data_storage", "network_2_5gbe")),
    "kiln": FleetNode("kiln", "KILN", "forge", "worker",
                      "secondary inference, review and supporting services",
                      "100.97.193.39", "R2",
                      cpu="AMD Ryzen 5 4600G", cpu_threads=12, memory_gib=31,
                      gpu="NVIDIA GeForce GTX 1660 Ti", gpu_vram_gib=6,
                      storage_gib=466,
                      capabilities=("small_inference", "embeddings", "local_review",
                                    "relay", "local_x86_64")),
    "ember": FleetNode("ember", "EMBER", "forge", "sre-backup",
                       "backup, monitoring and UPS/NUT", "LAN / tailnet", "R2"),
    "iris": FleetNode("iris", "IRIS", "bgm", "edge-ai",
                      "MQTT, logging, calibration, inference and dashboards",
                      "BGM LAN / cellular path", "R3"),
}


LANES = {"forge", "bgm", "inventory", "cloudflare", "aws", "pccg", "orca"}
