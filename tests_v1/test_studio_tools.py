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
    assert {"KiCad PCB Editor", "Writer", "Calc", "Web browser (Google Chrome)", "Document Scanner",
            "Image Viewer", "Thunderbird Mail", "Videos"} <= set(result["applications"])
    assert "web.search" in result["read_tools"]
    assert "approval-controlled" in result["governance"]
    assert any(item["service"] == "KiCad PCB Editor" and "save_project_artifact" in item["access"]
               for item in result["service_access"])
    assert "ORCA source code and active release" in result["protected_core"]
    assert "Frontier engineering sessions only" in result["core_authority"]
    assert "terminal and console tools" in result["application_policy"]["blocked"]
    assert "sending mail or messages" in result["application_policy"]["approval_controlled"]


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
    required = {"studio.capabilities", "inventory.search", "node.observe",
                "temper.inference_capabilities", "temper.plan_inference_workflow",
                "temper.plan_inventory_dataset", "temper.plan_inventory_capture",
                "temper.validate_inventory_dataset", "temper.plan_hailo_conversion"}
    assert required <= BOT_TOOL_MANIFESTS["orca"]
    assert all(not TOOL_CATALOG[name].mutates for name in required)


def test_temper_inference_tool_is_bounded_read_only_and_filters_workflows():
    tools = StudioReadTools(control_snapshot=snapshot)
    camera = tools.temper_inference_capabilities(input_type="camera")
    assert camera["node_id"] == "temper"
    assert camera["camera"]["state"] == "accepted_available"
    assert any(model["id"] == "yolov6n_h8" for model in camera["models"])
    assert any(workflow["id"] == "inventory_visual_count" for workflow in camera["workflows"])
    assert camera["runtime"]["automatic_execution"] is False
    assert "No facial recognition" in camera["governance"]["privacy"]


def test_temper_workflow_planner_never_executes_and_keeps_custom_models_blocked():
    tools = StudioReadTools(control_snapshot=snapshot)
    ready = tools.temper_plan_inference_workflow(
        workflow_id="product_media_preflight", input_kind="camera")
    assert ready["state"] == "ready_for_bounded_dry_run"
    assert ready["may_execute"] is False
    blocked = tools.temper_plan_inference_workflow(
        workflow_id="receiving_and_packaging_check", input_kind="image")
    assert blocked["state"] == "blocked_custom_model_required"


def test_temper_inventory_dataset_planner_is_read_only_and_inventory_bound():
    tools = StudioReadTools(control_snapshot=snapshot)
    plan = tools.temper_plan_inventory_dataset(
        name="Bench parts", version="1", source="Owner-captured bench images",
        license_name="Owner-controlled",
        labels=[{"id": "CAP-100UF", "name": "100 uF capacitor", "sku": "CAP-100"}])
    assert plan["state"] == "capture_plan_ready"
    assert plan["labels"][0]["sku"] == "CAP-100"
    assert plan["may_capture"] is False
    assert plan["may_train"] is False
    assert plan["may_deploy"] is False
    capture = tools.temper_plan_inventory_capture(
        manifest=plan, session_id="STUDIO-TEST-1", camera_profile="USB test camera")
    assert capture["frames_captured"] == 0
    assert capture["may_capture"] is False
