from pathlib import Path

import importlib.util
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import hashlib
import hmac
import os
import pytest
import subprocess
import threading
from types import SimpleNamespace
import zipfile


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "deploy/orca_studio_gateway.py"
SPEC = importlib.util.spec_from_file_location("orca_studio_gateway", MODULE_PATH)
gateway = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gateway)
CONVERTER_PATH = ROOT / "deploy/kiln/orca_manual_converter.py"
CONVERTER_SPEC = importlib.util.spec_from_file_location("orca_manual_converter", CONVERTER_PATH)
converter = importlib.util.module_from_spec(CONVERTER_SPEC)
CONVERTER_SPEC.loader.exec_module(converter)


def test_gateway_transport_boundary_is_loopback_or_tailnet_only():
    assert gateway.trusted_client("127.0.0.1")
    assert gateway.trusted_client("100.71.204.14")
    assert gateway.trusted_client("fd7a:115c:a1e0::1")
    assert not gateway.trusted_client("192.168.4.25")
    assert not gateway.trusted_client("8.8.8.8")


def test_gateway_route_and_method_allowlist_fails_closed():
    assert gateway.allowed_request("GET", "/")
    assert gateway.allowed_request("GET", "/api/state")
    assert gateway.allowed_request("POST", "/api/chat")
    assert gateway.allowed_request("POST", "/api/inference")
    assert not gateway.allowed_request("GET", "/api/inference")
    assert gateway.allowed_request("POST", "/api/custom-bots/test")
    assert gateway.allowed_request("POST", "/api/jobs/job-1/resume")
    assert gateway.allowed_request("GET", "/api/images/health")
    assert not gateway.allowed_request("POST", "/api/images/health")
    assert gateway.allowed_request("POST", "/api/images/generate")
    assert gateway.allowed_request("POST", "/api/manuals/export")
    assert gateway.allowed_request("GET", "/api/manuals/" + "a" * 64 + "/manual.pdf")
    assert not gateway.allowed_request("GET", "/api/manuals/../../etc/passwd")
    assert not gateway.allowed_request("GET", "/api/images/generate")
    assert not gateway.allowed_request("POST", "/api/unknown-mutation")
    assert not gateway.allowed_request("DELETE", "/api/jobs/job-1")


def test_manual_export_uses_libreoffice_and_is_idempotent(tmp_path: Path):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        output = Path(argv[argv.index("--outdir") + 1]) / f"manual.{argv[argv.index('--convert-to') + 1]}"
        if output.suffix == ".odt":
            with zipfile.ZipFile(output, "w") as archive:
                archive.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        else:
            output.write_bytes(b"%PDF-1.7\n" + b"verified" * 20)
        return SimpleNamespace(returncode=0, stdout="converted")

    content = "# Complete Manual\n\n" + ("A verified section of the manual.\n" * 8)
    first = converter.export_manual("ORCA User Manual", content, tmp_path, run=fake_run)
    second = converter.export_manual("ORCA User Manual", content, tmp_path, run=fake_run)
    assert first == second
    assert first["status"] == "verified"
    assert first["generator"] == "LibreOffice Writer on KILN"
    assert len(calls) == 2
    assert all(call[0][0] == "/usr/bin/libreoffice" for call in calls)
    assert all(call[1]["stdin"] is subprocess.DEVNULL for call in calls)
    assert (tmp_path / "manuals" / first["id"] / "manual.pdf").read_bytes().startswith(b"%PDF-")


def test_manual_export_rejects_bad_content_without_running_libreoffice(tmp_path: Path):
    def forbidden_run(*_args, **_kwargs):
        raise AssertionError("converter must not run")

    with pytest.raises(ValueError, match="100-64,000"):
        converter.export_manual("Manual", "too short", tmp_path, run=forbidden_run)
    with pytest.raises(ValueError, match="printable"):
        converter.export_manual("bad\nname", "x" * 200, tmp_path, run=forbidden_run)


def test_manual_html_escapes_untrusted_markup():
    rendered = converter.manual_html("Test <Manual>", "# Heading\n\n<script>alert(1)</script>\n\n- **safe**")
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "<strong>safe</strong>" in rendered


def test_manual_routes_require_authenticated_orca_identity(tmp_path: Path):
    gateway.Gateway.identity_token = "server-token-" + "x" * 32
    server = ThreadingHTTPServer(("127.0.0.1", 0), gateway.Gateway)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps({"title": "Manual", "content": "x" * 200})
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        connection.request("POST", "/api/manuals/export", body=body, headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        assert response.status == 401
        response.read()
        connection.close()

        session = hmac.new(
            gateway.Gateway.identity_token.encode(), b"orca-studio-session-v1", hashlib.sha256
        ).hexdigest()
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        connection.request("POST", "/api/manuals/export", body=b"{}", headers={
            "Content-Type": "application/json",
            "Cookie": f"ORCA_GATEWAY_SESSION={session}",
        })
        response = connection.getresponse()
        assert response.status == 400
        response.read()
        connection.close()
    finally:
        server.shutdown()
        server.server_close()


def test_verified_product_workflow_routes_are_narrowly_allowlisted():
    assert gateway.allowed_request("POST", "/api/administrator-screen/runs")
    assert gateway.allowed_request("GET", "/api/administrator-screen/runs")
    assert gateway.allowed_request(
        "GET", "/api/administrator-screen/runs/eng_20261003T153000Z_abcdef123456")
    assert not gateway.allowed_request(
        "GET", "/api/administrator-screen/runs/../../secrets")
    assert not gateway.allowed_request("DELETE", "/api/administrator-screen/runs")
    session = "/api/administrator-screen/sessions/admin_" + "a" * 24
    assert gateway.allowed_request("GET", "/api/administrator-screen/sessions")
    assert gateway.allowed_request("POST", "/api/administrator-screen/sessions")
    assert gateway.allowed_request("GET", session)
    assert gateway.allowed_request("POST", session + "/messages")
    assert gateway.allowed_request("POST", session + "/cancel")
    assert not gateway.allowed_request("POST", session + "/shell")
    assert not gateway.allowed_request("GET", session + "/messages")
    assert gateway.allowed_request("POST", "/api/product-development/package")
    assert gateway.allowed_request("POST", "/api/product-development/fabrication-readiness")
    assert not gateway.allowed_request("PUT", "/api/product-development/package")
    assert not gateway.allowed_request("POST", "/api/product-development/arbitrary")
    digest = "a" * 64
    assert gateway.allowed_request(
        "GET", f"/api/product-development/packages/{digest}/ORCA-Pi5-Environmental-Status-HAT.zip")
    assert gateway.allowed_request(
        "GET", f"/api/product-development/packages/{digest}/MANIFEST.json")
    assert not gateway.allowed_request(
        "GET", f"/api/product-development/packages/{digest}/secrets.txt")
    assert not gateway.allowed_request(
        "DELETE", f"/api/product-development/packages/{digest}/MANIFEST.json")


def test_gateway_token_file_must_be_owner_only(tmp_path: Path):
    token = tmp_path / "token"
    token.write_text("x" * 48)
    token.chmod(0o600)
    assert gateway.load_gateway_token(token) == "x" * 48
    token.chmod(0o640)
    with pytest.raises(ValueError, match="owner-only"):
        gateway.load_gateway_token(token)
    token.unlink()
    token.symlink_to(tmp_path / "missing")
    with pytest.raises((OSError, ValueError)):
        gateway.load_gateway_token(token)


def test_gateway_strips_client_auth_and_injects_server_identity():
    source = MODULE_PATH.read_text()
    assert 'CLIENT_AUTH_HEADERS' in source
    assert 'headers["X-ORCA-Identity"] = self.identity' in source
    assert 'headers["X-ORCA-Identity-Token"] = self.identity_token' in source
    assert 'self.headers.get("Transfer-Encoding")' in source


def test_gateway_replaces_client_identity_and_fails_closed():
    captured = {}

    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_GET(self):
            captured.update(path=self.path, headers=dict(self.headers.items()))
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    gateway.Gateway.upstream_host = "127.0.0.1"
    gateway.Gateway.upstream_port = upstream.server_port
    gateway.Gateway.identity_token = "server-token-" + "x" * 32
    proxy = ThreadingHTTPServer(("127.0.0.1", 0), gateway.Gateway)
    threads = [
        threading.Thread(target=upstream.serve_forever, daemon=True),
        threading.Thread(target=proxy.serve_forever, daemon=True),
    ]
    for thread in threads:
        thread.start()
    try:
        connection = HTTPConnection("127.0.0.1", proxy.server_port, timeout=3)
        connection.request("GET", "/api/inbox", headers={
            "X-ORCA-Identity": "attacker",
            "X-ORCA-Identity-Token": "attacker-token",
        })
        response = connection.getresponse()
        assert response.status == 200
        assert response.read() == b'{"ok":true}'
        assert captured["path"] == "/api/inbox"
        assert captured["headers"]["X-ORCA-Identity"] == "fry"
        assert captured["headers"]["X-ORCA-Identity-Token"] == gateway.Gateway.identity_token
        connection.close()

        connection = HTTPConnection("127.0.0.1", proxy.server_port, timeout=3)
        connection.request("POST", "/api/not-registered", body=b"{}")
        response = connection.getresponse()
        assert response.status == 405
        response.read()
        connection.close()
    finally:
        proxy.shutdown()
        upstream.shutdown()
        proxy.server_close()
        upstream.server_close()


def test_production_units_remove_trusted_network_auth_and_root_media_parser():
    control = (ROOT / "deploy/forge/orca.service").read_text()
    gateway_unit = (ROOT / "deploy/kiln/orca-studio-gateway.service").read_text()
    converter_unit = (ROOT / "deploy/kiln/orca-manual-converter.service").read_text()
    converter_source = CONVERTER_PATH.read_text()
    media = (ROOT / "deploy/kiln/orca-image-broker.service").read_text()
    controller = (ROOT / "deploy/kiln/orca_media_control.py").read_text()
    controller_unit = (ROOT / "deploy/kiln/orca-media-control.service").read_text()
    broker = (ROOT / "deploy/kiln/orca_image_broker.py").read_text()
    assert "--trusted-network-no-auth" not in control
    assert "--identity-token-file /var/lib/orca/identity-tokens.json" in control
    assert "--token-file /var/lib/orca-studio/gateway-token" in gateway_unit
    assert "ProtectHome=true" in gateway_unit
    assert "orca-manual-converter.service" in gateway_unit
    assert "User=orca-manual" in converter_unit
    assert "ProtectHome=true" in converter_unit
    assert "RestrictAddressFamilies=AF_UNIX" in converter_unit
    assert "socket.SO_PEERCRED" in converter_source
    assert '"/usr/bin/libreoffice"' in converter_source
    assert "User=orca-media" in media and "User=root" not in media
    assert set(gateway.MEDIA_PATHS) == gateway.MEDIA_GET_PATHS | gateway.MEDIA_POST_PATHS
    assert '"start-image"' in controller and '"stop-image"' in controller
    assert 'socket.SO_PEERCRED' in controller
    assert 'request = connection.recv(33)' in controller
    assert 'subprocess.run(' in controller
    assert 'User=root' in controller_unit
    assert 'RestrictAddressFamilies=AF_UNIX' in controller_unit
    assert 'control_engine("start-image")' in broker
    assert 'control_engine("stop-image")' in broker
    assert "/usr/bin/sudo" not in broker
