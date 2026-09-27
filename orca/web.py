from __future__ import annotations

from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from hashlib import sha256
import json
from pathlib import Path
from collections.abc import Mapping
from urllib.parse import urlparse
import base64
import binascii
import hmac

from .auth import (
    IdentityAuthenticationError,
    IdentityAuthorizationError,
    IdentityTokenAuthenticator,
)
from .control_plane import ControlPlane
from .domain import Action
from .fleet import Heartbeat
from .policy import PolicyViolation
from .security import redact_text
from .idempotency import IdempotencyConflict, StateRevisionConflict
from .runtime import ModelRuntimeGateway


STATIC_ROOT = Path(__file__).with_name("static")


class MutationPreconditionError(ValueError):
    pass


class UnknownMutationRoute(LookupError):
    pass


def _is_loopback_bind(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


class OrcaHTTPServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], control_plane: ControlPlane,
                 operator_token: str | None = None,
                 identity_tokens: Mapping[str, str] | IdentityTokenAuthenticator | None = None,
                 runtime_gateway: ModelRuntimeGateway | None = None):
        if not _is_loopback_bind(address[0]):
            raise ValueError(
                "non-loopback ORCA binding is disabled pending reviewed transport security")
        if operator_token is not None and (
                not isinstance(operator_token, str)
                or not 32 <= len(operator_token) <= 512):
            raise ValueError("operator token must contain 32-512 characters")
        if operator_token is not None and identity_tokens is not None:
            raise ValueError("configure operator-token or identity-token authentication, not both")
        self.control_plane = control_plane
        self.operator_token = operator_token
        self.identity_authenticator = identity_tokens if isinstance(
            identity_tokens, IdentityTokenAuthenticator
        ) else IdentityTokenAuthenticator(identity_tokens) if identity_tokens is not None else None
        self.runtime_gateway = runtime_gateway
        self.allowed_hosts = frozenset({address[0], "127.0.0.1", "localhost", "::1"})
        super().__init__(address, OrcaHandler)


class OrcaHandler(BaseHTTPRequestHandler):
    server: OrcaHTTPServer

    def log_message(self, format: str, *args) -> None:
        return

    def _json(self, payload: object, status: int = 200,
              extra_headers: Mapping[str, str] | None = None) -> None:
        body = json.dumps(payload, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _security_headers(self) -> None:
        self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")

    def _host_allowed(self) -> bool:
        supplied = self.headers.get("Host", "")
        if supplied.startswith("[") and "]" in supplied:
            host = supplied[1:supplied.index("]")]
        else:
            host = supplied.rsplit(":", 1)[0] if supplied.count(":") == 1 else supplied
        return host in self.server.allowed_hosts

    def _body(self) -> dict:
        if self.headers.get_content_type() != "application/json":
            raise ValueError("request content type must be application/json")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("request content length is invalid") from exc
        if length < 0 or length > 1_000_000:
            raise ValueError("request body too large")
        try:
            payload = json.loads(
                self.rfile.read(length) or b"{}",
                parse_constant=lambda value: (_ for _ in ()).throw(
                    ValueError(f"invalid JSON constant: {value}")),
            )
        except json.JSONDecodeError as exc:
            raise ValueError("request body is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def _authenticate_mutation(self) -> str:
        authenticator = self.server.identity_authenticator
        if authenticator is not None:
            return authenticator.authenticate(
                self.headers.get("X-ORCA-Identity", ""),
                self.headers.get("X-ORCA-Identity-Token", ""),
            )
        configured = self.server.operator_token
        if not configured:
            raise RuntimeError("operator mutations are disabled")
        supplied = self.headers.get("X-ORCA-Operator-Token", "")
        if not hmac.compare_digest(configured, supplied):
            raise IdentityAuthenticationError("operator authentication required")
        # The shared compatibility credential is the local owner's credential;
        # it never grants the ability to claim another stable identity.
        return "fry"

    @staticmethod
    def _bind_identity(data: dict, authenticated_identity: str | None,
                       field: str = "actor") -> None:
        if authenticated_identity is None:
            return
        claimed = data.get(field)
        if claimed is not None and claimed != authenticated_identity:
            raise IdentityAuthorizationError(
                f"authenticated identity may not act as {claimed}")
        data[field] = authenticated_identity

    @staticmethod
    def _require_identity(authenticated_identity: str | None,
                          allowed: set[str], action: str) -> None:
        if authenticated_identity is not None and authenticated_identity not in allowed:
            raise IdentityAuthorizationError(
                f"{authenticated_identity} may not {action}")

    def _mutation_envelope(self, path: str, identity: str, data: dict) -> tuple[str, int, str]:
        key = self.headers.get("Idempotency-Key", "")
        revision_text = self.headers.get("X-ORCA-Expected-Revision", "")
        if not key or not revision_text:
            raise MutationPreconditionError(
                "identity mutations require Idempotency-Key and X-ORCA-Expected-Revision")
        try:
            revision = int(revision_text)
        except ValueError as exc:
            raise MutationPreconditionError(
                "expected state revision must be a nonnegative integer") from exc
        canonical = json.dumps(
            {"body": data, "expected_revision": revision, "identity": identity,
             "method": "POST", "path": path},
            sort_keys=True, separators=(",", ":"), allow_nan=False,
        )
        return key, revision, sha256(canonical.encode()).hexdigest()

    def _dispatch_mutation(self, path: str, data: dict,
                           authenticated_identity: str | None) -> tuple[dict, int]:
        control = self.server.control_plane
        if path == "/api/jobs":
            self._bind_identity(data, authenticated_identity, "requested_by")
            action = Action(**data.pop("action"))
            job = control.submit(action=action, **data)
            return control._job_dict(job), HTTPStatus.CREATED
        if path == "/api/queue":
            self._bind_identity(data, authenticated_identity, "requested_by")
            action = Action(**data.pop("action"))
            job = control.queue(action=action, **data)
            return control._job_dict(job), HTTPStatus.CREATED
        if path == "/api/incidents":
            self._require_identity(authenticated_identity, {"orca", "fry"}, "open incidents")
            self._bind_identity(data, authenticated_identity)
            return asdict(control.open_incident(**data)), HTTPStatus.CREATED
        if path == "/api/security/scan":
            self._require_identity(
                authenticated_identity, {"security_gate", "orca", "fry"},
                "run the security gate")
            report = control.run_security_gate(
                author=data.get("author", ""), lane=data.get("lane", ""),
                artifacts=data.get("artifacts", {}),
                requested_by=authenticated_identity or "security_gate")
            return report, HTTPStatus.CREATED
        if path == "/api/governance/retention-audit":
            self._bind_identity(data, authenticated_identity)
            return control.run_retention_audit(
                actor=data.get("actor", ""), now=data.get("now")), HTTPStatus.CREATED
        if path.startswith("/api/approvals/"):
            self._bind_identity(data, authenticated_identity)
            job = control.decide(
                path.rsplit("/", 1)[-1], actor=data.get("actor", ""),
                approve=data.get("approve"), note=data.get("note", ""))
            return control._job_dict(job), HTTPStatus.OK
        if path.startswith("/api/jobs/") and path.endswith("/pause"):
            self._bind_identity(data, authenticated_identity)
            job = control.pause(
                path.split("/")[3], actor=data.get("actor", "orca"),
                reason=data.get("reason", "operator pause"))
            return control._job_dict(job), HTTPStatus.OK
        if path.startswith("/api/jobs/") and path.endswith("/start"):
            self._bind_identity(data, authenticated_identity)
            job = control.start_job(path.split("/")[3], actor=data.get("actor", ""))
            return control._job_dict(job), HTTPStatus.OK
        if path.startswith("/api/jobs/") and path.endswith("/resume"):
            self._bind_identity(data, authenticated_identity)
            job = control.resume(
                path.split("/")[3], actor=data.get("actor", ""),
                reason=data.get("reason", ""))
            return control._job_dict(job), HTTPStatus.OK
        if path.startswith("/api/jobs/") and path.endswith("/review"):
            self._bind_identity(data, authenticated_identity)
            job = control.submit_job_review(
                path.split("/")[3], actor=data.get("actor", ""),
                reviewer=data.get("reviewer", "quench"))
            return control._job_dict(job), HTTPStatus.OK
        if path.startswith("/api/jobs/") and path.endswith("/complete"):
            self._bind_identity(data, authenticated_identity)
            job = control.complete_job(
                path.split("/")[3], actor=data.get("actor", ""),
                note=data.get("note", ""))
            return control._job_dict(job), HTTPStatus.OK
        if path.startswith("/api/nodes/") and path.endswith("/pause"):
            self._bind_identity(data, authenticated_identity)
            node_id = path.split("/")[3]
            control.set_node_pause(
                node_id, actor=data.get("actor", "orca"),
                paused=data.get("paused", True), reason=data.get("reason", "operator action"))
            return {"node_id": node_id, "paused": node_id in control.paused_nodes}, HTTPStatus.OK
        if path.startswith("/api/nodes/") and path.endswith("/health"):
            self._bind_identity(data, authenticated_identity)
            node_id = path.split("/")[3]
            control.report_node_health(
                node_id, actor=data.get("actor", "orca"),
                state=data.get("state", "unproven"), detail=data.get("detail", ""))
            return control._node_dict(node_id), HTTPStatus.OK
        if path.startswith("/api/bots/") and path.endswith("/pause"):
            self._bind_identity(data, authenticated_identity)
            bot_id = path.split("/")[3]
            control.set_bot_pause(
                bot_id, actor=data.get("actor", "orca"),
                paused=data.get("paused", True), reason=data.get("reason", "operator action"))
            return {"bot_id": bot_id, "paused": bot_id in control.bots.paused}, HTTPStatus.OK
        if path.startswith("/api/lanes/") and path.endswith("/pause"):
            self._bind_identity(data, authenticated_identity)
            lane = path.split("/")[3]
            control.set_lane_pause(
                lane, actor=data.get("actor", "orca"),
                paused=data.get("paused", True), reason=data.get("reason", "operator action"))
            return {"lane": lane, "paused": lane in control.paused_lanes}, HTTPStatus.OK
        if path == "/api/control/emergency-stop":
            self._bind_identity(data, authenticated_identity)
            control.set_emergency_stop(
                actor=data.get("actor", ""), active=data.get("active", True),
                reason=data.get("reason", "operator action"))
            return {"emergency_stop": control.emergency_stop}, HTTPStatus.OK
        if path.startswith("/api/incidents/"):
            self._bind_identity(data, authenticated_identity)
            incident = control.update_incident(path.rsplit("/", 1)[-1], **data)
            return asdict(incident), HTTPStatus.OK
        raise UnknownMutationRoute(path)

    def do_GET(self) -> None:
        if not self._host_allowed():
            return self._json({"error": "host header is not allowlisted"}, HTTPStatus.MISDIRECTED_REQUEST)
        path = urlparse(self.path).path
        if path == "/api/state":
            try:
                snapshot = self.server.control_plane.snapshot()
                snapshot["events"] = self.server.control_plane.evidence.list(limit=100)
                return self._json(snapshot)
            except RuntimeError:
                return self._json(
                    {"error": "control-plane integrity check failed"},
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
        if path == "/api/health":
            try:
                self.server.control_plane._assert_fresh()
            except RuntimeError:
                return self._json(
                    {"status": "unhealthy", "integrity_valid": False},
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
            return self._json({"status": "healthy", "integrity_valid": True})
        asset = "index.html" if path == "/" else path.removeprefix("/")
        file = (STATIC_ROOT / asset).resolve()
        if STATIC_ROOT.resolve() not in file.parents or not file.is_file():
            return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        body = file.read_bytes()
        mime = {".html": "text/html", ".css": "text/css", ".js": "text/javascript"}.get(file.suffix, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", f"{mime}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if not self._host_allowed():
            return self._json({"error": "host header is not allowlisted"}, HTTPStatus.MISDIRECTED_REQUEST)
        path = urlparse(self.path).path
        try:
            if path == "/api/heartbeats":
                data = self._body()
                if set(data) != {"heartbeat", "signature", "key"}:
                    raise ValueError("heartbeat request has an invalid schema")
                heartbeat_data = data["heartbeat"]
                if not isinstance(heartbeat_data, dict) or set(heartbeat_data) != {
                        "node_id", "timestamp", "nonce", "state", "detail"}:
                    raise ValueError("heartbeat payload has an invalid schema")
                try:
                    key = base64.b64decode(data["key"], validate=True)
                except (TypeError, ValueError, binascii.Error) as exc:
                    raise ValueError("heartbeat key encoding is invalid") from exc
                if not 32 <= len(key) <= 512:
                    raise ValueError("heartbeat key has an invalid length")
                heartbeat = Heartbeat(**heartbeat_data)
                self.server.control_plane.accept_heartbeat(
                    heartbeat, signature=data["signature"], key=key)
                return self._json({
                    "accepted": True,
                    "node_id": heartbeat.node_id,
                    "nonce": heartbeat.nonce,
                    "status": "accepted",
                }, HTTPStatus.OK)
            if path == "/api/inference":
                try:
                    authenticated_identity = self._authenticate_mutation()
                except IdentityAuthenticationError as exc:
                    return self._json({"error": str(exc)}, HTTPStatus.UNAUTHORIZED)
                except RuntimeError:
                    return self._json(
                        {"error": "operator mutations are disabled"},
                        HTTPStatus.SERVICE_UNAVAILABLE,
                    )
                if authenticated_identity != "fry":
                    raise IdentityAuthorizationError(
                        "only Fry may initiate local model inference")
                if self.server.runtime_gateway is None:
                    raise PermissionError("model invocation is disabled")
                data = self._body()
                if set(data) != {"service_id", "bot_id", "prompt"}:
                    raise ValueError("inference request has an invalid schema")
                return self._json(self.server.runtime_gateway.invoke(
                    service_id=data["service_id"], bot_id=data["bot_id"],
                    prompt=data["prompt"],
                ))
            try:
                authenticated_identity = self._authenticate_mutation()
            except IdentityAuthenticationError as exc:
                return self._json({"error": str(exc)}, HTTPStatus.UNAUTHORIZED)
            except RuntimeError:
                return self._json(
                    {"error": "operator mutations are disabled"},
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
            data = self._body()
            key, revision, request_hash = self._mutation_envelope(
                path, authenticated_identity, data)
            payload, status, replayed, receipt_revision = (
                self.server.control_plane.execute_idempotent(
                key=key, actor=authenticated_identity, operation=f"POST {path}",
                request_hash=request_hash, expected_revision=revision,
                mutation=lambda: self._dispatch_mutation(
                    path, data, authenticated_identity),
                )
            )
            return self._json(payload, status, {
                "X-ORCA-Idempotency-Replayed": "true" if replayed else "false",
                "X-ORCA-Receipt-Revision": str(receipt_revision),
                # This is the revision atomically bound to the response receipt,
                # not a later unsynchronized observation of global state.
                "X-ORCA-State-Revision": str(receipt_revision),
            })
        except MutationPreconditionError as exc:
            return self._json({"error": str(exc)}, HTTPStatus.PRECONDITION_REQUIRED)
        except UnknownMutationRoute:
            return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except IdentityAuthorizationError as exc:
            return self._json({"error": redact_text(str(exc))}, HTTPStatus.FORBIDDEN)
        except IdempotencyConflict as exc:
            return self._json({"error": redact_text(str(exc))}, HTTPStatus.CONFLICT)
        except StateRevisionConflict as exc:
            return self._json({"error": redact_text(str(exc))}, HTTPStatus.CONFLICT)
        except (ValueError, KeyError, TypeError, PermissionError, PolicyViolation) as exc:
            return self._json({"error": redact_text(str(exc))}, HTTPStatus.BAD_REQUEST)
        except RuntimeError:
            return self._json(
                {"error": "control-plane integrity or concurrency check failed"},
                HTTPStatus.SERVICE_UNAVAILABLE,
            )


def serve(control_plane: ControlPlane | None = None, *, host: str = "127.0.0.1", port: int = 8787,
          operator_token: str | None = None,
          identity_tokens: Mapping[str, str] | IdentityTokenAuthenticator | None = None,
          runtime_gateway: ModelRuntimeGateway | None = None) -> None:
    server = OrcaHTTPServer(
        (host, port), control_plane or ControlPlane(), operator_token,
        identity_tokens=identity_tokens, runtime_gateway=runtime_gateway,
    )
    print(f"ORCA operator console: http://{host}:{server.server_port}")
    server.serve_forever()
