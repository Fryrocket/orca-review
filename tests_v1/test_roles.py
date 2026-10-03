from orca.control_plane import ControlPlane
from orca.bots import BOT_PROGRAMS, CORE_BOTS, validate_bot_programs
from orca.roles import ROLE_CATALOG, validate_role_catalog


def test_complete_role_catalog_is_valid_and_visible():
    validate_role_catalog()
    roles = {role["id"]: role for role in ControlPlane().snapshot()["role_catalog"]}
    assert set(roles) == set(ROLE_CATALOG) - {"smith"}
    assert {"orca", "gemini", "qwen_conversation", "quench", "security_gate"} <= set(roles)
    assert "smith" not in roles
    assert all("smith" not in role["receives_from"] for role in roles.values())
    assert all("smith" not in role["hands_off_to"] for role in roles.values())
    assert {"anvil_reflex", "forge_retrieval", "ember_sentinel"} <= set(roles)
    assert {"ampere", "relay", "temper", "heartbeat_agents", "fry"} <= set(roles)


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


def test_candidates_and_temper_workloads_remain_inactive_and_lane_bounded():
    assert all(not ROLE_CATALOG[x].active for x in ("ampere", "relay", "temper"))
    assert ROLE_CATALOG["temper"].lanes == ("forge", "bgm")
    assert "body_action_without_r3" in ROLE_CATALOG["temper"].prohibited


def test_solo_operator_bot_crew_is_registered_gated_and_non_authoritative():
    crew = (
        "reliability_sentinel", "recovery_marshal", "connector_steward",
        "evidence_auditor", "security_watch", "budget_officer",
        "legal_compliance_clerk", "inventory_steward", "product_scout",
        "product_development_lead", "channel_operator", "creative_director",
        "temper_watch", "browser_operator", "daily_briefing_officer",
        "continuity_keeper",
    )
    assert all(role_id in ROLE_CATALOG for role_id in crew)
    assert ROLE_CATALOG["reliability_sentinel"].active
    assert ROLE_CATALOG["recovery_marshal"].active
    assert ROLE_CATALOG["connector_steward"].active
    assert ROLE_CATALOG["evidence_auditor"].active
    assert ROLE_CATALOG["security_watch"].active
    assert ROLE_CATALOG["budget_officer"].active
    assert ROLE_CATALOG["legal_compliance_clerk"].active
    assert ROLE_CATALOG["inventory_steward"].active
    assert ROLE_CATALOG["product_scout"].active
    assert ROLE_CATALOG["product_development_lead"].active
    assert ROLE_CATALOG["channel_operator"].active
    assert ROLE_CATALOG["creative_director"].active
    assert ROLE_CATALOG["browser_operator"].active
    assert ROLE_CATALOG["daily_briefing_officer"].active
    assert all(not ROLE_CATALOG[role_id].active for role_id in crew
               if role_id not in {"reliability_sentinel", "recovery_marshal", "connector_steward", "evidence_auditor", "security_watch", "budget_officer", "legal_compliance_clerk", "inventory_steward", "product_scout", "product_development_lead", "channel_operator", "creative_director", "browser_operator", "daily_briefing_officer"})
    for role_id in crew:
        role = ROLE_CATALOG[role_id]
        assert not ({"approve_r3", "deploy"} & set(role.authority))
        assert role.activation_gate
    assert "move_money" in ROLE_CATALOG["budget_officer"].prohibited
    assert "delete_backup" in ROLE_CATALOG["recovery_marshal"].prohibited
    assert "restart_service" in ROLE_CATALOG["reliability_sentinel"].prohibited
    assert "publish" in ROLE_CATALOG["channel_operator"].prohibited
    assert ROLE_CATALOG["temper_watch"].lanes == ("forge", "bgm")


def test_every_core_bot_has_a_bounded_program_and_handoff():
    validate_bot_programs()
    assert set(BOT_PROGRAMS) == set(CORE_BOTS) | {"smith"}
    assert BOT_PROGRAMS["chatgpt"].tools == ()
    assert "do not claim to be ORCA" in BOT_PROGRAMS["chatgpt"].mission
    assert "approving R3 work" in BOT_PROGRAMS["orca"].refusals
    assert "smith" not in CORE_BOTS
    assert BOT_PROGRAMS["smith"].version == "retired-compatibility"
    assert BOT_PROGRAMS["gemini"].tools == ()
    assert "private-data access" in BOT_PROGRAMS["gemini"].refusals
    assert "authoring reviewed changes" in BOT_PROGRAMS["quench"].refusals
    assert BOT_PROGRAMS["security_gate"].tools == ()
    assert all(program.handoff for program in BOT_PROGRAMS.values())
