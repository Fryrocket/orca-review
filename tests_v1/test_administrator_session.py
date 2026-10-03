from pathlib import Path

import pytest

from orca.administrator_session import AdministratorSessionStore, administrator_turn


class ContextGateway:
    def __init__(self):
        self.calls = []

    def invoke(self, **payload):
        self.calls.append(payload)
        prior = " ".join(item["content"] for item in payload["history"])
        return {"summary": "Cedar" if "Cedar" in prior else "I am ready to help.",
                "evidence": ["conversation"], "uncertainty": "none", "next_gate": "none"}


def test_persistent_multiturn_context_and_reconnect(tmp_path):
    store = AdministratorSessionStore(tmp_path)
    session = store.create()
    gateway = ContextGateway()
    administrator_turn(store, gateway, tmp_path, session["session_id"], "My project is Cedar.")
    result = administrator_turn(store, gateway, tmp_path, session["session_id"], "What is its name?")
    assert result["messages"][-1]["content"] == "Cedar"
    assert gateway.calls[-1]["service_id"] == "kiln_codex"
    assert any(message["content"] == "My project is Cedar."
               for message in gateway.calls[-1]["history"])
    reopened = AdministratorSessionStore(tmp_path).read(session["session_id"])
    assert reopened == result
    assert AdministratorSessionStore(tmp_path).list()[0]["session_id"] == session["session_id"]


def test_model_unavailability_is_an_honest_blocker(tmp_path):
    class Unavailable:
        def invoke(self, **_payload):
            raise RuntimeError("offline")

    store = AdministratorSessionStore(tmp_path)
    session = store.create()
    result = administrator_turn(store, Unavailable(), tmp_path, session["session_id"], "How are you?")
    assert result["state"] == "blocked"
    assert "No tool ran and no success was recorded" in result["messages"][-1]["content"]


def test_governed_tool_call_records_validated_result(monkeypatch, tmp_path):
    from orca import administrator_session

    run = {"run_id": "eng_20261003T120000Z_abcdef123456", "state": "blocked",
           "iteration": 1, "blockers": ["physical fit"], "artifacts": [
               {"kind": "package", "href": "/verified.zip", "sha256": "a" * 64}],
           "rollback": {"state": "preserved", "activation": "not_requested"}}
    calls = []
    monkeypatch.setattr(administrator_session, "run_acceptance",
                        lambda prompt, root: calls.append((prompt, root)) or run)
    store = AdministratorSessionStore(tmp_path)
    session = store.create()
    result = administrator_turn(store, None, tmp_path, session["session_id"],
                                "Run the Pi 5 HAT acceptance tests.")
    assert len(calls) == 1
    assert result["active_run_id"] == run["run_id"]
    assert [message["role"] for message in result["messages"]] == [
        "user", "activity", "tool", "tool", "assistant"]
    assert result["messages"][-2]["tool_result"]["artifacts"][0]["sha256"] == "a" * 64
    assert result["state"] == "blocked"


def test_permission_isolation_secrets_and_invalid_sessions_fail_closed(tmp_path):
    store = AdministratorSessionStore(tmp_path)
    session = store.create()
    with pytest.raises(ValueError, match="secret-shaped"):
        administrator_turn(store, ContextGateway(), tmp_path, session["session_id"],
                           "Use token sk-abcdefghijklmnopqrstuvwxyz123456 now")
    with pytest.raises(ValueError, match="session id"):
        store.read("../../ordinary-orca")
    source = Path("orca/administrator_session.py").read_text(encoding="utf-8")
    assert "administrator.acceptance.run" in source
    assert "shell" not in source


def test_cancel_and_resume_are_durable(tmp_path):
    store = AdministratorSessionStore(tmp_path)
    session = store.create()
    cancelled = store.cancel(session["session_id"])
    assert cancelled["state"] == "cancelled" and cancelled["cancel_requested"] is True
    resumed = administrator_turn(store, ContextGateway(), tmp_path, session["session_id"], "Hello")
    assert resumed["state"] == "idle" and resumed["cancel_requested"] is False


def test_administrator_ui_is_conversational_and_evidence_is_expandable():
    html = Path("orca/static/index.html").read_text(encoding="utf-8")
    script = Path("orca/static/app.js").read_text(encoding="utf-8")
    assert 'id="administrator-conversation"' in html
    assert '<details class="administrator-evidence"' in html
    assert 'id="administrator-cancel"' in html
    assert "renderAdministratorSession" in script
    assert "orca-administrator-session-v1" in script
