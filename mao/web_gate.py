"""Simple web UI for human-in-the-loop gates.

Stdlib only (http.server). Open http://127.0.0.1:8765 when a gate is pending.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Optional
from urllib.parse import parse_qs

from .human import GateDecision, GateResult, fail_closed_timeout


class WebHumanGate:
    """Blocking human gate backed by a tiny local web form."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        timeout_sec: float | None = None,
    ):
        self.host = host
        self.port = port
        self.timeout_sec = timeout_sec
        self._payload: Any = None
        self._context: str = ""
        self._result: Optional[GateResult] = None
        self._event = threading.Event()
        self._server: Optional[HTTPServer] = None

    def ask(self, payload: Any, context: str = "") -> GateResult:
        self._payload = payload
        self._context = context
        self._result = None
        self._event.clear()

        handler = self._make_handler()
        self._server = HTTPServer((self.host, self.port), handler)
        self.port = int(self._server.server_address[1])
        thread = threading.Thread(target=self._serve_until_done, daemon=True)
        thread.start()

        print(f"\n[WebHumanGate] Open http://{self.host}:{self.port} to approve/reject/edit")
        ok = self._event.wait(timeout=self.timeout_sec)
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

            def do_GET(self):
                body = f"""<!doctype html>
<html><head><title>Orca Human Gate</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 720px; margin: 2rem auto; }}
pre {{ background: #111; color: #eee; padding: 1rem; overflow: auto; }}
button {{ margin-right: .5rem; padding: .5rem 1rem; }}
textarea {{ width: 100%; height: 120px; }}
</style></head><body>
<h1>Orca Human Gate</h1>
<p><b>Context:</b> {gate._context}</p>
<pre>{json.dumps(gate._payload, indent=2, default=str)}</pre>
<form method=\"POST\" action=\"/decide\">
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
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length).decode()
                form = parse_qs(raw)
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
