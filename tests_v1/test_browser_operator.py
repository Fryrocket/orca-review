import sys
from pathlib import Path

import pytest

repository = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repository / "deploy" / "kiln"))
from orca_browser_operator import evaluate, waiting_report


def plan():
    return {
        "allow_external_actions": False,
        "profile": "orca-private-ephemeral",
        "tasks": [
            {"id": "read", "action": "read_page", "url": "https://example.com/", "details": {}},
            {"id": "form", "action": "prepare_form", "url": "https://example.com/contact",
             "details": {"fields": [{"name": "subject", "value": "Synthetic inquiry"}]}},
            {"id": "upload", "action": "stage_upload", "url": "https://example.com/upload",
             "details": {"path": "/home/fryrocket/ORCA Projects/demo/spec.pdf", "sha256": "a" * 64}},
        ],
    }


def test_plan_is_validated_but_never_executed():
    report = evaluate(plan(), now=1000)
    assert report["state"] == "healthy"
    assert report["mode"] == "validated_browser_plan_not_executed"
    assert len(report["plan_sha256"]) == 64
    assert report["tasks"][0]["execution"] == "private_ephemeral_browser"
    assert report["tasks"][1]["execution"] == "prepare_only_submission_prohibited"
    assert report["tasks"][2]["execution"] == "stage_only_upload_prohibited"
    assert report["external_actions"] == 0


def test_all_consequential_actions_are_gated_and_zero():
    report = evaluate(plan(), now=1000)
    assert report["approval_gates"]["purchase"] == "prohibited"
    for key in ("pages_opened", "pages_read", "downloads_started", "forms_submitted",
                "uploads_started", "purchases", "messages_sent", "publications",
                "account_changes", "credentials_read", "external_actions"):
        assert report[key] == 0


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "javascript:alert(1)", "https://user:pw@example.com/",
    "http://example.com/", "https://192.168.1.1/", "https://10.0.0.1/",
])
def test_unsafe_urls_fail_closed(url):
    value = plan()
    value["tasks"][0]["url"] = url
    with pytest.raises(ValueError):
        evaluate(value, now=1000)


def test_secrets_and_paths_outside_projects_fail_closed():
    value = plan()
    value["tasks"][1]["details"]["fields"][0]["value"] = "password=do-not-log"
    with pytest.raises(ValueError, match="secret-shaped"):
        evaluate(value, now=1000)
    value = plan()
    value["tasks"][2]["details"]["path"] = "/etc/passwd"
    with pytest.raises(ValueError, match="outside"):
        evaluate(value, now=1000)


def test_external_permission_and_unapproved_profile_fail_closed():
    value = plan()
    value["allow_external_actions"] = True
    with pytest.raises(ValueError, match="external-action"):
        evaluate(value, now=1000)
    value = plan()
    value["profile"] = "default-signed-in-profile"
    with pytest.raises(ValueError, match="unapproved"):
        evaluate(value, now=1000)


def test_waiting_state_is_truthful_and_inert():
    report = waiting_report(now=1000)
    assert report["state"] == "healthy"
    assert report["mode"] == "waiting_for_approved_browser_plan"
    assert report["tasks"] == []
    assert report["external_actions"] == 0


def test_role_is_active_after_private_page_controller_acceptance():
    from orca.roles import ROLE_CATALOG

    role = ROLE_CATALOG["browser_operator"]
    assert role.active is True
    assert role.activation_gate == "private_ephemeral_page_read_and_action_boundary_accepted_20261001"
    assert {"purchase", "submit_form", "send_message", "publish", "change_account",
            "read_password", "approve"} <= set(role.prohibited)
