"""R11-F79 ("dashboard grant forgery") — a crisp finding.

Handler.do_POST's "/api/grant" branch read `human_approved` straight out
of the client-supplied JSON request body and forwarded it to
`PrivilegeBroker.grant(..., human_approved=human_approved)` with no
verification whatsoever. `PrivilegeBroker.grant()` itself trusts that
flag completely — per its own design (see roles.py: "Sensitive grant ...
requires HumanGate APPROVE from Fry (human_approved=True)"), the *caller*
is supposed to have already run a real HumanGate before ever passing
`human_approved=True`.

The dashboard never did. Any HTTP client that could reach `/api/grant`
(gated only by the optional bearer token — nothing at all when
ORCA_DASHBOARD_TOKEN isn't set, which is the default) could POST
`{"agent": "claude", "privs": ["orchestrate"], "human_approved": true}`
and be granted a SENSITIVE_GRANTS privilege (WRITE, CODE_EDIT,
FIRMWARE_EDIT, APPROVE_WRITE, HARDWARE_DESIGN, ORCHESTRATE) with zero
human involvement — DashboardGate.ask() was never called, no
`gate.pending` bus event fired, nobody ever saw or approved anything.

Fix: `/api/grant` now determines internally whether the requested privs
are sensitive. If so, it calls `st.gate.ask(...)` — the same
DashboardGate `/api/run` already uses for `require_human` — and only
sets `human_approved=True` from that gate's actual APPROVE decision.
Non-sensitive grants are unaffected (no gate needed; PrivilegeBroker.grant
itself only enforces human_approved for the sensitive-privilege case).
"""

from __future__ import annotations

import http.client
import json
import os
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("ORCA_REPO_ROOT", "/tmp/orca_f79_test_root")
os.environ.pop("ORCA_DASHBOARD_TOKEN", None)

import mao.web_ui.server as server_mod
from mao.roles import Privilege

# _GATE_TIMEOUT is read from the env once at first import of mao.web_ui.server
# — another test module may have imported it first (module cache), so setting
# the env var here would be a no-op. Patch the module attribute directly so
# the never-answered-gate test stays fast instead of waiting out the real
# 300s default.
server_mod._GATE_TIMEOUT = 0.3


def _fresh_server():
    server_mod.STATE = None  # force a clean DashboardState per test
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_mod.Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(0.1)
    return httpd, port, server_mod._state()


def _post(port, path, payload):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request(
        "POST", path, body=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    resp = conn.getresponse()
    body = json.loads(resp.read().decode() or "{}")
    conn.close()
    return resp.status, body


def test_forged_human_approved_does_not_grant_sensitive_privilege():
    """The bug: a plain client-supplied human_approved=True must not be
    enough on its own. With nobody ever answering the gate, the request
    must fail (whether via timeout or otherwise) and the broker state
    must stay untouched — never a silent 200 grant."""
    httpd, port, st = _fresh_server()
    try:
        assert Privilege.ORCHESTRATE not in st.broker._grants.get("claude", set())
        status, body = _post(port, "/api/grant", {
            "agent": "claude",
            "privs": ["orchestrate"],
            "human_approved": True,
        })
        assert status != 200, f"forged human_approved=True must not succeed, got {status}: {body}"
        assert Privilege.ORCHESTRATE not in st.broker._grants.get("claude", set()), (
            "sensitive privilege was granted despite no real gate approval"
        )
        assert "claude" not in st.broker._human_approved_grants
        assert st._gate_pending is False, "gate must not be left dangling open"
    finally:
        httpd.shutdown()


def test_sensitive_grant_succeeds_after_real_gate_approve():
    """Regression: the legitimate path still works — a real operator
    approving via /api/gate/decide must still let the grant through."""
    httpd, port, st = _fresh_server()
    try:
        def approve_soon():
            # Wait for the grant request to actually open the gate.
            deadline = time.time() + 3
            while not st._gate_pending and time.time() < deadline:
                time.sleep(0.02)
            assert st._gate_pending, "gate never opened for the sensitive grant"
            status, body = _post(port, "/api/gate/decide", {"decision": "approve"})
            assert status == 200

        approver = threading.Thread(target=approve_soon, daemon=True)
        approver.start()
        status, body = _post(port, "/api/grant", {
            "agent": "claude",
            "privs": ["orchestrate"],
            "human_approved": True,  # still forged; must be ignored either way
        })
        approver.join(timeout=3)
        assert status == 200, f"expected 200, got {status}: {body}"
        assert Privilege.ORCHESTRATE in st.broker._grants.get("claude", set())
        assert "claude" in st.broker._human_approved_grants
    finally:
        httpd.shutdown()


def test_sensitive_grant_denied_on_real_gate_reject():
    """Regression: an operator explicitly rejecting must deny the grant,
    not just timing out into a denial."""
    httpd, port, st = _fresh_server()
    try:
        def reject_soon():
            deadline = time.time() + 3
            while not st._gate_pending and time.time() < deadline:
                time.sleep(0.02)
            assert st._gate_pending
            status, body = _post(port, "/api/gate/decide", {"decision": "reject", "note": "no"})
            assert status == 200

        rejecter = threading.Thread(target=reject_soon, daemon=True)
        rejecter.start()
        status, body = _post(port, "/api/grant", {
            "agent": "claude",
            "privs": ["code_edit"],
            "human_approved": True,
        })
        rejecter.join(timeout=3)
        assert status == 403
        assert Privilege.CODE_EDIT not in st.broker._grants.get("claude", set())
    finally:
        httpd.shutdown()


def test_non_sensitive_grant_is_unaffected_and_needs_no_gate():
    """Regression: READ is not in SENSITIVE_GRANTS — must still grant
    immediately with no gate round-trip, exactly as before this patch."""
    httpd, port, st = _fresh_server()
    try:
        status, body = _post(port, "/api/grant", {
            "agent": "claude",
            "privs": ["read"],
            "human_approved": False,
        })
        assert status == 200, f"expected 200, got {status}: {body}"
        assert Privilege.READ in st.broker._grants.get("claude", set())
        assert st._gate_pending is False
    finally:
        httpd.shutdown()
