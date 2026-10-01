from orca.edge_inference import EDGE_WORKFLOWS, H8_MODELS, edge_inference_blueprint


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
