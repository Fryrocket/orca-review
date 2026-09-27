from orca.control_plane import ControlPlane
from orca.bots import BOT_PROGRAMS, CORE_BOTS, validate_bot_programs
from orca.roles import ROLE_CATALOG, validate_role_catalog


def test_complete_role_catalog_is_valid_and_visible():
    validate_role_catalog()
    roles = {role["id"]: role for role in ControlPlane().snapshot()["role_catalog"]}
    assert set(roles) == set(ROLE_CATALOG)
    assert {"orca", "smith", "qwen_conversation", "quench", "security_gate"} <= set(roles)
    assert {"anvil_reflex", "forge_retrieval", "ember_sentinel"} <= set(roles)
    assert {"ampere", "relay", "iris", "heartbeat_agents", "fry"} <= set(roles)


def test_author_review_and_human_authority_stay_separate():
    smith, quench = ROLE_CATALOG["smith"], ROLE_CATALOG["quench"]
    assert smith.node_id == "forge" and quench.node_id == "kiln"
    assert "author" in smith.authority and "review" in quench.authority
    assert "approve_r3" not in ROLE_CATALOG["orca"].authority
    assert "approve_r3" in ROLE_CATALOG["fry"].authority


def test_models_and_retrieval_are_services_not_agents():
    for role_id in ("qwen_conversation", "anvil_reflex", "forge_retrieval"):
        role = ROLE_CATALOG[role_id]
        assert not ({"author", "approve", "deploy"} & set(role.authority))
        assert role.active is False
    assert "act_as_agent" in ROLE_CATALOG["qwen_conversation"].prohibited


def test_candidates_and_iris_remain_inactive_and_lane_bounded():
    assert all(not ROLE_CATALOG[x].active for x in ("ampere", "relay", "iris"))
    assert ROLE_CATALOG["iris"].lanes == ("bgm",)
    assert "body_action_without_r3" in ROLE_CATALOG["iris"].prohibited


def test_every_core_bot_has_a_bounded_program_and_handoff():
    validate_bot_programs()
    assert set(BOT_PROGRAMS) == set(CORE_BOTS)
    assert "approving R3 work" in BOT_PROGRAMS["orca"].refusals
    assert "self-review" in BOT_PROGRAMS["smith"].refusals
    assert "authoring reviewed changes" in BOT_PROGRAMS["quench"].refusals
    assert BOT_PROGRAMS["security_gate"].tools == ()
    assert all(program.handoff for program in BOT_PROGRAMS.values())
