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
from .inventory import InventoryProvider, InventoryReadError, analyze_inventory_snapshot
from .inventory_system import inventory_system_blueprint
from .business import BusinessRevisionConflict


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
                 runtime_gateway: ModelRuntimeGateway | None = None,
                 inventory_provider: InventoryProvider | None = None,
                 trusted_network_no_auth: bool = False, chat_memory=None, bot_profiles=None,
                 inbox_store=None):
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
        self.chat_memory = chat_memory
        self.bot_profiles = bot_profiles
        self.inventory_provider = inventory_provider
        self.inbox_store = inbox_store
        self.trusted_network_no_auth = trusted_network_no_auth
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
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' blob:; media-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'",
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")

    def _product_artifact_root(self) -> Path:
        database = self.server.control_plane.evidence.path
        parent = Path(database).resolve().parent if database != ":memory:" else Path.cwd().resolve()
        return parent / "orca-product-artifacts"

    def _file(self, path: Path, mime: str) -> None:
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

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
        if self.server.trusted_network_no_auth:
            return "fry"
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
        if path == "/api/business/workflows":
            if set(data) != {"workflow_id", "title"}:
                raise ValueError("business workflow request has an invalid schema")
            job = control.start_business_workflow(
                workflow_id=data["workflow_id"], title=data["title"],
                requested_by=authenticated_identity or "")
            return control._job_dict(job), HTTPStatus.CREATED
        if path == "/api/business/records":
            required = {
                "record_type", "record_id", "source_system", "source_revision",
                "status", "data", "provenance", "confidence",
            }
            if not required <= set(data) or set(data) - (required | {"occurred_at"}):
                raise ValueError("business record request has an invalid schema")
            return control.upsert_business_record(
                **data, requested_by=authenticated_identity or ""), HTTPStatus.CREATED
        if path == "/api/product-development/plans":
            if set(data) != {"prompt"}:
                raise ValueError("product development request has an invalid schema")
            inventory = None
            if self.server.inventory_provider is not None:
                try:
                    inventory = self.server.inventory_provider.snapshot()
                except InventoryReadError:
                    inventory = None
            return control.create_product_development_plan(
                prompt=data["prompt"], inventory=inventory,
                requested_by=authenticated_identity or ""), HTTPStatus.CREATED
        if path == "/api/inventory/workflows":
            if set(data) != {"operation"} or not isinstance(data["operation"], dict):
                raise ValueError("inventory workflow request has an invalid schema")
            return control.propose_inventory_workflow(
                operation=data["operation"],
                requested_by=authenticated_identity or ""), HTTPStatus.CREATED
        if path.startswith("/api/inventory/workflows/") and path.endswith("/execute"):
            if set(data) != {"confirm"} or data["confirm"] is not True:
                raise ValueError("inventory workflow execution requires confirmation")
            job_id = path.split("/")[4]
            return control.run_approved_inventory_workflow(
                job_id, requested_by=authenticated_identity or ""), HTTPStatus.OK
        if path == "/api/inventory/counts/preview":
            if set(data) != {"observations", "reason", "evidence"}:
                raise ValueError("inventory count preview has an invalid schema")
            return control.preview_inventory_count_session(
                observations=data["observations"], reason=data["reason"],
                evidence=data["evidence"],
                requested_by=authenticated_identity or ""), HTTPStatus.OK
        if path == "/api/inventory/counts":
            if set(data) != {"observations", "reason", "evidence"}:
                raise ValueError("inventory count request has an invalid schema")
            return control.propose_inventory_count_session(
                observations=data["observations"], reason=data["reason"],
                evidence=data["evidence"],
                requested_by=authenticated_identity or ""), HTTPStatus.CREATED
        if path.startswith("/api/inventory/counts/") and path.endswith("/execute"):
            if set(data) != {"confirm"} or data["confirm"] is not True:
                raise ValueError("inventory count execution requires confirmation")
            job_id = path.split("/")[4]
            return control.run_approved_inventory_count_session(
                job_id, requested_by=authenticated_identity or ""), HTTPStatus.OK
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
        if path == "/api/product-development/projects":
            try:
                identity = self._authenticate_mutation()
            except IdentityAuthenticationError as exc:
                return self._json({"error": str(exc)}, HTTPStatus.UNAUTHORIZED)
            except RuntimeError:
                return self._json({"error": "project authentication is unavailable"}, HTTPStatus.SERVICE_UNAVAILABLE)
            if identity != "fry":
                return self._json({"error": "Only Fry may read product projects"}, HTTPStatus.FORBIDDEN)
            from .product_package import list_product_projects
            return self._json({"projects": list_product_projects(
                self._product_artifact_root())})
        if path.startswith("/api/product-development/packages/"):
            try:
                identity = self._authenticate_mutation()
            except IdentityAuthenticationError as exc:
                return self._json({"error": str(exc)}, HTTPStatus.UNAUTHORIZED)
            except RuntimeError:
                return self._json({"error": "product artifact authentication is unavailable"}, HTTPStatus.SERVICE_UNAVAILABLE)
            if identity != "fry":
                return self._json({"error": "Only Fry may download product artifacts"}, HTTPStatus.FORBIDDEN)
            parts = path.split("/")
            if len(parts) != 6:
                return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            try:
                from .product_package import resolve_product_package_artifact
                artifact = resolve_product_package_artifact(
                    self._product_artifact_root(), parts[4], parts[5])
            except (ValueError, FileNotFoundError):
                return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            mime = "application/zip" if artifact.suffix == ".zip" else "application/json"
            return self._file(artifact, mime)
        if path in {"/api/inbox", "/api/communications"}:
            try:
                identity = self._authenticate_mutation()
            except IdentityAuthenticationError as exc:
                return self._json({"error": str(exc)}, HTTPStatus.UNAUTHORIZED)
            except RuntimeError:
                return self._json({"error": "Inbox authentication is unavailable"},
                                  HTTPStatus.SERVICE_UNAVAILABLE)
            if identity != "fry":
                return self._json({"error": "Only Fry may read the Inbox"},
                                  HTTPStatus.FORBIDDEN)
            if self.server.inbox_store is None:
                return self._json({"error": "Inbox storage is unavailable"},
                                  HTTPStatus.SERVICE_UNAVAILABLE)
            if path == "/api/communications":
                return self._json(self.server.inbox_store.communications_snapshot())
            return self._json(self.server.inbox_store.snapshot())
        if path == "/api/config":
            return self._json({
                "authentication_required": not self.server.trusted_network_no_auth,
                "deployment": "trusted-network" if self.server.trusted_network_no_auth else "secured",
            })
        if path == "/api/engineering/catalog":
            from .engineering import engineering_catalog
            return self._json(engineering_catalog())
        if path == "/api/edge-inference":
            from .edge_inference import edge_inference_blueprint
            return self._json(edge_inference_blueprint(camera_connected=True))
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
        if path == "/api/business/state":
            try:
                self.server.control_plane.assert_fresh()
                return self._json(self.server.control_plane.business.snapshot())
            except RuntimeError:
                return self._json(
                    {"error": "business ledger integrity check failed"},
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
        if path == "/api/business/muse":
            from .muse import integration_status
            return self._json(integration_status())
        if path == "/api/health":
            try:
                self.server.control_plane.assert_fresh()
            except RuntimeError:
                return self._json(
                    {"status": "unhealthy", "integrity_valid": False},
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
            return self._json({"status": "healthy", "integrity_valid": True})
        if path == "/api/inventory/analysis":
            if self.server.inventory_provider is None:
                return self._json(
                    {"error": "inventory source is not configured"},
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
            try:
                snapshot = self.server.inventory_provider.snapshot()
                return self._json({
                    "snapshot": snapshot,
                    "analysis": analyze_inventory_snapshot(snapshot),
                })
            except InventoryReadError:
                return self._json(
                    {"error": "inventory source is unavailable"},
                    HTTPStatus.BAD_GATEWAY,
                )
            except ValueError:
                return self._json(
                    {"error": "inventory source returned invalid records"},
                    HTTPStatus.BAD_GATEWAY,
                )
        if path == "/api/inventory/system":
            return self._json(inventory_system_blueprint())
        if path == "/api/solo-operator/system":
            from .solo_operator import solo_operator_blueprint
            return self._json(solo_operator_blueprint())
        if path == "/api/inventory":
            if self.server.inventory_provider is None:
                return self._json(
                    {"error": "inventory source is not configured"},
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
            try:
                return self._json(self.server.inventory_provider.snapshot())
            except InventoryReadError:
                return self._json(
                    {"error": "inventory source is unavailable"},
                    HTTPStatus.BAD_GATEWAY,
                )
        asset = "index.html" if path == "/" else path.removeprefix("/")
        file = (STATIC_ROOT / asset).resolve()
        if STATIC_ROOT.resolve() not in file.parents or not file.is_file():
            return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        body = file.read_bytes()
        mime = {".html": "text/html", ".css": "text/css", ".js": "text/javascript",
                ".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}.get(file.suffix, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", f"{mime}; charset=utf-8" if mime.startswith("text/") else mime)
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
            if path == "/api/inbox/import":
                try:
                    identity = self._authenticate_mutation()
                except IdentityAuthenticationError as exc:
                    return self._json({"error": str(exc)}, HTTPStatus.UNAUTHORIZED)
                if identity != "fry":
                    raise IdentityAuthorizationError("Only Fry may import Inbox summaries")
                if self.server.inbox_store is None:
                    raise ValueError("Inbox storage is unavailable")
                return self._json(self.server.inbox_store.import_packet(self._body()))
            if path in {"/api/custom-bots/list", "/api/custom-bots/save", "/api/custom-bots/test"}:
                try:
                    identity = self._authenticate_mutation()
                except IdentityAuthenticationError as exc:
                    return self._json({"error":str(exc)}, HTTPStatus.UNAUTHORIZED)
                if identity != 'fry':
                    raise IdentityAuthorizationError('Only Fry may manage custom bots.')
                if self.server.bot_profiles is None:
                    raise ValueError('Bot Creator storage is not configured.')
                data=self._body()
                from .bot_creator import CREATOR_TOOLS, run_profile
                if path.endswith('/list'):
                    if data: raise ValueError('List takes no arguments.')
                    handlers = self.server.runtime_gateway.tool_broker.handlers if (
                        self.server.runtime_gateway and self.server.runtime_gateway.tool_broker) else {}
                    return self._json({'bots':self.server.bot_profiles.list(),
                        'tools':sorted(CREATOR_TOOLS & set(handlers)),
                        'model':'Qwen 3.5 · existing ORCA runtime'})
                if path.endswith('/save'):
                    return self._json(self.server.bot_profiles.save(data))
                if set(data)!={'id','prompt'}: raise ValueError('Test requires bot ID and prompt.')
                return self._json(run_profile(self.server.bot_profiles.get(data['id']),data['prompt'],self.server.runtime_gateway))
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
            if path in {"/api/inference", "/api/chat", "/api/memory", "/api/science", "/api/engineering", "/api/project/plan", "/api/cad/pcb-draft", "/api/product-development/package", "/api/temper/inventory-dataset/plan", "/api/business/muse/handoff", "/api/business/muse/email-handoff", "/api/solo-operator/action-plan", "/api/solo-operator/snapshot"}:
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
                data = self._body()
                if path == "/api/product-development/package":
                    if set(data) != {"prompt"}:
                        raise ValueError("product package creation requires one prompt")
                    from .product_package import (
                        attach_quench_review,
                        create_pi5_cooling_hat_package,
                        quench_review_prompt,
                    )
                    result = create_pi5_cooling_hat_package(
                        data["prompt"], self._product_artifact_root())
                    if self.server.runtime_gateway is not None:
                        independent = self.server.runtime_gateway.invoke(
                            service_id="kiln_quench", bot_id="quench",
                            prompt=quench_review_prompt(
                                self._product_artifact_root(), result["package_id"]),
                            use_tool_broker=False,
                        )
                        result = attach_quench_review(
                            self._product_artifact_root(), result["package_id"], independent)
                    return self._json(result, HTTPStatus.CREATED)
                if path == "/api/solo-operator/action-plan":
                    if set(data) != {"signals"}:
                        raise ValueError("Action Center request has an invalid schema")
                    from .solo_operator import build_action_plan
                    return self._json(build_action_plan(data["signals"]))
                if path == "/api/solo-operator/snapshot":
                    if set(data) != {"records"}:
                        raise ValueError("Solo Operator snapshot request has an invalid schema")
                    from .solo_operator import build_operating_snapshot
                    return self._json(build_operating_snapshot(data["records"]))
                if path == "/api/business/muse/handoff":
                    if set(data) != {"workflow_id", "objective"}:
                        raise ValueError("Muse handoff request has an invalid schema")
                    from .muse import build_handoff
                    return self._json(build_handoff(
                        workflow_id=data["workflow_id"], objective=data["objective"]))
                if path == "/api/business/muse/email-handoff":
                    if set(data) != {"workflow_id", "objective"}:
                        raise ValueError("Muse email handoff request has an invalid schema")
                    from .muse import build_email_handoff
                    return self._json(build_email_handoff(
                        workflow_id=data["workflow_id"], objective=data["objective"]))
                if path == "/api/temper/inventory-dataset/plan":
                    expected = {"name", "version", "labels", "source", "license_name",
                                "target_images_per_label", "session_id", "camera_profile"}
                    if set(data) != expected:
                        raise ValueError("inventory dataset planning request has an invalid schema")
                    from .vision_dataset import (
                        plan_inventory_capture_session,
                        plan_inventory_vision_dataset,
                    )
                    manifest = plan_inventory_vision_dataset(
                        name=data["name"], version=data["version"], labels=data["labels"],
                        source=data["source"], license_name=data["license_name"],
                        target_images_per_label=data["target_images_per_label"])
                    capture = plan_inventory_capture_session(
                        manifest=manifest, session_id=data["session_id"],
                        camera_profile=data["camera_profile"])
                    return self._json({
                        "status": "planned", "read_only": True,
                        "manifest": manifest, "capture_plan": capture,
                        "external_actions": 0,
                    })
                if path == "/api/cad/pcb-draft":
                    if set(data) != {"prompt"}:
                        raise ValueError("PCB draft creation requires one prompt")
                    from .cad import create_kicad_pcb_draft
                    return self._json(create_kicad_pcb_draft(data["prompt"]))
                if path == "/api/project/plan":
                    if set(data) != {"prompt"}:
                        raise ValueError("Project planning requires one prompt")
                    if self.server.inventory_provider is None:
                        raise PermissionError("inventory source is unavailable")
                    from .project_design import dog_feeder_plan
                    return self._json(dog_feeder_plan(
                        data["prompt"], self.server.inventory_provider.snapshot()))
                if path == "/api/science":
                    from .scientific import scientific_calculate
                    return self._json(scientific_calculate(**data))
                if path == "/api/engineering":
                    from .engineering import engineering_calculate
                    if set(data) != {"tool", "values"}:
                        raise ValueError("Engineering request requires tool and values only")
                    return self._json(engineering_calculate(**data))
                if path == "/api/memory":
                    if self.server.chat_memory is None:
                        raise PermissionError("conversation archive is unavailable")
                    if set(data) != {"request_id", "messages"}:
                        raise ValueError("invalid memory request schema")
                    return self._json(self.server.chat_memory.append(data["request_id"], data["messages"]))
                if self.server.runtime_gateway is None:
                    raise PermissionError("model invocation is disabled")
                if self.server.chat_memory is not None and "prompt" in data:
                    data["history"] = self.server.chat_memory.context(data["prompt"], data.get("history", []))
                if path == "/api/chat":
                    if (not {"prompt"} <= set(data)
                            or set(data) - {"prompt", "history", "business_job_id"}):
                        raise ValueError("chat request has an invalid schema")
                    business_job_id = data.get("business_job_id")
                    if business_job_id is not None and (
                            not isinstance(business_job_id, str)
                            or not business_job_id.startswith("job_")
                            or len(business_job_id) > 80):
                        raise ValueError("business workflow job id is invalid")
                    if business_job_id is not None:
                        self.server.control_plane.require_running_business_workflow(
                            business_job_id)
                    try:
                        result = self.server.runtime_gateway.chat(
                            prompt=data["prompt"], history=data.get("history", []))
                    except Exception:
                        if business_job_id is not None:
                            self.server.control_plane.record_business_workflow_result(
                                business_job_id, success=False,
                                result_sha256=sha256(b"").hexdigest(), result_bytes=0)
                        raise
                    if business_job_id is not None:
                        encoded = json.dumps(
                            result, sort_keys=True, separators=(",", ":"),
                            allow_nan=False).encode("utf-8")
                        self.server.control_plane.record_business_workflow_result(
                            business_job_id, success=True,
                            result_sha256=sha256(encoded).hexdigest(),
                            result_bytes=len(encoded),
                            routed_mode=str(result.get("mode", ""))
                            if isinstance(result, dict) else "")
                    return self._json(result)
                if not {"service_id", "bot_id", "prompt"} <= set(data) or set(data) - {"service_id", "bot_id", "prompt", "history"}:
                    raise ValueError("inference request has an invalid schema")
                context = {"history": data["history"]} if "history" in data else {}
                return self._json(self.server.runtime_gateway.invoke(
                    service_id=data["service_id"], bot_id=data["bot_id"],
                    prompt=data["prompt"], **context,
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
        except BusinessRevisionConflict as exc:
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
          runtime_gateway: ModelRuntimeGateway | None = None,
          inventory_provider: InventoryProvider | None = None,
          trusted_network_no_auth: bool = False, chat_memory=None, bot_profiles=None,
          inbox_store=None) -> None:
    server = OrcaHTTPServer(
        (host, port), control_plane or ControlPlane(), operator_token,
        identity_tokens=identity_tokens, runtime_gateway=runtime_gateway,
        inventory_provider=inventory_provider,
        trusted_network_no_auth=trusted_network_no_auth,
        chat_memory=chat_memory,
        bot_profiles=bot_profiles,
        inbox_store=inbox_store,
    )
    print(f"ORCA operator console: http://{host}:{server.server_port}")
    server.serve_forever()
