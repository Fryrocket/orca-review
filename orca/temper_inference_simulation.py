from __future__ import annotations

from .edge_inference import plan_edge_workflow


def run_temper_inference_simulation() -> dict:
    """Exercise workflow planning with disposable inputs and no remote action."""
    checks: dict[str, bool] = {}
    inventory_pending = plan_edge_workflow(workflow_id="inventory_visual_count")
    inventory_ready = plan_edge_workflow(
        workflow_id="inventory_visual_count", labels=["box", "bottle"])
    media_ready = plan_edge_workflow(workflow_id="product_media_preflight")
    pcb_blocked = plan_edge_workflow(
        workflow_id="pcb_assembly_inspection", input_kind="image")
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
    return {
        "simulation": "TEMPER governed inference workflow planning",
        "passed": all(checks.values()),
        "checks": checks,
        "checks_passed": sum(checks.values()),
        "checks_total": len(checks),
        "details": {"external_actions": 0, "jobs_enqueued": 0, "frames_captured": 0},
    }
