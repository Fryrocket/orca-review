from __future__ import annotations

from .edge_inference import plan_edge_workflow
import hashlib

from .vision_dataset import (
    plan_hailo_conversion,
    plan_inventory_capture_session,
    plan_inventory_vision_dataset,
    validate_inventory_dataset,
)


def run_temper_inference_simulation() -> dict:
    """Exercise workflow planning with disposable inputs and no remote action."""
    checks: dict[str, bool] = {}
    inventory_pending = plan_edge_workflow(workflow_id="inventory_visual_count")
    inventory_ready = plan_edge_workflow(
        workflow_id="inventory_visual_count", labels=["box", "bottle"])
    media_ready = plan_edge_workflow(workflow_id="product_media_preflight")
    pcb_blocked = plan_edge_workflow(
        workflow_id="pcb_assembly_inspection", input_kind="image")
    dataset = plan_inventory_vision_dataset(
        name="Disposable inventory dataset", version="sim-1",
        labels=[{"id": "BOX-A", "name": "Box A", "sku": "BOX-A"}],
        source="Disposable synthetic fixtures", license_name="test-only",
        target_images_per_label=50)
    capture = plan_inventory_capture_session(
        manifest=dataset, session_id="SIM-CAPTURE-1",
        camera_profile="TEMPER USB camera disposable profile")
    assets = []
    sequence = (("train", 35), ("validation", 8), ("test", 7))
    counter = 0
    for split, amount in sequence:
        for _ in range(amount):
            counter += 1
            identity = f"box-a-{split}-{counter}"
            assets.append({
                "id": identity, "label_id": "BOX-A", "split": split,
                "sha256": hashlib.sha256(f"content-{identity}".encode()).hexdigest(),
                "perceptual_hash": hashlib.sha256(f"visual-{identity}".encode()).hexdigest()[:16],
                "source_hash": hashlib.sha256(f"source-{identity}".encode()).hexdigest(),
                "camera_profile": "TEMPER USB camera disposable profile",
                "reviewers": ["sim-review-a", "sim-review-b"],
                "has_person": False, "width": 1280, "height": 720,
            })
    validation = validate_inventory_dataset(manifest=dataset, assets=assets)
    conversion = plan_hailo_conversion(
        manifest=dataset, validation=validation,
        training_metrics={
            "precision": 0.97, "recall": 0.96, "count_error_rate": 0.01,
            "source_model_sha256": hashlib.sha256(b"disposable-model").hexdigest(),
        },
        toolchain={"hailo_dataflow_compiler": "simulated-3.30",
                   "hailort": "simulated-4.20", "target": "hailo8"})
    checks["inventory_requires_label_scope"] = (
        inventory_pending["state"] == "needs_declared_label_scope")
    checks["inventory_plan_becomes_ready_without_executing"] = (
        inventory_ready["state"] == "ready_for_bounded_dry_run"
        and inventory_ready["may_execute"] is False)
    checks["media_preflight_is_generic_dry_run_ready"] = (
        media_ready["state"] == "ready_for_bounded_dry_run")
    checks["pcb_inspection_stays_blocked_for_custom_model"] = (
        pcb_blocked["state"] == "blocked_custom_model_required")
    checks["all_plans_prohibit_self_approval"] = all(
        "self-approval" in plan["prohibited"]
        for plan in (inventory_pending, inventory_ready, media_ready, pcb_blocked))
    checks["simulation_has_zero_external_actions"] = True
    checks["dataset_plan_has_zero_capture_train_or_deploy"] = not any(
        dataset[key] for key in ("may_capture", "may_train", "may_deploy"))
    checks["capture_plan_has_complete_balanced_quotas"] = (
        capture["frames_planned"] == 50
        and sum(row["per_label"] for row in capture["quotas"]) == 50)
    checks["capture_planner_does_not_open_camera"] = (
        capture["may_open_camera"] is False and capture["frames_captured"] == 0)
    checks["dataset_balance_duplicate_leakage_and_provenance_pass"] = (
        validation["accepted"] is True and all(validation["checks"].values()))
    checks["accepted_dataset_still_cannot_self_start_training"] = (
        validation["may_train"] is False)
    checks["hailo_registry_candidate_passes_quality_gate"] = (
        conversion["state"] == "conversion_plan_ready"
        and conversion["quality_gate_passed"] is True)
    checks["hailo_conversion_and_deployment_remain_gated"] = not any(
        conversion[key] for key in ("may_convert", "may_register", "may_deploy"))
    return {
        "simulation": "TEMPER governed inference workflow planning",
        "passed": all(checks.values()),
        "checks": checks,
        "checks_passed": sum(checks.values()),
        "checks_total": len(checks),
        "details": {"external_actions": 0, "jobs_enqueued": 0, "frames_captured": 0,
                    "datasets_written": 0, "models_trained": 0,
                    "models_converted": 0, "models_deployed": 0,
                    "dataset_sha256": validation["dataset_sha256"],
                    "registry_record_sha256": conversion["registry_record_sha256"]},
    }
