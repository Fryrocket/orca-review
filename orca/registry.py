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
    cpu_cores: int | None = None
    cpu_threads: int | None = None
    architecture: str = "unverified"
    memory_gib: int | None = None
    gpu: str = "unverified"
    gpu_vram_gib: int | None = None
    planned_gpu: str | None = None
    planned_gpu_name: str | None = None
    storage_gib: int | None = None
    wired_network_mbps: int | None = None
    capabilities: tuple[str, ...] = ()


# Inventory facts only. Runtime health starts unproven until a verified probe exists.
LEGACY_NODE_IDS = {"iris": "temper"}


NODES = {
    "anvil": FleetNode("anvil", "ANVIL", "forge", "workstation",
                       "operator console, development and review", "192.168.4.20 (local workstation)",
                       cpu="Apple M4 (10 cores)", cpu_cores=10, cpu_threads=10,
                       architecture="arm64", memory_gib=16,
                       gpu="Apple M4 integrated GPU (10 cores, shared memory)",
                       storage_gib=466,
                       capabilities=("operator_interactive", "development",
                                     "interactive_review", "fast_local_inference",
                                     "media_acceleration", "local_arm64")),
    "forge": FleetNode("forge", "FORGE", "forge", "server",
                       "authoritative control plane, shared memory, storage, deep CPU inference and primary infrastructure",
                       "192.168.7.30", "R2",
                       cpu="AMD Ryzen 9 5900XT", cpu_cores=16, cpu_threads=32,
                       architecture="x86_64", memory_gib=62,
                       gpu="CRUCIBLE — AMD Radeon AI PRO R9700 32 GiB; AMD Lexa Pro display adapter 4 GiB",
                       gpu_vram_gib=32,
                       storage_gib=10_350,
                       wired_network_mbps=2_500,
                       capabilities=("control_plane", "cpu_batch", "durable_storage",
                                     "model_storage", "data_storage", "network_2_5gbe",
                                     "shared_context", "build_ci", "document_ingest",
                                     "cpu_inference", "large_cpu_inference",
                                     "embeddings", "monitoring_fallback",
                                     "gpu_compute_rocm")),
    "kiln": FleetNode("kiln", "KILN", "forge", "worker",
                      "independent GPU review, verification and supporting services",
                      "100.97.193.39", "R2",
                      cpu="AMD Ryzen 5 4600G", cpu_cores=6, cpu_threads=12,
                      architecture="x86_64", memory_gib=31,
                      gpu="BILLOWS — NVIDIA GeForce GTX 1660 Ti", gpu_vram_gib=6,
                      storage_gib=466,
                      wired_network_mbps=1_000,
                      capabilities=("small_inference", "gpu_inference", "local_review",
                                    "independent_review", "relay", "local_x86_64")),
    "ember": FleetNode("ember", "EMBER", "forge", "sre-backup",
                       "always-on backup observer, monitoring, UPS/NUT and watchdog",
                       "192.168.4.26 / 100.87.165.66", "R2",
                       cpu="Broadcom BCM2711 / Cortex-A72", cpu_cores=4,
                       cpu_threads=4, architecture="arm64", memory_gib=8,
                       gpu="VideoCore VI integrated GPU (shared memory)",
                       storage_gib=477, wired_network_mbps=1_000,
                       capabilities=("monitoring", "ups_watch", "watchdog",
                                     "backup_observer", "wake_signals", "local_arm64")),
    "temper": FleetNode("temper", "TEMPER", "bgm", "edge-ai",
                        "MQTT, logging, calibration, Hailo inference and dashboards",
                        "192.168.4.25 primary / 192.168.4.27 wired fallback", "R3",
                        cpu="Broadcom BCM2712 quad-core Arm Cortex-A76",
                        cpu_cores=4, cpu_threads=4, architecture="arm64",
                        memory_gib=16,
                        gpu="Hailo-8 edge AI accelerator (26 TOPS INT8)",
                        storage_gib=1_000, wired_network_mbps=1_000,
                        capabilities=("mqtt", "sensor_ingest", "signal_processing",
                                      "calibration", "edge_inference",
                                      "offline_queue", "dashboards", "local_arm64")),
}


LANES = {"forge", "bgm", "inventory", "cloudflare", "aws", "pccg", "orca"}
