import pytest

from orca.inbox import InboxStore


def message(reference="mail-1"):
    return {
        "message_reference": reference,
        "sender_display": "Example Vendor",
        "subject": "Invoice question",
        "received_at": "2026-10-01T12:00:00Z",
        "project_or_customer": "QuasarVolt",
        "category": "invoice",
        "priority": "normal",
        "summary": "The vendor asked which purchase order applies.",
        "follow_up": "Confirm the purchase order after review.",
        "deadline": None,
        "draft_reply": "Draft: Thanks. I will confirm the purchase order.",
        "uncertainty": "Purchase order is not present in the message summary.",
    }


def packet(*messages, request_id="request-0001"):
    return {"request_id": request_id, "handoff_id": "muse-email-abc123",
            "messages": list(messages)}


def test_inbox_import_is_idempotent_private_and_read_only():
    store = InboxStore(":memory:")
    first = store.import_packet(packet(message()))
    replay = store.import_packet(packet(message()))
    assert first == replay
    snapshot = store.snapshot()
    assert snapshot["status"] == "ready"
    assert snapshot["count"] == 1
    assert snapshot["read_only"] is True
    assert snapshot["raw_bodies_stored"] is False
    assert snapshot["attachments_stored"] is False
    assert snapshot["mailbox_mutations"] == 0
    assert "password" not in str(snapshot).lower()


def test_inbox_rejects_conflicts_duplicates_secrets_and_bad_enums():
    store = InboxStore(":memory:")
    store.import_packet(packet(message()))
    changed = message(); changed["summary"] = "Changed under the same reference."
    with pytest.raises(ValueError, match="request ID"):
        store.import_packet(packet(changed))
    with pytest.raises(ValueError, match="duplicate"):
        store.import_packet(packet(message("mail-2"), message("mail-2"), request_id="request-0002"))
    secret = message("mail-3"); secret["summary"] = "api_key=sk-abcdefghijklmnop"
    with pytest.raises(ValueError, match="secret-shaped"):
        store.import_packet(packet(secret, request_id="request-0003"))
    invalid = message("mail-4"); invalid["priority"] = "critical"
    with pytest.raises(ValueError, match="category or priority"):
        store.import_packet(packet(invalid, request_id="request-0004"))


def test_inbox_message_reference_cannot_be_rewritten_by_later_import():
    store = InboxStore(":memory:")
    store.import_packet(packet(message(), request_id="request-0001"))
    changed = message(); changed["subject"] = "A different subject"
    with pytest.raises(ValueError, match="changed under"):
        store.import_packet(packet(changed, request_id="request-0002"))
