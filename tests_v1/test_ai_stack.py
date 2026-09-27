from orca.ai_stack import AI_LADDERS, AI_SERVICES, ladder_snapshot, validate_ai_stack
from orca.control_plane import ControlPlane
from orca.models import DEFAULT_ROUTES
from orca.registry import NODES


def test_four_host_stack_matches_live_hardware_and_one_mind_topology():
    validate_ai_stack()
    snapshot = ladder_snapshot()
    fabric = snapshot["fabric"]
    assert fabric["identity"] == "one ORCA mind with specialized execution surfaces"
    assert fabric["authoritative_writer"] == "forge"
    assert fabric["shared_memory_owner"] == "forge"
    assert fabric["operator_surface"] == "anvil"
    assert fabric["independent_review_surface"] == "kiln"
    assert fabric["sentinel_surface"] == "ember"
    assert fabric["memory_pooling"] is False
    assert fabric["automatic_execution"] is False


def test_smith_moves_to_forge_and_quench_keeps_kiln_gpu_exclusivity():
    smith = AI_SERVICES["forge_smith"]
    quench = AI_SERVICES["kiln_quench"]
    assert smith.node_id == "forge"
    assert smith.model == "Qwen3-Coder-30B-A3B-Instruct-Q4_K_M"
    assert smith.accelerator == "CPU / AVX2"
    assert smith.ram_budget_gib == 28
    assert smith.may_author is True

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


def test_deepseek_is_a_bounded_crucible_reasoner_not_an_author_or_reviewer():
    deepseek = AI_SERVICES["forge_deepseek"]
    assert deepseek.node_id == "forge"
    assert deepseek.model == "DeepSeek-R1-Distill-Qwen-32B-Q4_K_M"
    assert deepseek.accelerator == "CRUCIBLE / AMD ROCm"
    assert deepseek.vram_budget_gib == 24
    assert deepseek.may_author is False
    assert deepseek.may_review is False
    assert deepseek.runtime_enabled is False


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
    assert AI_LADDERS["interactive"] == ("anvil_reflex", "forge_deepseek", "forge_smith", "fry")
    assert AI_LADDERS["coding"] == ("forge_deepseek", "forge_smith", "kiln_quench", "fry")
    assert AI_LADDERS["review"] == ("kiln_quench", "fry")
    assert AI_LADDERS["monitoring"][:2] == ("ember_sentinel", "forge_policy")
    assert AI_LADDERS["large_gpu_inference"] == ("forge_deepseek", "forge_crucible", "fry")


def test_default_model_routes_point_to_hardware_aware_services():
    assert DEFAULT_ROUTES["coding"].primary == "forge_smith"
    assert DEFAULT_ROUTES["review"].primary == "kiln_quench"
    assert DEFAULT_ROUTES["monitoring"].primary == "ember_sentinel"
    assert DEFAULT_ROUTES["embeddings"].primary == "forge_embeddings"
    assert all(route.monthly_hard_cap_usd == 0 for route in DEFAULT_ROUTES.values())


def test_control_plane_exposes_stack_without_enabling_model_calls():
    stack = ControlPlane().snapshot()["ai_stack"]
    assert stack["model_invocation_enabled"] is False
    assert all(
        not service["runtime_enabled"]
        for service in stack["services"].values()
    )
    assert stack["ladders"]["coding"][0]["service_id"] == "forge_deepseek"
    assert stack["ladders"]["coding"][1]["service_id"] == "forge_smith"
    assert stack["ladders"]["review"][0]["node_id"] == "kiln"
    assert stack["crucible_acceptance"]["status"] == "blocked"
    assert stack["crucible_acceptance"]["runtime_enabled"] is False
