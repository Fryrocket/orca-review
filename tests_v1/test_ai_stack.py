from orca.ai_stack import AI_LADDERS, AI_SERVICES, ladder_snapshot, validate_ai_stack
from orca.control_plane import ControlPlane
from orca.models import DEFAULT_ROUTES
from orca.registry import NODES
from orca.crucible import CrucibleAcceptance
from dataclasses import asdict
import json


def test_four_host_stack_matches_live_hardware_and_one_mind_topology():
    validate_ai_stack()
    snapshot = ladder_snapshot()
    fabric = snapshot["fabric"]
    assert fabric["identity"] == "one ORCA mind with specialized execution surfaces"
    assert "never overrides Fry" in fabric["executive_orchestrator"]
    assert fabric["authoritative_writer"] == "forge"
    assert fabric["shared_memory_owner"] == "forge"
    assert fabric["operator_surface"] == "anvil"
    assert fabric["independent_review_surface"] == "kiln"
    assert fabric["sentinel_surface"] == "ember"
    assert fabric["memory_pooling"] is False
    assert fabric["automatic_execution"] is False


def test_smith_is_retired_and_quench_keeps_kiln_gpu_exclusivity():
    smith = AI_SERVICES["forge_smith"]
    quench = AI_SERVICES["kiln_quench"]
    assert smith.node_id == "forge"
    assert smith.model == "Qwen3-Coder-30B-A3B-Instruct-Q4_K_M"
    assert smith.accelerator == "CPU / AVX2"
    assert smith.ram_budget_gib == 28
    assert smith.may_author is False
    assert smith.deployment_state == "retired_stopped"

    assert quench.node_id == "kiln"
    assert quench.accelerator == "CUDA"
    assert quench.vram_budget_gib == 5
    assert quench.may_review is True
    assert smith.node_id != quench.node_id


def test_anvil_is_fast_reflex_and_ember_has_no_generative_model():
    assert AI_SERVICES["anvil_reflex"].model == "llama3.2:3b"
    assert AI_SERVICES["anvil_reflex"].node_id == "anvil"
    assert AI_SERVICES["ember_sentinel"].model == "deterministic rules only"
    assert AI_SERVICES["ember_sentinel"].node_id == "ember"


def test_qwen_is_a_bounded_crucible_reasoner_not_an_author_or_reviewer():
    qwen = AI_SERVICES["forge_qwen"]
    assert qwen.node_id == "forge"
    assert qwen.model == "Qwen3.5-35B-A3B-Q4_K_M"
    assert qwen.accelerator == "CRUCIBLE / AMD ROCm"
    assert qwen.vram_budget_gib == 24
    assert qwen.may_author is False
    assert qwen.may_review is False
    assert qwen.runtime_enabled is False


def test_temper_edge_camera_is_live_but_autonomous_invocation_stays_gated():
    temper = AI_SERVICES["temper_edge"]
    assert temper.node_id == "temper"
    assert temper.backend == "HailoRT"
    assert temper.deployment_state == "broker_live_camera_and_file_accepted_custom_gated"
    assert temper.runtime_enabled is False
    assert "approved-file pipelines accepted" in temper.model
    assert AI_LADDERS["edge_inference"] == (
        "temper_edge", "forge_qwen", "kiln_quench", "fry")


def test_concurrent_ai_service_budgets_do_not_overcommit_hosts():
    for node_id, node in NODES.items():
        if node.memory_gib is None:
            continue
        active = [
            service for service in AI_SERVICES.values()
            if service.node_id == node_id
            and service.deployment_state != "blocked_hardware"
        ]
        assert sum(service.ram_budget_gib for service in active) <= node.memory_gib
        assert sum(service.vram_budget_gib for service in active) <= (
            node.gpu_vram_gib or 0)


def test_ladders_escalate_to_deeper_reasoning_then_independent_review():
    assert AI_LADDERS["interactive"] == ("kiln_codex", "gemini_free", "forge_qwen", "fry")
    assert AI_LADDERS["coding"] == ("kiln_codex", "gemini_free", "forge_qwen", "kiln_quench", "fry")
    assert AI_LADDERS["review"] == ("kiln_quench", "fry")
    assert AI_LADDERS["monitoring"][:2] == ("ember_sentinel", "forge_policy")
    assert AI_LADDERS["large_gpu_inference"] == ("forge_qwen", "forge_crucible", "fry")


def test_default_model_routes_point_to_hardware_aware_services():
    assert DEFAULT_ROUTES["coding"].primary == "kiln_codex"
    assert DEFAULT_ROUTES["coding"].fallback == "forge_qwen"
    assert DEFAULT_ROUTES["review"].primary == "kiln_quench"
    assert DEFAULT_ROUTES["monitoring"].primary == "ember_sentinel"
    assert DEFAULT_ROUTES["embeddings"].primary == "forge_embeddings"
    assert DEFAULT_ROUTES["documentation"].primary == "kiln_codex"
    assert DEFAULT_ROUTES["large_inference"].primary == "forge_qwen"
    assert all(route.monthly_hard_cap_usd == 0 for route in DEFAULT_ROUTES.values())


def test_control_plane_exposes_stack_without_enabling_model_calls():
    stack = ControlPlane().snapshot()["ai_stack"]
    assert stack["model_invocation_enabled"] is False
    assert all(
        not service["runtime_enabled"]
        for service in stack["services"].values()
    )
    assert stack["ladders"]["coding"][0]["service_id"] == "kiln_codex"
    assert stack["ladders"]["coding"][1]["service_id"] == "gemini_free"
    assert stack["ladders"]["coding"][2]["service_id"] == "forge_qwen"
    assert stack["ladders"]["review"][0]["node_id"] == "kiln"
    assert stack["crucible_acceptance"]["status"] == "blocked"
    assert stack["crucible_acceptance"]["runtime_enabled"] is False


def test_runtime_activation_is_explicit_and_crucible_evidence_gated(
        monkeypatch, tmp_path):
    evidence = CrucibleAcceptance(
        model_id="qwen", model_sha256="a" * 64,
        runtime_id="llama.cpp", runtime_sha256="b" * 64,
        loopback_only=True, tool_calls_disabled=True, bounded_context=True,
        post_reboot_model_test=True, sustained_load_test=True,
        orca_responsiveness_test=True, rollback_test=True,
        quench_review_id="review-1", fry_activation_id="decision-1",
    )
    path = tmp_path / "acceptance.json"
    path.write_text(json.dumps(asdict(evidence)))
    monkeypatch.setenv("ORCA_CRUCIBLE_ACCEPTANCE_FILE", str(path))
    monkeypatch.setenv(
        "ORCA_ENABLED_MODEL_SERVICES", "forge_qwen,gemini_free,kiln_quench")
    stack = ladder_snapshot()
    assert stack["model_invocation_enabled"] is True
    assert stack["crucible_acceptance"]["activation_ready"] is True
    assert stack["crucible_acceptance"]["status"] == "accepted_enabled"
    assert stack["crucible_acceptance"]["runtime_enabled"] is True
    assert stack["services"]["forge_qwen"]["runtime_enabled"] is True
    assert stack["services"]["gemini_free"]["runtime_enabled"] is True
    assert stack["services"]["kiln_quench"]["runtime_enabled"] is True
    bots = {row["id"]: row for row in ControlPlane().snapshot()["bots"]}
    assert bots["chatgpt"]["runtime_enabled"] is False
    assert all(bot["runtime_enabled"] for bot_id, bot in bots.items()
               if bot_id != "chatgpt")

    path.write_text("{}")
    stack = ladder_snapshot()
    assert stack["services"]["forge_qwen"]["runtime_enabled"] is False
    assert stack["services"]["gemini_free"]["runtime_enabled"] is True
