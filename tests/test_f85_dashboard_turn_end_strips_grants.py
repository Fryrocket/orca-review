"""R11-F85 — the manual /api/turn/end control strips standing /api/grant
privileges too, the same way /api/run did before F84 -- F84's fix only
lived inside /api/run's handler.

index.html exposes explicit "Start turn" / "End turn" buttons wired to
POST /api/turn/start and POST /api/turn/end. Handler.do_POST's
/api/turn/end branch calls st.broker.end_turn("grok") directly --
PrivilegeBroker.end_turn() unconditionally revokes whatever was
dynamically granted to the currently-active-turn agent (same mechanism
F84 fixed for /api/run). F84's restoration logic (DashboardState.
_standing_grants replay) was added only inside /api/run's handler, so a
human clicking the manual Start turn / End turn buttons (or any client
calling those endpoints directly) still silently loses a standing
/api/grant privilege, with no /api/revoke ever called -- the exact same
class of bug F84 fixed, reachable through a different control.

Reproduced directly against a real ThreadingHTTPServer/Handler at the
pinned tree (mirror 25f7434, F84 landed, 225 passed): granted claude
WRITE via a real approved gate, then called POST /api/turn/start
{"agent":"claude"} followed by POST /api/turn/end -- confirmed claude's
WRITE was silently stripped, with neither endpoint touching
_standing_grants at all.

Fix: factor the restoration into _restore_standing_grants(st) and call it
from /api/turn/end too (right after end_turn()); also wrap /api/turn/
start and /api/turn/end in the same _run_lock /api/run already uses, so
manual turn control can't interleave with an in-flight run either.
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

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("ORCA_REPO_ROOT", "/tmp/orca_f85_test_root")
os.environ.pop("ORCA_DASHBOARD_TOKEN", None)

import mao.web_ui.server as server_mod
from mao.roles import Privilege


@pytest.fixture(autouse=True)
def _short_gate_timeout(monkeypatch):
    monkeypatch.setattr(server_mod, "_GATE_TIMEOUT", 5.0)


def _fresh_server():
    server_mod.STATE = None
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_mod.Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(0.1)
    return httpd, port, server_mod._state()


def _post(port, path, payload, timeout=15):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    conn.request(
        "POST", path, body=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    resp = conn.getresponse()
    body = json.loads(resp.read().decode() or "{}")
    conn.close()
    return resp.status, body


def _grant_write_to_claude(port, st):
    def approve_soon():
        deadline = time.time() + 3
        while not st._gate_pending and time.time() < deadline:
            time.sleep(0.01)
        _post(port, "/api/gate/decide", {"decision": "approve"})

    a = threading.Thread(target=approve_soon, daemon=True)
    a.start()
    status, body = _post(port, "/api/grant", {
        "agent": "claude",
        "privs": ["write"],
        "note": "test elevation",
    }, timeout=5)
    a.join(timeout=5)
    assert status == 200, body


def test_manual_turn_end_does_not_strip_standing_grant():
    httpd, port, st = _fresh_server()
    try:
        _grant_write_to_claude(port, st)
        assert Privilege.WRITE in st.broker._grants.get("claude", set())
        s1, _ = _post(port, "/api/turn/start", {"agent": "claude"})
        s2, _ = _post(port, "/api/turn/end", {})
        assert s1 == 200 and s2 == 200
        assert Privilege.WRITE in st.broker._grants.get("claude", set()), (
            "manual /api/turn/end must not silently strip a standing /api/grant privilege"
        )
    finally:
        httpd.shutdown()


def test_revoke_still_sticks_through_a_turn_cycle():
    httpd, port, st = _fresh_server()
    try:
        _grant_write_to_claude(port, st)
        status, _ = _post(port, "/api/revoke", {"agent": "claude"})
        assert status == 200
        assert Privilege.WRITE not in st.broker._grants.get("claude", set())
        _post(port, "/api/turn/start", {"agent": "claude"})
        _post(port, "/api/turn/end", {})
        assert Privilege.WRITE not in st.broker._grants.get("claude", set()), (
            "an explicit /api/revoke must not be undone by a subsequent turn start/end cycle"
        )
    finally:
        httpd.shutdown()
