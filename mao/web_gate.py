"""Simple web UI for human-in-the-loop gates.

Stdlib only (http.server). Open http://127.0.0.1:8765 when a gate is pending.
"""

from __future__ import annotations

import html
import hmac
import json
from ipaddress import ip_address
import secrets
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Optional
from urllib.parse import parse_qs

from .human import GateDecision, GateResult, fail_closed_timeout
from .errors import OrcaConfigError


class WebHumanGate:
    """Blocking human gate backed by a tiny local web form."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        timeout_sec: float | None = None,
    ):
        try:
            loopback = host == "localhost" or ip_address(host).is_loopback
        except ValueError:
            loopback = False
        if not loopback:
            raise OrcaConfigError("the standalone human gate requires a loopback bind")
        self.host = host
        self.port = port
        self.timeout_sec = timeout_sec
        self._payload: Any = None
        self._context: str = ""
        self._result: Optional[GateResult] = None
        self._event = threading.Event()
        self._server: Optional[HTTPServer] = None
        self._ask_lock = threading.Lock()
        self._form_token = secrets.token_urlsafe(32)

    def ask(self, payload: Any, context: str = "") -> GateResult:
        with self._ask_lock:
            return self._ask(payload, context)

    def _ask(self, payload: Any, context: str) -> GateResult:
        self._payload = payload
        self._context = context
        self._result = None
        self._event.clear()
        self._form_token = secrets.token_urlsafe(32)

        handler = self._make_handler()
        self._server = HTTPServer((self.host, self.port), handler)
        self._server.timeout = 0.05
        self.port = int(self._server.server_address[1])
        thread = threading.Thread(target=self._serve_until_done, daemon=True)
        thread.start()

        print(f"\n[WebHumanGate] Open http://{self.host}:{self.port} to approve/reject/edit")
        ok = self._event.wait(timeout=self.timeout_sec)
        self._event.set()
        if self._server:
            try:
                self._server.server_close()
            except Exception:
                pass
        if not ok:
            fail_closed_timeout(
                f"WebHumanGate no response within {self.timeout_sec}s"
            )
        return self._result or GateResult(GateDecision.SKIP, content=payload)

    def _serve_until_done(self):
        assert self._server is not None
        while not self._event.is_set():
            try:
                self._server.handle_request()
            except Exception:
                break

    def _make_handler(self):
        gate = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def end_headers(self):
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
                super().end_headers()

            def _allowed_host(self):
                from urllib.parse import urlsplit
                try:
                    host = urlsplit("//" + self.headers.get("Host", "")).hostname
                except ValueError:
                    host = None
                if host not in {gate.host, "localhost", "127.0.0.1", "::1"}:
                    self.send_error(421, "host is not allowed")
                    return False
                return True

            def do_GET(self):
                if not self._allowed_host():
                    return
                if self.path != "/":
                    return self.send_error(404)
                # R11-F81: context and payload can carry attacker/model-
                # controlled text (e.g. an orchestrator `objective` or a
                # begin_task() grant note) -- this page's whole job is to
                # show that content to a human before they click Approve.
                # Rendering it unescaped meant a payload containing
                # </pre><script>...</script> ran with same-origin access
                # to POST /decide, letting injected content approve its
                # own gate with no real human click. HTML-escape both
                # before embedding.
                safe_context = html.escape(str(gate._context))
                safe_payload = html.escape(
                    json.dumps(gate._payload, indent=2, default=str)
                )
                body = f"""<!doctype html>
<html><head><title>Orca Human Gate</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 720px; margin: 2rem auto; }}
pre {{ background: #111; color: #eee; padding: 1rem; overflow: auto; }}
button {{ margin-right: .5rem; padding: .5rem 1rem; }}
textarea {{ width: 100%; height: 120px; }}
</style></head><body>
<h1>Orca Human Gate</h1>
<p><b>Context:</b> {safe_context}</p>
<pre>{safe_payload}</pre>
<form method=\"POST\" action=\"/decide\">
  <input type=\"hidden\" name=\"csrf_token\" value=\"{gate._form_token}\"/>
  <p>
    <button name=\"decision\" value=\"approve\">Approve</button>
    <button name=\"decision\" value=\"reject\">Reject</button>
    <button name=\"decision\" value=\"skip\">Skip</button>
  </p>
  <p>Edit (optional — submits as Edit):</p>
  <textarea name=\"edited\"></textarea>
  <p><button name=\"decision\" value=\"edit\">Submit Edit</button></p>
  <p>Note: <input name=\"note\" style=\"width:70%\"/></p>
</form>
</body></html>"""
                data = body.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                if not self._allowed_host():
                    return
                if self.path != "/decide":
                    return self.send_error(404)
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    if not 0 < length <= 65536:
                        return self.send_error(413)
                    raw = self.rfile.read(length).decode()
                    form = parse_qs(raw, max_num_fields=8)
                except (ValueError, UnicodeError):
                    return self.send_error(400)
                supplied_token = (form.get("csrf_token") or [""])[0]
                if not hmac.compare_digest(supplied_token.encode(), gate._form_token.encode()):
                    return self.send_error(403, "current form token required")
                if gate._event.is_set():
                    return self.send_error(409, "gate is no longer pending")
                decision = (form.get("decision") or ["skip"])[0]
                note = (form.get("note") or [""])[0]
                edited = (form.get("edited") or [""])[0]

                if decision == "approve":
                    gate._result = GateResult(GateDecision.APPROVE, content=gate._payload, note=note)
                elif decision == "reject":
                    gate._result = GateResult(GateDecision.REJECT, note=note)
                elif decision == "edit":
                    gate._result = GateResult(
                        GateDecision.EDIT,
                        content=edited or gate._payload,
                        note=note,
                    )
                else:
                    gate._result = GateResult(GateDecision.SKIP, content=gate._payload, note=note)

                ok = b"<html><body><h2>Recorded. You can close this tab.</h2></body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(ok)))
                self.end_headers()
                self.wfile.write(ok)
                gate._event.set()

        return Handler
