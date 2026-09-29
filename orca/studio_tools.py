from __future__ import annotations

from collections.abc import Callable

from .inventory import InventoryReadError, analyze_inventory_snapshot


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

    def handlers(self) -> dict:
        return {
            "studio.capabilities": self.capabilities,
            "inventory.search": self.inventory_search,
            "node.observe": self.node_observe,
        }
