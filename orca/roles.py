from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RoleDefinition:
    id: str
    name: str
    category: str
    duty: str
    owner: str
    node_id: str | None
    lanes: tuple[str, ...]
    authority: tuple[str, ...]
    prohibited: tuple[str, ...]
    receives_from: tuple[str, ...]
    hands_off_to: tuple[str, ...]
    active: bool = False
    activation_gate: str = "fry_recorded_decision"


ROLE_CATALOG = {
    "fry": RoleDefinition("fry", "Fry", "human_authority", "Own the system and decide R3 approvals, deployment, spend, publication, secrets, physical action and exceptions.", "fry", None, ("all",), ("approve_r3", "deploy", "record_exception", "stop_system"), (), ("orca", "quench", "security_gate"), ("orca",), True, "not_applicable"),
    "orca": RoleDefinition("orca", "ORCA", "governed_bot", "Classify, route and pause work; enforce policy, evidence, lane isolation and approval boundaries.", "fry", "forge", ("all",), ("route", "classify", "pause", "record_evidence"), ("impersonate_fry", "approve_r3", "author_release", "review_own_work", "deploy"), ("fry", "ember_sentinel", "heartbeat_agents"), ("anvil_reflex", "deepseek_reasoner", "smith", "security_gate", "quench", "fry"), True, "deterministic_control_plane_verified"),
    "smith": RoleDefinition("smith", "SMITH", "governed_bot", "Author scoped code, documentation, synthesis and operations plans with tests and rollback evidence.", "orca", "forge", ("all",), ("author", "propose_change", "run_bounded_evaluation"), ("self_review", "approve", "merge", "deploy", "connector_write", "unbounded_tools"), ("orca", "anvil_reflex", "deepseek_reasoner", "forge_retrieval"), ("security_gate", "quench", "orca"), False, "crucible_model_runtime_and_quench_acceptance"),
    "deepseek_reasoner": RoleDefinition("deepseek_reasoner", "DeepSeek Reasoner", "model_service", "Provide architecture, difficult-debugging, mathematical and planning analysis without author or approval identity.", "smith", "forge", ("all",), ("analyze", "challenge_assumptions", "propose_options"), ("act_as_agent", "author_change", "approve", "review_release", "use_tools", "deploy"), ("orca", "smith"), ("smith", "orca"), False, "crucible_model_runtime_and_output_contract_acceptance"),
    "quench": RoleDefinition("quench", "QUENCH", "governed_bot", "Independently review technical, security and verification evidence on a host separate from the author.", "orca", "kiln", ("all",), ("review", "verify", "adjudicate_security", "recommend_block"), ("author_reviewed_change", "approve_r3", "merge", "deploy", "connector_write"), ("smith", "security_gate", "orca"), ("orca", "fry"), False, "independent_runtime_and_identity_acceptance"),
    "security_gate": RoleDefinition("security_gate", "Independent Security Gate", "deterministic_service", "Scan supplied artifacts for secrets, unsafe configuration, dependencies and provenance risks.", "orca", "forge", ("all",), ("scan_supplied_artifacts", "report_redacted_findings"), ("author", "approve", "enforce", "read_repository", "use_connectors", "deploy"), ("smith", "orca"), ("quench", "orca"), True, "advisory_only_contract_verified"),
    "anvil_reflex": RoleDefinition("anvil_reflex", "ANVIL Reflex", "model_service", "Provide optional low-latency triage, summarization and prompt preparation.", "orca", "anvil", ("forge", "orca"), ("prepare", "summarize", "triage"), ("author_release", "approve", "review_release", "deploy", "be_required_for_uptime"), ("fry", "orca"), ("orca", "smith"), False, "local_adapter_and_output_contract_acceptance"),
    "forge_retrieval": RoleDefinition("forge_retrieval", "FORGE Retrieval", "retrieval_service", "Ingest approved sources and return cited, freshness-labelled context without deciding actions.", "orca", "forge", ("all",), ("index_approved_content", "retrieve", "rerank", "cite_sources"), ("connector_write", "approve", "author", "deploy", "invent_sources"), ("orca", "smith"), ("orca", "smith", "deepseek_reasoner"), False, "embedding_reranker_and_connector_read_acceptance"),
    "ember_sentinel": RoleDefinition("ember_sentinel", "EMBER Sentinel", "deterministic_service", "Observe UPS, backups, watchdogs, wake recovery and fleet health continuously.", "orca", "ember", ("forge",), ("observe", "alert", "send_bounded_wake_signal"), ("generative_reasoning", "author", "approve", "remote_shell", "shutdown_without_r3"), ("heartbeat_agents",), ("orca", "fry"), True, "deployed_deterministic_monitoring"),
    "heartbeat_agents": RoleDefinition("heartbeat_agents", "Fleet Heartbeat Agents", "infrastructure_agent", "Publish signed freshness, health and service observations from enrolled nodes.", "orca", None, ("forge",), ("publish_signed_health",), ("reason", "author", "approve", "execute_remote_commands", "use_connectors"), (), ("orca", "ember_sentinel"), True, "owner_keyed_enrollment"),
    "ampere": RoleDefinition("ampere", "AMPERE", "specialist_candidate", "Proposed electronics design, schematic, PCB, power and component-analysis specialist.", "orca", None, ("bgm", "forge"), ("propose_electronics_design", "analyze_components"), ("physical_actuation", "purchase", "approve", "deploy", "body_impact"), ("orca",), ("smith", "quench", "fry"), False, "role_review_and_bgm_safety_acceptance"),
    "relay": RoleDefinition("relay", "RELAY", "specialist_candidate", "Proposed embedded firmware, device bring-up, protocol and hardware-in-loop test specialist.", "orca", None, ("bgm", "forge"), ("propose_firmware", "design_bringup_test"), ("flash_device", "physical_actuation", "approve", "deploy", "body_impact"), ("orca", "ampere"), ("smith", "quench", "fry"), False, "role_review_and_hardware_lab_acceptance"),
    "iris": RoleDefinition("iris", "IRIS", "project_edge_system", "BGM edge sensing, calibration, logging, bounded inference and dashboards under the BGM lane.", "fry", "iris", ("bgm",), ("sense", "log", "calibrate", "bounded_edge_inference"), ("cross_lane_authority", "approve", "deploy_without_r3", "body_action_without_r3"), ("orca", "relay"), ("orca", "fry"), False, "bgm_specific_safety_and_deployment_acceptance"),
}


def validate_role_catalog() -> None:
    if set(ROLE_CATALOG) != {role.id for role in ROLE_CATALOG.values()}:
        raise ValueError("role catalog keys must match role ids")
    for role in ROLE_CATALOG.values():
        if not role.duty or not role.owner or not role.lanes or not role.activation_gate:
            raise ValueError(f"role is incomplete: {role.id}")
    if ROLE_CATALOG["smith"].node_id == ROLE_CATALOG["quench"].node_id:
        raise ValueError("author and independent reviewer must use separate nodes")
    if "approve_r3" in ROLE_CATALOG["orca"].authority:
        raise ValueError("ORCA cannot approve R3 work")
    for role_id in ("deepseek_reasoner", "anvil_reflex", "forge_retrieval"):
        if {"author", "approve", "deploy"} & set(ROLE_CATALOG[role_id].authority):
            raise ValueError(f"service has agent authority: {role_id}")


def role_snapshot() -> list[dict]:
    validate_role_catalog()
    return [asdict(role) for role in ROLE_CATALOG.values()]


validate_role_catalog()
