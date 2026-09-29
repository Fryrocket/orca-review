from orca.studio_tools import StudioReadTools
from orca.tools import BOT_TOOL_MANIFESTS, TOOL_CATALOG


class Inventory:
    def snapshot(self):
        return {
            "source": "test inventory",
            "items": [
                {"sku": "CAP-100", "name": "100 uF capacitor", "category": "passives",
                 "location": "BIN-A", "quantity": 12, "reserved": 2,
                 "reorder_point": 5, "unit": "ea"},
                {"sku": "MCU-1", "name": "Controller", "category": "IC",
                 "location": "BIN-B", "quantity": 0, "unit": "ea"},
            ],
        }


def snapshot():
    return {
        "tool_catalog": {"web.search": {"family": "web"}},
        "connector_capabilities": [{"id": "drive", "read": True}],
        "nodes": [{"id": "forge", "status": "healthy"},
                  {"id": "kiln", "status": "healthy"}],
        "evidence_chain_valid": True,
        "emergency_stop": False,
        "paused_nodes": [],
        "paused_lanes": [],
    }


def test_chat_capability_registry_covers_every_sidebar_workspace_and_apps():
    result = StudioReadTools(control_snapshot=snapshot).capabilities(area="all")
    assert {item["id"] for item in result["workspaces"]} == {
        "studio", "projects", "canvas", "inventory", "engineering",
        "operations", "business", "product-builder",
    }
    assert {"KiCad PCB Editor", "Writer", "Calc", "Web browser"} <= set(result["applications"])
    assert "web.search" in result["read_tools"]
    assert "approval-controlled" in result["governance"]


def test_inventory_search_is_read_only_filtered_and_bounded():
    tools = StudioReadTools(control_snapshot=snapshot, inventory_provider=Inventory())
    result = tools.inventory_search(query="capacitor", limit=5)
    assert result["status"] == "ok"
    assert result["matches"][0]["sku"] == "CAP-100"
    assert result["matches"][0]["available"] == 10
    assert result["matches"][0]["status"] == "healthy"
    stockout = tools.inventory_search(state="stockout")
    assert [item["sku"] for item in stockout["matches"]] == ["MCU-1"]


def test_node_observe_filters_and_new_chat_tools_are_manifested_read_only():
    tools = StudioReadTools(control_snapshot=snapshot)
    assert [node["id"] for node in tools.node_observe(node_id="kiln")["nodes"]] == ["kiln"]
    required = {"studio.capabilities", "inventory.search", "node.observe"}
    assert required <= BOT_TOOL_MANIFESTS["orca"]
    assert all(not TOOL_CATALOG[name].mutates for name in required)
