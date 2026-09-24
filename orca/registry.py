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


# Inventory facts only. Runtime health starts unproven until a verified probe exists.
NODES = {
    "anvil": FleetNode("anvil", "ANVIL", "forge", "workstation",
                       "operator console, development and review", "tailnet node"),
    "forge": FleetNode("forge", "FORGE", "forge", "server",
                       "primary infrastructure and Gitea", "192.168.7.30", "R2"),
    "kiln": FleetNode("kiln", "KILN", "forge", "worker",
                      "inference and supporting services", "100.97.193.39", "R2"),
    "ember": FleetNode("ember", "EMBER", "forge", "sre-backup",
                       "backup, monitoring and UPS/NUT", "LAN / tailnet", "R2"),
    "iris": FleetNode("iris", "IRIS", "bgm", "edge-ai",
                      "MQTT, logging, calibration, inference and dashboards",
                      "BGM LAN / cellular path", "R3"),
}


LANES = {"forge", "bgm", "inventory", "cloudflare", "aws", "pccg", "orca"}
