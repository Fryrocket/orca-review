from pathlib import Path

import importlib.util
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import pytest
import threading


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "deploy/orca_studio_gateway.py"
SPEC = importlib.util.spec_from_file_location("orca_studio_gateway", MODULE_PATH)
gateway = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gateway)


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
    assert gateway.allowed_request("POST", "/api/custom-bots/test")
    assert gateway.allowed_request("POST", "/api/jobs/job-1/resume")
    assert gateway.allowed_request("GET", "/api/images/health")
    assert not gateway.allowed_request("POST", "/api/images/health")
    assert gateway.allowed_request("POST", "/api/images/generate")
    assert not gateway.allowed_request("GET", "/api/images/generate")
    assert not gateway.allowed_request("POST", "/api/unknown-mutation")
    assert not gateway.allowed_request("DELETE", "/api/jobs/job-1")


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
    media = (ROOT / "deploy/kiln/orca-image-broker.service").read_text()
    controller = (ROOT / "deploy/kiln/orca_media_control.py").read_text()
    controller_unit = (ROOT / "deploy/kiln/orca-media-control.service").read_text()
    broker = (ROOT / "deploy/kiln/orca_image_broker.py").read_text()
    assert "--trusted-network-no-auth" not in control
    assert "--identity-token-file /var/lib/orca/identity-tokens.json" in control
    assert "--token-file /var/lib/orca-studio/gateway-token" in gateway_unit
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
