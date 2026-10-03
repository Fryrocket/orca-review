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
    "orca": RoleDefinition("orca", "ORCA", "governed_bot", "Classify, route and pause work; enforce policy, evidence, lane isolation and approval boundaries.", "fry", "forge", ("all",), ("route", "classify", "pause", "record_evidence"), ("impersonate_fry", "approve_r3", "author_release", "review_own_work", "deploy"), ("fry", "ember_sentinel", "heartbeat_agents"), ("anvil_reflex", "qwen_conversation", "gemini", "security_gate", "quench", "fry"), True, "deterministic_control_plane_verified"),
    "smith": RoleDefinition("smith", "SMITH", "governed_bot", "Author scoped code, documentation, synthesis and operations plans with tests and rollback evidence.", "orca", "forge", ("all",), ("author", "propose_change", "run_bounded_evaluation"), ("self_review", "approve", "merge", "deploy", "connector_write", "unbounded_tools"), ("orca", "anvil_reflex", "qwen_conversation", "forge_retrieval"), ("security_gate", "quench", "orca"), False, "crucible_model_runtime_and_quench_acceptance"),
    "gemini": RoleDefinition("gemini", "Gemini 3.8 Flash", "governed_frontier_bot", "Produce scoped coding, documentation and engineering proposals from sanitized prompts through the bounded Gemini free-tier bridge.", "orca", "forge", ("all",), ("analyze_sanitized_prompt", "propose_code", "propose_documentation", "propose_engineering"), ("read_private_data", "use_tools", "self_review", "approve", "merge", "deploy", "connector_write", "paid_fallback"), ("orca",), ("quench", "orca"), True, "gemini_free_bridge_and_quench_separation_verified"),
    "qwen_conversation": RoleDefinition("qwen_conversation", "Qwen Conversation", "model_service", "Power ORCA conversation, explanations, brainstorming and planning without author or approval identity.", "orca", "forge", ("all",), ("analyze", "challenge_assumptions", "propose_options"), ("act_as_agent", "author_change", "approve", "review_release", "use_tools", "deploy"), ("orca", "gemini"), ("gemini", "orca"), False, "crucible_model_runtime_and_output_contract_acceptance"),
    "quench": RoleDefinition("quench", "QUENCH", "governed_bot", "Independently review technical, security and verification evidence on a host separate from the author.", "orca", "kiln", ("all",), ("review", "verify", "adjudicate_security", "recommend_block"), ("author_reviewed_change", "approve_r3", "merge", "deploy", "connector_write"), ("gemini", "security_gate", "orca"), ("orca", "fry"), False, "independent_runtime_and_identity_acceptance"),
    "security_gate": RoleDefinition("security_gate", "Independent Security Gate", "deterministic_service", "Scan supplied artifacts for secrets, unsafe configuration, dependencies and provenance risks.", "orca", "forge", ("all",), ("scan_supplied_artifacts", "report_redacted_findings"), ("author", "approve", "enforce", "read_repository", "use_connectors", "deploy"), ("gemini", "orca"), ("quench", "orca"), True, "advisory_only_contract_verified"),
    "anvil_reflex": RoleDefinition("anvil_reflex", "ANVIL Reflex", "model_service", "Provide optional low-latency triage, summarization and prompt preparation.", "orca", "anvil", ("forge", "orca"), ("prepare", "summarize", "triage"), ("author_release", "approve", "review_release", "deploy", "be_required_for_uptime"), ("fry", "orca"), ("orca", "gemini"), False, "local_adapter_and_output_contract_acceptance"),
    "forge_retrieval": RoleDefinition("forge_retrieval", "FORGE Retrieval", "retrieval_service", "Ingest approved sources and return cited, freshness-labelled context without deciding actions.", "orca", "forge", ("all",), ("index_approved_content", "retrieve", "rerank", "cite_sources"), ("connector_write", "approve", "author", "deploy", "invent_sources"), ("orca", "gemini"), ("orca", "gemini", "qwen_conversation"), False, "embedding_reranker_and_connector_read_acceptance"),
    "ember_sentinel": RoleDefinition("ember_sentinel", "EMBER Sentinel", "deterministic_service", "Observe UPS, backups, watchdogs, wake recovery and fleet health continuously.", "orca", "ember", ("forge",), ("observe", "alert", "send_bounded_wake_signal"), ("generative_reasoning", "author", "approve", "remote_shell", "shutdown_without_r3"), ("heartbeat_agents",), ("orca", "fry"), True, "deployed_deterministic_monitoring"),
    "heartbeat_agents": RoleDefinition("heartbeat_agents", "Fleet Heartbeat Agents", "infrastructure_agent", "Publish signed freshness, health and service observations from enrolled nodes.", "orca", None, ("forge",), ("publish_signed_health",), ("reason", "author", "approve", "execute_remote_commands", "use_connectors"), (), ("orca", "ember_sentinel"), True, "owner_keyed_enrollment"),
    "ampere": RoleDefinition("ampere", "AMPERE", "specialist_candidate", "Proposed electronics design, schematic, PCB, power and component-analysis specialist.", "orca", None, ("bgm", "forge"), ("propose_electronics_design", "analyze_components"), ("physical_actuation", "purchase", "approve", "deploy", "body_impact"), ("orca",), ("gemini", "quench", "fry"), False, "role_review_and_bgm_safety_acceptance"),
    "relay": RoleDefinition("relay", "RELAY", "specialist_candidate", "Proposed embedded firmware, device bring-up, protocol and hardware-in-loop test specialist.", "orca", None, ("bgm", "forge"), ("propose_firmware", "design_bringup_test"), ("flash_device", "physical_actuation", "approve", "deploy", "body_impact"), ("orca", "ampere"), ("gemini", "quench", "fry"), False, "role_review_and_hardware_lab_acceptance"),
    "temper": RoleDefinition("temper", "TEMPER", "forge_edge_system", "FORGE edge compute, MQTT, sensing, calibration, logging, telemetry, storage and gated Hailo inference while retaining BGM duties.", "fry", "temper", ("forge", "bgm"), ("sense", "log", "calibrate", "publish_signed_health", "serve_mqtt", "store_edge_data", "stage_bounded_edge_work"), ("approve", "deploy_without_r3", "body_action_without_r3", "expose_secret", "unbounded_remote_execution"), ("orca", "relay", "heartbeat_agents"), ("temper_watch", "reliability_sentinel", "orca", "fry"), False, "forge_membership_verified_workload_acceptance_pending"),
    "reliability_sentinel": RoleDefinition("reliability_sentinel", "Reliability Sentinel", "operations_bot", "Watch fleet health, latency, resources, services, stuck work and recovery thresholds; report exceptions without changing systems.", "orca", "ember", ("forge",), ("observe_health", "detect_anomaly", "stage_alert"), ("remote_shell", "restart_service", "change_threshold", "approve", "deploy"), ("heartbeat_agents", "ember_sentinel"), ("orca", "recovery_marshal", "fry"), True, "read_only_telemetry_and_exception_reporting_accepted_20261001"),
    "recovery_marshal": RoleDefinition("recovery_marshal", "Recovery Marshal", "operations_bot", "Track backup freshness, checksums, restore readiness, rollback evidence and disaster-recovery drills.", "orca", "ember", ("forge",), ("inspect_backup", "verify_checksum", "stage_restore_drill", "report_recovery_readiness"), ("delete_backup", "prune_repository", "restore_production", "read_secret", "approve", "deploy"), ("reliability_sentinel", "ember_sentinel", "continuity_keeper"), ("evidence_auditor", "orca", "fry"), True, "non_destructive_restore_drill_accepted_20260930"),
    "connector_steward": RoleDefinition("connector_steward", "Connector Steward", "operations_bot", "Monitor approved connectors for authentication, freshness, scope, duplicates, failures and reconciliation gaps.", "orca", "forge", ("all",), ("inspect_connector", "test_read_path", "detect_sync_gap", "stage_reauth_request"), ("read_credential", "expand_scope", "connector_write", "contact_outsider", "approve", "deploy"), ("orca", "continuity_keeper"), ("evidence_auditor", "orca", "fry"), True, "read_only_connector_matrix_accepted_20260930"),
    "evidence_auditor": RoleDefinition("evidence_auditor", "Evidence Auditor", "independent_review_bot", "Verify bot claims, artifact lineage, approvals, evidence integrity and completion without authoring the reviewed work.", "orca", "kiln", ("all",), ("inspect_evidence", "verify_claim", "recommend_block", "report_contradiction"), ("author_reviewed_work", "approve_r3", "merge", "deploy", "connector_write"), ("recovery_marshal", "connector_steward", "orca"), ("quench", "orca", "fry"), True, "independence_and_evidence_contract_accepted_20260930"),
    "security_watch": RoleDefinition("security_watch", "Security Watch", "security_bot", "Review exposure, permissions, connector scopes, software changes and secret-handling signals; remain advisory.", "orca", "kiln", ("all",), ("inspect_security_posture", "scan_metadata", "stage_finding"), ("read_secret", "lock_account", "change_firewall", "revoke_access", "approve", "deploy"), ("security_gate", "connector_steward"), ("quench", "orca", "fry"), True, "advisory_security_review_accepted_20260930"),
    "budget_officer": RoleDefinition("budget_officer", "Budget Officer", "business_bot", "Maintain budgets, compare read-only actuals, calculate runway and margins, forecast obligations and report exceptions.", "orca", "forge", ("forge", "inventory"), ("read_financial_summary", "calculate_budget", "forecast_runway", "stage_variance_report"), ("move_money", "pay_bill", "trade", "change_account", "file_tax", "approve"), ("connector_steward", "inventory_steward"), ("evidence_auditor", "orca", "fry"), True, "read_only_finance_and_budget_accepted_20260930"),
    "legal_compliance_clerk": RoleDefinition("legal_compliance_clerk", "Legal and Compliance Clerk", "business_bot", "Track contracts, filings, product rules, privacy, marketplace policy and counsel questions with cited evidence.", "orca", "forge", ("forge", "inventory"), ("research_rule", "draft_checklist", "organize_contract", "prepare_counsel_pack"), ("give_final_legal_advice", "sign", "file", "certify", "contact_authority", "approve"), ("product_development_lead", "channel_operator", "connector_steward"), ("evidence_auditor", "orca", "fry"), True, "legal_evidence_and_professional_review_accepted_20260930"),
    "inventory_steward": RoleDefinition("inventory_steward", "Inventory Steward", "business_bot", "Reconcile item records, counts, locations, reservations, purchasing proposals, lots, serials, RMAs and replenishment.", "orca", "forge", ("inventory",), ("inspect_inventory", "simulate_reservation", "stage_replenishment", "report_variance"), ("mutate_stock_without_approval", "purchase", "write_off", "ship", "contact_vendor", "approve"), ("product_development_lead", "channel_operator"), ("budget_officer", "evidence_auditor", "orca", "fry"), True, "inventory_simulation_and_approval_accepted_20260930"),
    "product_scout": RoleDefinition("product_scout", "Product Scout", "business_bot", "Research product opportunities and score demand evidence, margin, competition, supplier fit, compliance and return risk.", "orca", "forge", ("forge",), ("research_product", "compare_supplier", "score_candidate", "cite_evidence"), ("scrape_prohibited_source", "invent_sales_data", "purchase", "contact_vendor", "publish", "approve"), ("fry", "connector_steward"), ("product_development_lead", "budget_officer", "legal_compliance_clerk"), True, "cited_synthetic_product_research_accepted_20261001"),
    "product_development_lead": RoleDefinition("product_development_lead", "Product Development Lead", "engineering_bot", "Coordinate requirements, calculations, CAD, BOM, simulation, prototype, test and manufacturing-readiness evidence.", "orca", "forge", ("forge", "bgm", "inventory"), ("plan_product", "run_bounded_calculation", "stage_design_artifact", "coordinate_review"), ("physical_actuation", "order_part", "release_manufacturing", "approve", "deploy"), ("product_scout", "ampere", "relay"), ("inventory_steward", "legal_compliance_clerk", "evidence_auditor", "quench", "fry"), True, "bounded_product_engineering_and_review_accepted_20261001"),
    "channel_operator": RoleDefinition("channel_operator", "Channel Operator", "business_bot", "Prepare governed listings, channel mappings, prices, orders and fulfillment drafts across approved sales platforms.", "orca", "forge", ("forge", "inventory"), ("prepare_listing", "map_inventory", "stage_order", "reconcile_channel"), ("publish", "refund", "message_customer", "change_price_live", "spend", "ship", "approve"), ("inventory_steward", "creative_director", "legal_compliance_clerk"), ("evidence_auditor", "orca", "fry"), True, "draft_only_multichannel_acceptance_20261001"),
    "creative_director": RoleDefinition("creative_director", "Creative Director", "media_bot", "Coordinate CRUCIBLE for product photos, artwork, diagrams and short videos with provenance and claim review.", "orca", "forge", ("forge",), ("stage_media_job", "inspect_output", "prepare_campaign_asset"), ("publish", "run_paid_ad", "make_unverified_claim", "use_unlicensed_asset", "approve"), ("product_development_lead", "channel_operator"), ("legal_compliance_clerk", "evidence_auditor", "orca", "fry"), True, "draft_media_provenance_and_claim_review_accepted_20261001"),
    "temper_watch": RoleDefinition("temper_watch", "TEMPER Watch", "edge_operations_bot", "Monitor TEMPER connectivity, Pi and NVMe health, Hailo readiness, MQTT queues, sensors, storage and edge-model freshness as part of FORGE.", "orca", "temper", ("forge", "bgm"), ("observe_temper", "validate_sensor_freshness", "inspect_edge_capacity", "stage_edge_alert"), ("body_action", "change_model", "publish_mqtt", "remote_shell", "approve", "deploy"), ("temper", "heartbeat_agents"), ("reliability_sentinel", "orca", "fry"), False, "temper_mqtt_recovery_and_soak_acceptance"),
    "browser_operator": RoleDefinition("browser_operator", "Browser Operator", "tool_bot", "Perform governed navigation, research, downloads, uploads and form preparation in approved browser profiles.", "orca", "kiln", ("all",), ("navigate", "read_page", "download", "prepare_form", "stage_upload"), ("purchase", "submit_form", "send_message", "publish", "change_account", "read_password", "approve"), ("orca", "connector_steward"), ("evidence_auditor", "orca", "fry"), True, "private_ephemeral_page_read_and_action_boundary_accepted_20261001"),
    "daily_briefing_officer": RoleDefinition("daily_briefing_officer", "Daily Briefing Officer", "reporting_bot", "Produce one concise owner briefing covering completed work, failures, approvals, money, inventory, fleet health and priorities.", "orca", "forge", ("all",), ("read_approved_summary", "compile_briefing", "stage_report"), ("contact_outsider", "change_priority_without_owner", "hide_failure", "approve", "deploy"), ("reliability_sentinel", "recovery_marshal", "connector_steward", "budget_officer", "inventory_steward", "evidence_auditor"), ("orca", "fry"), True, "cross_source_truthful_owner_briefing_accepted_20261001"),
    "continuity_keeper": RoleDefinition("continuity_keeper", "Continuity Keeper", "documentation_bot", "Reconcile material project changes into the existing authoritative state, Drive, Notion and Linear records without duplication.", "orca", "anvil", ("all",), ("inspect_completed_context", "update_approved_record", "report_sync_gap"), ("create_duplicate_record", "change_live_system", "read_secret", "deploy", "approve"), ("orca", "fry"), ("recovery_marshal", "connector_steward", "evidence_auditor"), False, "record_reconciliation_and_monitoring_acceptance"),
}


def validate_role_catalog() -> None:
    if set(ROLE_CATALOG) != {role.id for role in ROLE_CATALOG.values()}:
        raise ValueError("role catalog keys must match role ids")
    for role in ROLE_CATALOG.values():
        if not role.duty or not role.owner or not role.lanes or not role.activation_gate:
            raise ValueError(f"role is incomplete: {role.id}")
    if ROLE_CATALOG["gemini"].node_id == ROLE_CATALOG["quench"].node_id:
        raise ValueError("author and independent reviewer must use separate nodes")
    if "approve_r3" in ROLE_CATALOG["orca"].authority:
        raise ValueError("ORCA cannot approve R3 work")
    for role_id in ("qwen_conversation", "anvil_reflex", "forge_retrieval"):
        if {"author", "approve", "deploy"} & set(ROLE_CATALOG[role_id].authority):
            raise ValueError(f"service has agent authority: {role_id}")
    governed = set(ROLE_CATALOG) - {"fry"}
    for role_id in governed:
        if {"approve_r3", "deploy"} & set(ROLE_CATALOG[role_id].authority):
            raise ValueError(f"bot has owner authority: {role_id}")


def role_snapshot() -> list[dict]:
    validate_role_catalog()
    rows = []
    for role in ROLE_CATALOG.values():
        if role.id == "smith":
            continue
        row = asdict(role)
        row["receives_from"] = tuple("gemini" if x == "smith" else x for x in row["receives_from"])
        row["hands_off_to"] = tuple("gemini" if x == "smith" else x for x in row["hands_off_to"])
        rows.append(row)
    return rows


validate_role_catalog()
