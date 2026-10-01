from orca.communications import build_communications_snapshot


def message(reference, *, association="QuasarVolt", category="vendor",
            priority="normal", follow_up="none", deadline=None, uncertainty="none"):
    return {
        "message_reference": reference,
        "sender_display": "Example Sender",
        "subject": f"Subject {reference}",
        "received_at": f"2026-10-01T12:0{reference[-1]}:00Z",
        "project_or_customer": association,
        "category": category,
        "priority": priority,
        "summary": "Minimal summary.",
        "follow_up": follow_up,
        "deadline": deadline,
        "draft_reply": None,
        "uncertainty": uncertainty,
        "handoff_id": "muse-email-example",
        "imported_at": "2026-10-01 12:00:00",
    }


def test_communications_builds_tasks_timelines_calendar_quarantine_and_brief():
    result = build_communications_snapshot([
        message("mail-1", priority="high", follow_up="Confirm availability.",
                deadline="2026-10-03T17:00:00Z"),
        message("mail-2", association="Customer A", category="support"),
        message("mail-3", category="spam", uncertainty="Suspicious unknown link."),
    ])
    assert result["counts"] == {
        "messages": 3, "follow_ups": 1, "deadlines": 1,
        "relationships": 2, "quarantined": 1, "urgent": 0,
    }
    assert result["tasks"][0]["state"] == "owner_review_required"
    assert result["calendar_candidates"][0]["state"] == "candidate_only"
    assert result["quarantine"][0]["message_reference"] == "mail-3"
    assert result["daily_brief"]["external_actions"] == 0
    assert all(value == 0 for key, value in result["controls"].items()
               if key != "approval_required_for_external_action")
    assert result["controls"]["approval_required_for_external_action"] is True


def test_communications_empty_state_is_truthful_and_inert():
    result = build_communications_snapshot([])
    assert result["status"] == "waiting_for_authorized_mail_summary"
    assert result["counts"]["messages"] == 0
    assert result["mode"] == "read_only_owner_review"
