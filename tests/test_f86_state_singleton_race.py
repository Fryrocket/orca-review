"""R11-F86 — mao.web_ui.server._state() is an unlocked lazy singleton;
a burst of concurrent first requests can each construct their own
DashboardState, and every one but the last is silently orphaned.

_state() was:

    def _state() -> DashboardState:
        global STATE
        if STATE is None:
            STATE = DashboardState()
        return STATE

ThreadingHTTPServer dispatches every request on its own thread. A burst of
concurrent requests hitting a freshly-started dashboard -- several browser
tabs loading at once, a health-check racing a real request, anything that
fires more than one request before the server has served its first one --
can all observe `STATE is None` before any of them finishes constructing
DashboardState, so more than one gets built. Whichever assignment runs
last "wins" the module-level STATE; every other thread already has its
own `st = _state()` reference for the rest of that HTTP request and keeps
using it. A request that landed on a losing instance -- e.g. /api/grant --
mutates a PrivilegeBroker nobody else will ever see again, then returns a
misleading `200 {"ok": true}`: the grant silently never took effect
anywhere any subsequent request can observe.

Reproduced directly against the pinned tree (mirror 89d15f9, F85 landed,
227 passed): 30 concurrent first calls to _state() produced 3 distinct
DashboardState instances (not just 2 -- confirming this isn't a one-off
double-init but a genuinely racy window), and most callers held a
reference that did not match the module's final STATE.

Fix: standard double-checked locking with a module-level threading.Lock.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("ORCA_REPO_ROOT", str(Path(__file__).resolve().parents[1]))
os.environ.pop("ORCA_API_KEY", None)
os.environ.pop("MAO_API_KEY", None)

import mao.web_ui.server as server_mod  # noqa: E402


def test_concurrent_first_calls_construct_exactly_one_state():
    server_mod.STATE = None

    results = []
    lock = threading.Lock()

    def get_state():
        st = server_mod._state()
        with lock:
            results.append(st)

    threads = [threading.Thread(target=get_state) for _ in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(results) == 30
    distinct = {id(r) for r in results}
    assert len(distinct) == 1, (
        f"expected exactly one DashboardState across 30 concurrent first "
        f"calls, got {len(distinct)} distinct instances"
    )
    assert all(r is server_mod.STATE for r in results), (
        "every caller must receive the same instance that ends up as the "
        "module-level STATE -- otherwise a caller's mutations are silently "
        "invisible to everyone else"
    )


def test_state_is_stable_across_sequential_calls():
    """Regression guard: normal, non-racing repeated calls still return
    the same cached instance (no accidental re-construction from the
    lock itself)."""
    server_mod.STATE = None
    first = server_mod._state()
    second = server_mod._state()
    third = server_mod._state()
    assert first is second is third
