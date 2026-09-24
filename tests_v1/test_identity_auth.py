from __future__ import annotations

from http.client import HTTPConnection
from pathlib import Path
from threading import Thread
import json
import os
from itertools import count

import pytest

from orca.auth import (
    IdentityAuthenticationError,
    IdentityTokenAuthenticator,
    load_identity_authenticator,
)
from orca.control_plane import ControlPlane
from orca.web import OrcaHTTPServer


TOKENS = {
    "orca": "orca-identity-token-000000000000000",
    "smith": "smith-identity-token-00000000000000",
    "security_gate": "security-gate-token-0000000000000",
    "fry": "fry-identity-token-0000000000000000",
}
REQUEST_IDS = count(1)


def _post(server: OrcaHTTPServer, path: str, body: dict,
          identity: str | None = None, token: str | None = None, *,
          idempotency_key: str | None = None,
          expected_revision: int | None = None,
          include_envelope: bool = True) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if identity is not None:
        headers["X-ORCA-Identity"] = identity
    if token is not None:
        headers["X-ORCA-Identity-Token"] = token
    if identity is not None and include_envelope:
        headers["Idempotency-Key"] = (
            idempotency_key or f"test-request-{next(REQUEST_IDS):08d}")
        headers["X-ORCA-Expected-Revision"] = str(
            server.control_plane.state_revision
            if expected_revision is None else expected_revision)
    connection = HTTPConnection("127.0.0.1", server.server_port)
    try:
        connection.request("POST", path, body=json.dumps(body), headers=headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


@pytest.fixture
def identity_server():
    server = OrcaHTTPServer(
        ("127.0.0.1", 0), ControlPlane(), identity_tokens=TOKENS)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def test_identity_credentials_are_strict_unique_and_digest_only():
    authenticator = IdentityTokenAuthenticator(TOKENS)
    assert authenticator.identities == frozenset(TOKENS)
    assert authenticator.authenticate("orca", TOKENS["orca"]) == "orca"
    assert TOKENS["orca"] not in repr(authenticator.__dict__)
    with pytest.raises(IdentityAuthenticationError):
        authenticator.authenticate("orca", TOKENS["smith"])
    with pytest.raises(IdentityAuthenticationError):
        authenticator.authenticate("unknown", TOKENS["orca"])
    with pytest.raises(ValueError, match="registered identities"):
        IdentityTokenAuthenticator({"unknown": "x" * 32})
    with pytest.raises(ValueError, match="32-512"):
        IdentityTokenAuthenticator({"orca": "short"})
    with pytest.raises(ValueError, match="unique"):
        IdentityTokenAuthenticator({"orca": "x" * 32, "fry": "x" * 32})


def test_identity_token_file_must_be_owner_only_regular_json(tmp_path: Path):
    path = tmp_path / "identities.json"
    path.write_text(json.dumps(TOKENS), encoding="utf-8")
    path.chmod(0o600)
    authenticator = load_identity_authenticator(path)
    assert authenticator.identities == frozenset(TOKENS)
    assert authenticator.authenticate("fry", TOKENS["fry"]) == "fry"
    if os.name == "posix":
        path.chmod(0o640)
        with pytest.raises(ValueError, match="group or others"):
            load_identity_authenticator(path)
        path.chmod(0o600)
        link = tmp_path / "identity-link.json"
        link.symlink_to(path)
        with pytest.raises(ValueError, match="non-symlink"):
            load_identity_authenticator(link)


def test_auth_modes_are_explicit_and_mutually_exclusive():
    with pytest.raises(ValueError, match="not both"):
        OrcaHTTPServer(
            ("127.0.0.1", 0), ControlPlane(), operator_token="x" * 32,
            identity_tokens=TOKENS)


def test_identity_authentication_and_actor_binding(identity_server: OrcaHTTPServer):
    path = "/api/control/emergency-stop"
    body = {"active": True, "reason": "identity test"}
    status, payload = _post(identity_server, path, body)
    assert status == 401
    assert payload["error"] == "identity authentication required"
    status, _ = _post(identity_server, path, body, "fry", "wrong")
    assert status == 401
    status, payload = _post(
        identity_server, path, {**body, "actor": "fry"},
        "orca", TOKENS["orca"])
    assert status == 403
    assert "may not act as fry" in payload["error"]
    assert identity_server.control_plane.emergency_stop is False
    status, payload = _post(identity_server, path, body, "fry", TOKENS["fry"])
    assert status == 200
    assert payload["emergency_stop"] is True


def test_identity_mutations_require_and_replay_the_mutation_envelope(
        identity_server: OrcaHTTPServer):
    body = {"active": True, "reason": "idempotency test"}
    status, payload = _post(
        identity_server, "/api/control/emergency-stop", body,
        "fry", TOKENS["fry"], include_envelope=False)
    assert status == 428
    assert "Idempotency-Key" in payload["error"]

    key = "identity-replay-00000001"
    status, first = _post(
        identity_server, "/api/control/emergency-stop", body,
        "fry", TOKENS["fry"], idempotency_key=key, expected_revision=0)
    assert status == 200
    event_count = len(identity_server.control_plane.evidence.list())
    status, second = _post(
        identity_server, "/api/control/emergency-stop", body,
        "fry", TOKENS["fry"], idempotency_key=key, expected_revision=0)
    assert status == 200
    assert second == first
    assert len(identity_server.control_plane.evidence.list()) == event_count
    assert identity_server.control_plane.idempotency.count() == 1

    status, payload = _post(
        identity_server, "/api/control/emergency-stop", body,
        "fry", TOKENS["fry"], idempotency_key=key,
        expected_revision=identity_server.control_plane.state_revision)
    assert status == 409
    assert "different mutation" in payload["error"]


def test_stale_expected_revision_is_a_conflict(identity_server: OrcaHTTPServer):
    identity_server.control_plane.set_emergency_stop(
        actor="fry", active=True, reason="advance revision")
    status, payload = _post(
        identity_server, "/api/control/emergency-stop",
        {"active": False, "reason": "stale client"},
        "fry", TOKENS["fry"], expected_revision=0)
    assert status == 409
    assert "revision is stale" in payload["error"]
    assert identity_server.control_plane.emergency_stop is True


def test_job_lifecycle_uses_the_authenticated_identity(identity_server: OrcaHTTPServer):
    body = {
        "title": "identity-bound read",
        "lane": "orca",
        "assigned_to": "smith",
        "action": {"kind": "read", "resource": "fixture"},
    }
    status, job = _post(
        identity_server, "/api/jobs", body, "orca", TOKENS["orca"])
    assert status == 201
    assert job["requested_by"] == "orca"

    status, payload = _post(
        identity_server, "/api/jobs", {**body, "requested_by": "fry"},
        "orca", TOKENS["orca"])
    assert status == 403
    assert "may not act as fry" in payload["error"]

    status, payload = _post(
        identity_server, f"/api/jobs/{job['id']}/start", {"actor": "orca"},
        "smith", TOKENS["smith"])
    assert status == 403
    assert "may not act as orca" in payload["error"]
    status, started = _post(
        identity_server, f"/api/jobs/{job['id']}/start", {},
        "smith", TOKENS["smith"])
    assert status == 200
    assert started["status"] == "running"


def test_security_gate_endpoint_has_identity_authorization(identity_server: OrcaHTTPServer):
    body = {"author": "smith", "lane": "orca", "artifacts": {"README.md": "safe"}}
    status, payload = _post(
        identity_server, "/api/security/scan", body,
        "smith", TOKENS["smith"])
    assert status == 403
    assert "may not run the security gate" in payload["error"]
    status, payload = _post(
        identity_server, "/api/security/scan", body,
        "security_gate", TOKENS["security_gate"])
    assert status == 201
    assert payload["author"] == "smith"
    assert payload["requested_by"] == "security_gate"
    event = identity_server.control_plane.evidence.list(
        correlation_id=payload["correlation_id"], limit=1)[0]
    assert event["actor"] == "security_gate"

    status, payload = _post(
        identity_server, "/api/security/scan", body,
        "fry", TOKENS["fry"])
    assert status == 201
    assert payload["requested_by"] == "fry"
    event = identity_server.control_plane.evidence.list(
        correlation_id=payload["correlation_id"], limit=1)[0]
    assert event["actor"] == "fry"


def test_incident_evidence_records_the_authenticated_actor(
        identity_server: OrcaHTTPServer):
    status, incident = _post(
        identity_server, "/api/incidents",
        {"severity": "S1", "title": "actor fixture", "lane": "orca",
         "owner": "orca"},
        "fry", TOKENS["fry"],
    )
    assert status == 201
    event = identity_server.control_plane.evidence.list(
        correlation_id=incident["correlation_id"], limit=1)[0]
    assert event["kind"] == "incident.opened"
    assert event["actor"] == "fry"
