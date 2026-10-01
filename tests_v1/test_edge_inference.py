import pytest

from orca.edge_inference import (
    EDGE_WORKFLOWS, H8_MODELS, edge_inference_blueprint, plan_edge_workflow)


def test_h8_catalog_contains_only_explicit_hailo8_artifacts():
    assert {model.task for model in H8_MODELS} == {
        "object_detection", "instance_segmentation", "pose_estimation"
    }
    assert all(model.artifact.endswith("_h8.hef") for model in H8_MODELS)
    assert all(model.state == "runtime_benchmarked" for model in H8_MODELS)
    assert all(model.benchmark_fps > 0 for model in H8_MODELS)


def test_edge_workflows_cover_orca_areas_without_granting_authority():
    areas = {workflow.area for workflow in EDGE_WORKFLOWS}
    assert {"inventory", "engineering", "canvas", "product-builder", "operations", "business", "bgm", "studio"} <= areas
    snapshot = edge_inference_blueprint(camera_connected=True)
    assert snapshot["camera"]["state"] == "accepted_available"
    assert snapshot["runtime"]["job_broker"] == "live_camera_and_file_accepted"
    assert snapshot["runtime"]["model_invocation"] == "signed_bounded_camera_and_file_jobs"
    assert snapshot["runtime"]["camera_and_file_inputs"] == "accepted"
    assert snapshot["runtime"]["automatic_execution"] is False
    assert "may not publish" in snapshot["governance"]["authority"]


def test_camera_disconnected_is_truthfully_reported():
    snapshot = edge_inference_blueprint(camera_connected=False)
    assert snapshot["camera"]["connected"] is False
    assert snapshot["camera"]["state"] == "accepted_not_connected"


def test_edge_workflow_plan_is_read_only_and_truthfully_gated():
    pending = plan_edge_workflow(workflow_id="inventory_visual_count")
    assert pending["state"] == "needs_declared_label_scope"
    ready = plan_edge_workflow(
        workflow_id="inventory_visual_count", labels=["box", "bottle", "box"])
    assert ready["state"] == "ready_for_bounded_dry_run"
    assert ready["declared_labels"] == ["box", "bottle"]
    assert ready["may_execute"] is False
    blocked = plan_edge_workflow(workflow_id="pcb_assembly_inspection", input_kind="image")
    assert blocked["state"] == "blocked_custom_model_required"
    assert "validated custom Hailo-8 model" in blocked["next_gate"]
    assert "self-approval" in blocked["prohibited"]
    with pytest.raises(ValueError, match="not registered"):
        plan_edge_workflow(workflow_id="arbitrary")
