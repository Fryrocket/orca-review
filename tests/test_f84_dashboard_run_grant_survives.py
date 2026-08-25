"""R11-F84 — /api/run silently strips standing /api/grant privileges, and
concurrent /api/run calls race on the shared turn state.

Two related defects in mao/web_ui/server.py, both stemming from the
dashboard wiring a single shared PrivilegeBroker/Orchestrator behind
ThreadingHTTPServer:

1. Orchestrator._turn()'s finally block always calls end_turn(), which
   fully revokes whatever privileges were dynamically granted to that
   agent -- UNLESS Orchestrator._active_run_id is set and the agent is in
   Orchestrator._task_grants (the F58 carry-over, only ever populated by
   begin_task()). The dashboard's /api/run handler only ever calls bare
   run_sequential() -- begin_task()/end_task() are never used anywhere in
   web_ui/server.py. So /api/grant's contract ("grant until /api/revoke")
   has no way to survive the very next /api/run: every run's default
   roster touches every TEAM agent's turn, and end_turn() silently strips
   any privilege a human explicitly, correctly approved via /api/grant --
   with no /api/revoke ever called. This reproduces with a single, solo,
   non-concurrent run; no race required.

2. DashboardGate's turn-safety issue: ThreadingHTTPServer runs each
   /api/run request on its own thread, and PrivilegeBroker._active_turn
   is one shared string with no locking. Concurrent runs whose rosters
   overlap (the default roster is always all four TEAM agents) either
   spuriously reject each other ("turn already active for X") or silently
   share one turn slot, letting one run's end_turn() strip privileges a
   different, still-in-flight run depends on.

Reproduced directly against a real ThreadingHTTPServer/Handler at the
pinned tree (mirror a43f588, F83 landed, 222 passed): granted claude WRITE
via a real approved gate, then a single solo /api/run call alone already
stripped it; separately, firing 40 concurrent /api/run calls produced 24
non-200 "turn already active" failures and also stripped the grant.

Fix:
- DashboardState._run_lock serializes /api/run execution (mirrors F83's
  _ask_lock pattern) -- eliminates the concurrent-run turn race entirely.
- DashboardState._standing_grants records what /api/grant has granted;
  /api/run restores it (human_approved=True, since this re-applies an
  already-made human decision, not a new one) after every run drains,
  regardless of whether the run raised; /api/revoke clears the record so
  an explicit revoke still sticks.
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

os.environ.setdefault("ORCA_REPO_ROOT", "/tmp/orca_f84_test_root")
os.environ.pop("ORCA_DASHBOARD_TOKEN", None)
os.environ.pop("ORCA_API_KEY", None)
os.environ.pop("MAO_API_KEY", None)

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


def test_solo_run_does_not_strip_standing_grant():
    httpd, port, st = _fresh_server()
    try:
        _grant_write_to_claude(port, st)
        assert Privilege.WRITE in st.broker._grants.get("claude", set())
        status, body = _post(port, "/api/run", {"input": "solo, no concurrency"})
        assert status == 200, body
        assert Privilege.WRITE in st.broker._grants.get("claude", set()), (
            "a single, non-concurrent /api/run must not silently strip a standing /api/grant privilege"
        )
    finally:
        httpd.shutdown()


def test_explicit_revoke_still_sticks_after_a_run():
    httpd, port, st = _fresh_server()
    try:
        _grant_write_to_claude(port, st)
        status, _ = _post(port, "/api/revoke", {"agent": "claude"})
        assert status == 200
        assert Privilege.WRITE not in st.broker._grants.get("claude", set())
        status, body = _post(port, "/api/run", {"input": "after revoke"})
        assert status == 200, body
        assert Privilege.WRITE not in st.broker._grants.get("claude", set()), (
            "an explicit /api/revoke must not be undone by the next /api/run"
        )
    finally:
        httpd.shutdown()


def test_concurrent_runs_do_not_lose_standing_grant_or_fail():
    httpd, port, st = _fresh_server()
    try:
        _grant_write_to_claude(port, st)
        n = 12
        outcomes = [None] * n

        def run_one(i):
            outcomes[i] = _post(port, "/api/run", {"input": "run " + str(i)}, timeout=20)

        threads = [
            threading.Thread(target=run_one, args=(i,), daemon=True)
            for i in range(n)
        ]
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=20)
        failures = [o for o in outcomes if o is None or o[0] != 200]
        assert not failures, "concurrent /api/run calls must not fail: " + repr(failures)
        assert Privilege.WRITE in st.broker._grants.get("claude", set()), (
            "concurrent /api/run calls must not strip a standing grant"
        )
    finally:
        httpd.shutdown()
