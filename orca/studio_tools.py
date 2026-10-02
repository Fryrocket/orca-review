from __future__ import annotations

from collections.abc import Callable

from .inventory import InventoryReadError, analyze_inventory_snapshot
from .edge_inference import edge_inference_blueprint, plan_edge_workflow
from .vision_dataset import (
    plan_hailo_conversion,
    plan_inventory_capture_session,
    plan_inventory_vision_dataset,
    validate_inventory_dataset,
)


WORKSPACES = (
    {"id": "studio", "name": "Studio", "purpose": "Chat, routing, memory, images and video"},
    {"id": "projects", "name": "Code", "purpose": "Coding work and review"},
    {"id": "canvas", "name": "Canvas", "purpose": "Local image generation, editing and short video"},
    {"id": "inventory", "name": "Inventory", "purpose": "Parts, counts, reservations and governed stock workflows"},
    {"id": "engineering", "name": "Engineering", "purpose": "Calculators, KiCad and LibreOffice tools"},
    {"id": "operations", "name": "Operations", "purpose": "Jobs, approvals, evidence, agents, connectors and node health"},
    {"id": "business", "name": "QuasarVolt", "purpose": "Business, sales, suppliers, marketing and records"},
    {"id": "product-builder", "name": "Product Builder", "purpose": "Governed product development from discovery through lifecycle"},
)

APPLICATIONS = (
    "Web browser (Google Chrome)", "Firefox fallback", "Files", "Calculator", "Text editor", "KiCad",
    "KiCad Image Converter", "KiCad PCB Calculator", "KiCad PCB Editor",
    "KiCad Schematic Editor", "KiCad Gerber Viewer", "FreeCAD", "LibreOffice", "Writer", "Calc", "Draw",
    "Impress", "LibreOffice Math", "Archive Manager", "Calendar",
    "Characters", "Chatbox", "Cheese", "Document Scanner", "Document Viewer",
    "Fonts", "Image Viewer", "Power Statistics", "Rhythmbox", "Shotwell",
    "Thunderbird Mail", "To Do", "Videos", "Help",
)

APPLICATION_POLICY = {
    "automatic": (
        "engineering, office, media, document, scanning, viewing, browser, calendar, "
        "task, file and local utility applications"
    ),
    "approval_controlled": (
        "sending mail or messages, publishing, purchases, account changes, credential entry, "
        "downloads that execute software, printing, and external writes"
    ),
    "blocked": (
        "terminal and console tools, passwords and keys, settings, disks, network configuration, "
        "software installation or updates, startup configuration, remote desktop, peer-to-peer "
        "transfer, service control, permissions, and security administration"
    ),
    "write_roots": ("ORCA Projects", "QuasarVolt business records", "explicitly selected user files"),
}

BUSINESS_AREAS = (
    "market and product discovery", "vendors and supplier intelligence",
    "catalog, pricing and inventory", "sales channels and storefronts",
    "customers, support and returns", "marketing and organic growth",
    "orders, fulfillment and logistics", "accounting, finance and tax packs",
    "documents and records", "AWS and cloud operations", "compliance and risk",
    "quality, RMA and recalls", "analytics and KPIs", "contracts and intellectual property",
    "agent control and business simulation",
)

SERVICE_ACCESS = (
    {"service": "KiCad PCB Editor", "access": ["open", "create_draft", "save_project_artifact"], "write_scope": "ORCA Projects only"},
    {"service": "KiCad suite", "access": ["open", "file_handoff"], "write_scope": "application-owned project files"},
    {"service": "FreeCAD", "access": ["open", "file_handoff"], "write_scope": "application-owned project files"},
    {"service": "LibreOffice suite", "access": ["open", "file_handoff"], "write_scope": "application-owned business and project files"},
    {"service": "Web services", "access": ["open_governed_browser", "navigate", "research", "prepare_forms"],
     "write_scope": "downloads and uploads stay scoped; no account or external write without approval"},
    {"service": "KILN non-core applications", "access": ["open", "task_handoff", "project_file_handoff"],
     "write_scope": "approved project and business locations only"},
)

PROTECTED_CORE = (
    "ORCA source code and active release", "policy and approval rules",
    "authentication and secrets", "service units and deployment configuration",
    "evidence integrity controls and rollback assets",
)

STUDIO_MODES = (
    {"id": "auto", "name": "Auto", "status": "live", "purpose": "Route the request to the least-powerful capable specialist."},
    {"id": "reason", "name": "Chat", "status": "live", "purpose": "Conversation, explanation, planning and brainstorming."},
    {"id": "code", "name": "Code", "status": "live", "purpose": "Governed coding and implementation drafts; deployment remains gated."},
    {"id": "review", "name": "Review", "status": "live", "purpose": "Independent technical and evidence review through QUENCH."},
    {"id": "engineer", "name": "Engineer", "status": "live", "purpose": "Engineering analysis with explicit assumptions, calculations and verification."},
    {"id": "visual", "name": "Visual", "status": "live", "purpose": "Visual direction, diagrams and image-editing plans."},
    {"id": "photo", "name": "Photo", "status": "live", "purpose": "Bounded local photos, art, illustrations and product-image jobs on CRUCIBLE."},
    {"id": "video", "name": "Video", "status": "live", "purpose": "Bounded local short-video jobs on CRUCIBLE; publishing remains gated."},
)

MANUAL_STATUS = {
    "live": (
        "Studio, Code, Canvas, Inventory, Engineering, Operations, QuasarVolt, Product Builder and Bot Monitor interfaces",
        "Legal, Accounting, Budget and Connections control-center interfaces",
        "governed chat routing, durable chat memory, approvals, evidence, rollback and signed five-node telemetry",
        "local CRUCIBLE image generation and bounded short-video generation",
        "TEMPER enrollment, signed telemetry, USB-camera discovery and accepted packaged Hailo-8 vision models",
    ),
    "staged_or_connection_dependent": (
        "bank and ChatGPT Finances read-only feeds until the owner authorizes an eligible account",
        "mail reading and Meta Muse email organization until an owner-authorized provider session exists",
        "live marketplace, supplier, cloud and publishing connectors until their scoped authentication and read/write acceptance passes",
    ),
    "planned_or_gated": (
        "custom TEMPER models, future local speech recognition and new plugins until provenance, tests and approval pass",
        "physical whole-site outage and UPS-on-battery drills until the owner is present",
    ),
    "approval_gated": (
        "purchases, payments, transfers, publishing, sending messages, account changes, stock mutations, filings, signatures, deployment and irreversible actions",
    ),
    "unavailable_by_design": (
        "autonomous authority over money, legal conclusions, credentials, permissions or the protected ORCA core",
        "facial recognition, covert recording, medical diagnosis and unbounded physical control",
    ),
}


class StudioReadTools:
    """Read-only bridge from ORCA Chat to Studio's registered capabilities."""

    def __init__(self, *, control_snapshot: Callable[[], dict], inventory_provider=None) -> None:
        self.control_snapshot = control_snapshot
        self.inventory_provider = inventory_provider

    def capabilities(self, *, area: str = "all") -> dict:
        if area not in {"all", "workspaces", "applications", "business", "tools"}:
            raise ValueError("capability area is invalid")
        result = {
            "area": area,
            "governance": (
                "Read-only inspection may run directly. Stock changes, spending, publishing, "
                "external messages, permissions, deletion and irreversible actions remain approval-controlled."
            ),
            "core_authority": (
                "External authenticated Frontier engineering sessions only; ORCA Chat, local models, "
                "custom bots, workflows, plugins and KILN applications are excluded."
            ),
        }
        if area in {"all", "workspaces"}:
            result["workspaces"] = WORKSPACES
        if area in {"all", "applications"}:
            result["applications"] = APPLICATIONS
            result["application_policy"] = APPLICATION_POLICY
            result["service_access"] = SERVICE_ACCESS
        if area in {"all", "business"}:
            result["business_areas"] = BUSINESS_AREAS
        if area in {"all", "tools"}:
            snapshot = self.control_snapshot()
            result["read_tools"] = snapshot.get("tool_catalog", {})
            result["connectors"] = snapshot.get("connector_capabilities", [])
        result["protected_core"] = PROTECTED_CORE
        return result

    def user_manual_source(self) -> dict:
        """Return one compact, authoritative grounding record for self-documentation."""

        snapshot = self.control_snapshot()
        nodes = [
            {
                "id": node.get("id", node.get("node_id")),
                "state": node.get("state", node.get("status", "unproven")),
                "duty": node.get("duty", ""),
                "paused": bool(node.get("paused", False)),
            }
            for node in snapshot.get("nodes", [])
        ]
        return {
            "title": "ORCA User Manual authoritative source",
            "purpose": (
                "ORCA is a policy-first solo-operator control plane that plans, routes, "
                "executes bounded work, preserves evidence and stops at approval boundaries."
            ),
            "workspaces": WORKSPACES,
            "studio_modes": STUDIO_MODES,
            "business_control_centers": (
                "Legal and compliance", "Accounting", "Budget", "Connections and AI paths",
                "Bot Monitor", "product and market discovery", "sales and fulfillment",
                "creative advertising", "contracts", "tax operations", "data governance",
                "agent control", "business simulation",
            ),
            "governance": {
                "read_only": "Inspection, research, calculations, planning, drafting and simulations may run directly within bounded tools.",
                "approval_required": APPLICATION_POLICY["approval_controlled"],
                "blocked_from_everyday_chat": APPLICATION_POLICY["blocked"],
                "core_authority": (
                    "Only an explicitly authenticated external Frontier engineering session may change ORCA core code, policy, authentication, deployment or integrity controls, with tests and rollback."
                ),
                "protected_core": PROTECTED_CORE,
            },
            "status": MANUAL_STATUS,
            "temper": {
                "status": "enrolled_live_custom_models_gated",
                "hardware": "Raspberry Pi 5, 16 GiB RAM, 1 TB NVMe, Hailo-8 26 TOPS and owner-connected USB camera",
                "live_uses": (
                    "signed telemetry", "camera discovery", "packaged object detection",
                    "instance segmentation", "pose estimation", "bounded edge job brokering",
                    "inventory and assembly observation plans", "offline queueing",
                ),
                "gates": "No covert recording, face recognition, autonomous stock change, physical control or unreviewed custom-model deployment.",
            },
            "recovery": {
                "live": (
                    "immutable releases", "previous-release rollback", "signed node heartbeats",
                    "KILN-to-FORGE wake guard", "EMBER-to-KILN wake guard",
                    "fleet-readiness verification", "integrity checks", "encrypted backups",
                ),
                "owner_present": (
                    "whole-site power cut", "UPS battery drill", "firmware restore-after-power-loss settings",
                ),
            },
            "operating_loop": (
                "Choose a workspace or Auto mode", "state the desired outcome and constraints",
                "inspect the proposed route and evidence", "approve only real authority boundaries",
                "review the result and verification", "retain evidence and rollback",
            ),
            "example_seeds": (
                "concept-to-launch product simulation", "KiCad PCB draft and independent review",
                "inventory barcode lookup and approval-gated count adjustment",
                "product photo and 33-frame advertising clip", "budget-versus-actual analysis",
                "legal compliance evidence pack", "TEMPER camera inventory observation",
                "node outage detection and rollback-safe recovery",
            ),
            "fleet": nodes,
            "evidence_chain_valid": snapshot.get("evidence_chain_valid"),
            "paused_nodes": snapshot.get("paused_nodes", []),
        }

    def inventory_search(self, *, query: str = "", state: str = "all", limit: int = 20) -> dict:
        if not isinstance(query, str) or len(query) > 240:
            raise ValueError("inventory query must be bounded text")
        if state not in {"all", "healthy", "reorder", "stockout", "attention"}:
            raise ValueError("inventory state is invalid")
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("inventory limit must be 1-50")
        if self.inventory_provider is None:
            return {"status": "unavailable", "error": "KILN inventory source is not configured"}
        try:
            analysis = analyze_inventory_snapshot(self.inventory_provider.snapshot())
        except InventoryReadError:
            return {"status": "unavailable", "error": "KILN inventory source is unavailable"}
        needle = query.strip().casefold()
        matches = []
        for item in analysis["items"]:
            searchable = " ".join(str(item.get(key, "")) for key in (
                "sku", "name", "category", "location", "lot", "serial"))
            if needle and needle not in searchable.casefold():
                continue
            if state != "all" and item.get("status") != state:
                continue
            matches.append({key: item.get(key) for key in (
                "sku", "name", "category", "location", "on_hand", "reserved",
                "available", "reorder_point", "unit", "status", "lot", "serial")})
            if len(matches) >= limit:
                break
        return {"status": "ok", "source": "KILN canonical bench inventory",
                "query": query, "state": state, "matches": matches,
                "truncated": len(matches) == limit}

    def node_observe(self, *, node_id: str = "all") -> dict:
        if not isinstance(node_id, str) or not node_id or len(node_id) > 24:
            raise ValueError("node id is invalid")
        snapshot = self.control_snapshot()
        nodes = snapshot.get("nodes", [])
        if node_id.casefold() != "all":
            nodes = [node for node in nodes
                     if str(node.get("id", node.get("node_id", ""))).casefold() == node_id.casefold()]
        return {
            "nodes": nodes,
            "evidence_chain_valid": snapshot.get("evidence_chain_valid"),
            "emergency_stop": snapshot.get("emergency_stop"),
            "paused_nodes": snapshot.get("paused_nodes", []),
            "paused_lanes": snapshot.get("paused_lanes", []),
        }

    def temper_inference_capabilities(self, *, input_type: str = "all") -> dict:
        if input_type not in {"all", "camera", "image", "video", "sensor", "audio"}:
            raise ValueError("edge inference input type is invalid")
        result = edge_inference_blueprint(camera_connected=True)
        if input_type != "all":
            aliases = {"camera": "usb_camera", "sensor": "signal_quality", "audio": "automatic_speech_recognition"}
            target = aliases.get(input_type, input_type)
            result["models"] = [
                model for model in result["models"]
                if target in model["input_types"] or target == model["task"]
            ]
            result["workflows"] = [
                workflow for workflow in result["workflows"]
                if target in workflow["model_tasks"]
                or (input_type in {"camera", "image", "video"}
                    and any(task in {"object_detection", "instance_segmentation", "pose_estimation"}
                            for task in workflow["model_tasks"]))
            ]
        result["filter"] = input_type
        return result

    def temper_plan_inference_workflow(self, *, workflow_id: str,
                                       input_kind: str = "camera",
                                       labels: list[str] | None = None) -> dict:
        return plan_edge_workflow(
            workflow_id=workflow_id, input_kind=input_kind, labels=labels or [])

    def temper_plan_inventory_dataset(self, *, name: str, version: str,
                                      labels: list[dict], source: str,
                                      license_name: str,
                                      target_images_per_label: int = 120) -> dict:
        return plan_inventory_vision_dataset(
            name=name, version=version, labels=labels, source=source,
            license_name=license_name,
            target_images_per_label=target_images_per_label)

    def temper_plan_inventory_capture(self, *, manifest: dict, session_id: str,
                                      camera_profile: str,
                                      operator: str = "Fry") -> dict:
        return plan_inventory_capture_session(
            manifest=manifest, session_id=session_id,
            camera_profile=camera_profile, operator=operator)

    def temper_validate_inventory_dataset(self, *, manifest: dict,
                                          assets: list[dict]) -> dict:
        return validate_inventory_dataset(manifest=manifest, assets=assets)

    def temper_plan_hailo_conversion(self, *, manifest: dict, validation: dict,
                                     training_metrics: dict,
                                     toolchain: dict) -> dict:
        return plan_hailo_conversion(
            manifest=manifest, validation=validation,
            training_metrics=training_metrics, toolchain=toolchain)

    def handlers(self) -> dict:
        return {
            "studio.capabilities": self.capabilities,
            "studio.user_manual_source": self.user_manual_source,
            "inventory.search": self.inventory_search,
            "node.observe": self.node_observe,
            "temper.inference_capabilities": self.temper_inference_capabilities,
            "temper.plan_inference_workflow": self.temper_plan_inference_workflow,
            "temper.plan_inventory_dataset": self.temper_plan_inventory_dataset,
            "temper.plan_inventory_capture": self.temper_plan_inventory_capture,
            "temper.validate_inventory_dataset": self.temper_validate_inventory_dataset,
            "temper.plan_hailo_conversion": self.temper_plan_hailo_conversion,
        }
