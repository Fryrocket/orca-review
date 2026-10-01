from __future__ import annotations

import hashlib
import json
import re


_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_ROUTINE_ACTIONS = frozenset({"open_app", "read_connector", "existing_login"})
_OWNER_ACTIONS = frozenset({
    "new_credential", "expand_scope", "export", "recover", "rotate", "delete",
    "move_money", "legal_acceptance", "publish", "security_change", "account_change",
})


def plan_credential_use(*, reference: str, caller: str, service: str,
                        account: str, purpose: str, host: str,
                        action_class: str, allowed: list[dict]) -> dict:
    """Authorize an opaque reference; never receive, reveal or inject a secret."""
    fields = {"reference": reference, "caller": caller, "service": service,
              "account": account, "host": host, "action_class": action_class}
    if any(not isinstance(value, str) or not _IDENTIFIER.fullmatch(value)
           for value in fields.values()):
        raise ValueError("credential request identifiers are invalid")
    if not isinstance(purpose, str) or not purpose.strip() or len(purpose) > 160:
        raise ValueError("credential purpose is invalid")
    if action_class not in _ROUTINE_ACTIONS | _OWNER_ACTIONS:
        raise ValueError("credential action class is unsupported")
    exact = any(
        isinstance(rule, dict)
        and rule.get("reference") == reference
        and rule.get("caller") == caller
        and rule.get("service") == service
        and rule.get("account") == account
        and rule.get("host") == host
        and action_class in rule.get("actions", [])
        for rule in allowed
    )
    preauthorized = exact and action_class in _ROUTINE_ACTIONS
    canonical = {**fields, "purpose": purpose.strip(),
                 "decision": "preauthorized" if preauthorized else "owner_approval_required"}
    request_id = hashlib.sha256(json.dumps(
        canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "schema": "orca.credential-request.v1", "request_id": request_id,
        **canonical, "approved": preauthorized, "secret_present": False,
        "may_enumerate_keychain": False, "may_export_secret": False,
        "may_log_secret": False,
        "next_gate": "inject opaque reference through the OS broker"
                     if preauthorized else "authenticated remote owner approval",
    }
