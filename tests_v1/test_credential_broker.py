import pytest

from orca.credential_broker import plan_credential_use


RULE = {"reference": "kiln.drive", "caller": "connector_steward",
        "service": "drive", "account": "quasarvolt", "host": "kiln",
        "actions": ["read_connector"]}


def test_exact_read_only_reference_is_preauthorized_without_secret_material():
    result = plan_credential_use(
        reference="kiln.drive", caller="connector_steward", service="drive",
        account="quasarvolt", purpose="read connector health", host="kiln",
        action_class="read_connector", allowed=[RULE])
    assert result["approved"] is True
    assert result["secret_present"] is False
    assert result["may_enumerate_keychain"] is False


@pytest.mark.parametrize("action", [
    "new_credential", "expand_scope", "export", "recover", "rotate", "delete",
    "move_money", "legal_acceptance", "publish", "security_change", "account_change",
])
def test_sensitive_actions_always_require_authenticated_owner(action):
    result = plan_credential_use(
        reference="kiln.drive", caller="connector_steward", service="drive",
        account="quasarvolt", purpose="sensitive fixture", host="kiln",
        action_class=action, allowed=[{**RULE, "actions": [action]}])
    assert result["approved"] is False
    assert result["next_gate"] == "authenticated remote owner approval"


def test_scope_mismatch_fails_closed():
    result = plan_credential_use(
        reference="kiln.drive", caller="browser_operator", service="drive",
        account="quasarvolt", purpose="wrong caller", host="kiln",
        action_class="read_connector", allowed=[RULE])
    assert result["approved"] is False
