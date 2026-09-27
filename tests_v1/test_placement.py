import pytest

from orca.control_plane import ControlPlane
from orca.placement import recommend_placement
from orca.registry import NODES


def test_verified_three_host_profiles_match_intended_roles():
    assert NODES["anvil"].cpu == "Apple M4 (10 cores)"
    assert NODES["anvil"].memory_gib == 16
    assert "development" in NODES["anvil"].capabilities

    assert NODES["kiln"].gpu == "BILLOWS — NVIDIA GeForce GTX 1660 Ti"
    assert NODES["kiln"].gpu_vram_gib == 6
    assert "small_inference" in NODES["kiln"].capabilities

    assert NODES["forge"].cpu_threads == 32
    assert NODES["forge"].memory_gib == 62
    assert "AMD Radeon AI PRO R9700" in NODES["forge"].gpu
    assert NODES["forge"].gpu_vram_gib == 32
    assert NODES["forge"].planned_gpu is None
    assert NODES["forge"].planned_gpu_name is None
    assert "gpu_compute_rocm" in NODES["forge"].capabilities
    assert "control_plane" in NODES["forge"].capabilities
    assert "large_cpu_inference" in NODES["forge"].capabilities
    assert "large_gpu_inference" not in NODES["forge"].capabilities

    assert "BILLOWS" in NODES["kiln"].gpu

    assert NODES["ember"].cpu_threads == 4
    assert NODES["ember"].memory_gib == 8
    assert "ups_watch" in NODES["ember"].capabilities


@pytest.mark.parametrize(
    ("workload", "node_id"),
    [
        ("operator_interactive", "anvil"),
        ("development", "anvil"),
        ("control_plane", "forge"),
        ("cpu_batch", "forge"),
        ("build_ci", "forge"),
        ("durable_storage", "forge"),
        ("model_storage", "forge"),
        ("document_ingest", "forge"),
        ("fast_interactive_inference", "anvil"),
        ("small_inference", "kiln"),
        ("embeddings", "forge"),
        ("local_review", "kiln"),
        ("large_inference", "forge"),
        ("monitoring", "ember"),
        ("ups_watch", "ember"),
        ("backup_observer", "ember"),
    ],
)
def test_static_placement_recommends_hardware_appropriate_node(workload, node_id):
    recommendation = recommend_placement(workload)
    assert recommendation["status"] == "recommended"
    assert recommendation["selected_node"] == node_id
    assert recommendation["remote_execution_enabled"] is False


def test_large_cpu_inference_uses_forge_while_large_gpu_remains_blocked():
    recommendation = recommend_placement("large_inference")
    assert recommendation["status"] == "recommended"
    assert recommendation["selected_node"] == "forge"
    assert "30.5B" in recommendation["reason"]

    recommendation = recommend_placement("large_gpu_inference")
    assert recommendation["status"] == "blocked"
    assert recommendation["selected_node"] is None
    assert "CRUCIBLE" in recommendation["reason"]
    assert recommendation["candidates"][0]["missing_capabilities"] == ["large_gpu_inference"]


def test_live_recommendation_requires_authenticated_healthy_node():
    health = {node_id: {"state": "unproven"} for node_id in NODES}
    assert recommend_placement("small_inference", health)["status"] == "blocked"
    health["kiln"] = {"state": "healthy"}
    assert recommend_placement("small_inference", health)["selected_node"] == "kiln"


def test_control_plane_snapshot_exposes_advisory_placement_only():
    state = ControlPlane().snapshot()
    assert state["placement"]["automatic_execution"] is False
    assert state["placement"]["workloads"]["control_plane"]["status"] == "blocked"
    assert all(not node["remote_execution_enabled"] for node in state["nodes"])


def test_unknown_workload_fails_closed():
    with pytest.raises(ValueError, match="unknown workload"):
        recommend_placement("surprise")
