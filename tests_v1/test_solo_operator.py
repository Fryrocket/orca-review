import pytest

from orca.solo_operator import build_action_plan, solo_operator_blueprint


def signal(source_id="source-1", *, priority="normal", due_at=None,
           kind="follow_up", approval=False):
    return {
        "source_id": source_id, "source": "communications",
        "kind": kind, "summary": f"Review {source_id}",
        "priority": priority, "due_at": due_at,
        "workspace": "business", "owner": "orca",
        "evidence": f"evidence:{source_id}", "approval_required": approval,
    }


def test_solo_operator_registers_all_twelve_control_rooms_truthfully():
    result = solo_operator_blueprint()
    assert result["module_count"] == 12
    assert result["current_front_door"] == "action_center"
    assert result["external_actions"] == 0
    assert {item["id"] for item in result["modules"]} == {
        "action_center", "relationship_master", "knowledge_center", "case_manager",
        "attachment_quarantine", "commitment_manager", "identity_consent",
        "dead_letter", "business_memory", "decision_journal",
        "performance_optimizer", "executive_brief",
    }
    assert any(item["state"] == "staged" for item in result["modules"])


def test_action_center_deduplicates_sorts_and_never_executes():
    normal = signal("normal-1")
    urgent = signal("urgent-1", priority="urgent", due_at="2026-10-02T10:00:00Z",
                    kind="approval", approval=True)
    first = build_action_plan([normal, urgent, normal])
    replay = build_action_plan([normal, urgent, normal])
    assert first == replay
    assert first["items"][0]["source_id"] == "urgent-1"
    assert first["count"] == 2
    assert first["duplicates_removed"] == 1
    assert first["approvals"] == 1
    assert first["state"] == "owner_review_required"
    assert first["external_actions"] == first["jobs_created"] == first["records_mutated"] == 0


def test_action_center_fails_closed_on_conflict_secret_and_bad_schema():
    one = signal("same")
    changed = signal("same"); changed["summary"] = "Changed"
    with pytest.raises(ValueError, match="conflicting"):
        build_action_plan([one, changed])
    secret = signal("secret"); secret["summary"] = "api_key=sk-abcdefghijklmnop"
    with pytest.raises(ValueError, match="secret-shaped"):
        build_action_plan([secret])
    with pytest.raises(ValueError, match="invalid schema"):
        build_action_plan([{"source_id": "incomplete"}])


def test_empty_action_center_is_clear():
    result = build_action_plan([])
    assert result["state"] == "clear"
    assert result["count"] == 0
