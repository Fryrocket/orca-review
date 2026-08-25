"""R11-F83 ("dashboard gate race").

DashboardGate.ask() mutated a single shared DashboardState gate slot
with no lock. ThreadingHTTPServer runs each request on its own thread,
so two concurrent sensitive /api/grant calls could both enter ask():
the second overwrote the first's displayed payload, and one
/api/gate/decide Event.set() woke BOTH waiters with the same result.

Fix: serialize ask() on DashboardGate._ask_lock for the full cycle.
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

os.environ.setdefault("ORCA_REPO_ROOT", "/tmp/orca_f83_test_root")
os.environ.pop("ORCA_DASHBOARD_TOKEN", None)

import mao.web_ui.server as server_mod
from mao.roles import Privilege

server_mod._GATE_TIMEOUT = 0.8


def _fresh_server():
    server_mod.STATE = None
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_mod.Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(0.1)
    return httpd, port, server_mod._state()


def _post(port, path, payload, timeout=8):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    conn.request(
        "POST", path, body=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    resp = conn.getresponse()
    body = json.loads(resp.read().decode() or "{}")
    conn.close()
    return resp.status, body


def _grant_async(port, agent, priv, box, key):
    def run():
        try:
            box[key] = _post(port, "/api/grant", {
                "agent": agent,
                "privs": [priv],
                "human_approved": True,
            }, timeout=8)
        except Exception as e:
            box[key] = e
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def test_second_pending_request_does_not_overwrite_first_while_visible():
    httpd, port, st = _fresh_server()
    box = {}
    try:
        t1 = _grant_async(port, "claude", "orchestrate", box, "first")
        deadline = time.time() + 2
        while not st._gate_pending and time.time() < deadline:
            time.sleep(0.02)
        assert st._gate_pending
        assert st._gate_payload.get("agent") == "claude"

        t2 = _grant_async(port, "relay", "code_edit", box, "second")
        time.sleep(0.15)
        assert st._gate_payload.get("agent") == "claude"
        assert Privilege.CODE_EDIT not in st.broker._grants.get("relay", set())

        status, body = _post(port, "/api/gate/decide", {"decision": "approve"})
        assert status == 200, body

        t1.join(timeout=3)
        t2.join(timeout=4)

        s1, b1 = box["first"]
        assert s1 == 200, b1
        assert Privilege.ORCHESTRATE in st.broker._grants.get("claude", set())

        second = box["second"]
        assert not isinstance(second, Exception), second
        s2, b2 = second
        assert s2 != 200, b2
        assert Privilege.CODE_EDIT not in st.broker._grants.get("relay", set())
    finally:
        httpd.shutdown()


def test_sequential_grants_still_work_normally():
    httpd, port, st = _fresh_server()
    try:
        def approve_soon():
            deadline = time.time() + 3
            while not st._gate_pending and time.time() < deadline:
                time.sleep(0.02)
            assert st._gate_pending
            status, body = _post(port, "/api/gate/decide", {"decision": "approve"})
            assert status == 200, body

        t = threading.Thread(target=approve_soon, daemon=True)
        t.start()
        s1, b1 = _post(port, "/api/grant", {
            "agent": "claude",
            "privs": ["orchestrate"],
        })
        t.join(timeout=3)
        assert s1 == 200, b1
        assert Privilege.ORCHESTRATE in st.broker._grants.get("claude", set())

        t = threading.Thread(target=approve_soon, daemon=True)
        t.start()
        s2, b2 = _post(port, "/api/grant", {
            "agent": "relay",
            "privs": ["code_edit"],
        })
        t.join(timeout=3)
        assert s2 == 200, b2
        assert Privilege.CODE_EDIT in st.broker._grants.get("relay", set())
    finally:
        httpd.shutdown()
