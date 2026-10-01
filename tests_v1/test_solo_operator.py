import pytest

from orca.solo_operator import (
    build_action_plan, build_operating_snapshot, solo_operator_blueprint,
)


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
    assert all(item["state"] == "implemented_candidate" for item in result["modules"])
    assert any("awaiting" in item["mode"] for item in result["modules"])


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


def record(record_id, module, *, priority="normal", due_at=None,
           approval=False, untrusted=False, related_ids=None, status="open"):
    return {
        "record_id": record_id, "module": module,
        "title": f"Review {record_id}", "status": status,
        "priority": priority, "owner": "orca", "due_at": due_at,
        "source": "simulation", "evidence": f"fixture:{record_id}",
        "related_ids": related_ids or [],
        "approval_required": approval, "untrusted": untrusted,
    }


def test_operating_snapshot_projects_every_room_without_side_effects():
    modules = [
        "relationship_master", "knowledge_center", "case_manager",
        "attachment_quarantine", "commitment_manager", "identity_consent",
        "dead_letter", "business_memory", "decision_journal",
        "performance_optimizer",
    ]
    records = [record(f"rec-{index}", module) for index, module in enumerate(modules)]
    records[0]["related_ids"] = ["rec-1"]
    records[3]["untrusted"] = True
    records[4]["due_at"] = "2026-10-02T10:00:00Z"
    records[5]["approval_required"] = True
    records[6]["status"] = "failed"
    first = build_operating_snapshot(records)
    replay = build_operating_snapshot(records)
    assert first == replay
    assert first["room_count"] == 12
    assert set(first["rooms"]) == {
        "action_center", "relationship_master", "knowledge_center", "case_manager",
        "attachment_quarantine", "commitment_manager", "identity_consent",
        "dead_letter", "business_memory", "decision_journal",
        "performance_optimizer", "executive_brief",
    }
    assert first["rooms"]["attachment_quarantine"][0]["record_id"] == "rec-3"
    assert first["rooms"]["business_memory"]["edges"] == [{"from": "rec-0", "to": "rec-1"}]
    assert first["rooms"]["executive_brief"]["top_actions"]
    assert first["external_actions"] == first["connector_reads"] == 0
    assert first["records_mutated"] == first["messages_sent"] == 0
    assert first["calendar_writes"] == first["jobs_replayed"] == 0


def test_operating_snapshot_deduplicates_and_fails_closed():
    one = record("record-1", "knowledge_center")
    result = build_operating_snapshot([one, one])
    assert result["records"] == 1
    assert result["duplicates_removed"] == 1
    conflict = dict(one); conflict["title"] = "Changed"
    with pytest.raises(ValueError, match="conflicting"):
        build_operating_snapshot([one, conflict])
    secret = record("record-2", "decision_journal")
    secret["evidence"] = "password=super-secret-value"
    with pytest.raises(ValueError, match="secret-shaped"):
        build_operating_snapshot([secret])
    invalid = record("record-3", "action_center")
    with pytest.raises(ValueError, match="source module"):
        build_operating_snapshot([invalid])
