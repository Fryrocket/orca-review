"""R11-F81 ("web gate HTML injection").

WebHumanGate.do_GET() embedded context and json.dumps(payload) in a
raw HTML f-string. json.dumps does not HTML-escape < > &, so a payload
containing </pre><script>...</script> injected live script with
same-origin access to POST /decide — the gate could approve itself.

Fix: html.escape() both context and the serialized payload before
embedding.
"""
from __future__ import annotations

import http.client
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mao.human import GateDecision
from mao.web_gate import WebHumanGate


def _start(payload, context):
    gate = WebHumanGate(host="127.0.0.1", port=0, timeout_sec=3)
    box = {}

    def run():
        try:
            box["result"] = gate.ask(payload, context=context)
        except Exception as e:
            box["error"] = e

    t = threading.Thread(target=run, daemon=True)
    t.start()
    deadline = time.time() + 2
    while gate._server is None and time.time() < deadline:
        time.sleep(0.01)
    assert gate._server is not None, "WebHumanGate server never started"
    time.sleep(0.02)
    return gate, t, box


def _get(port):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    conn.request("GET", "/")
    resp = conn.getresponse()
    body = resp.read().decode()
    conn.close()
    return resp.status, body


def _post_decide(port, decision="approve", note=""):
    raw = urlencode({"decision": decision, "note": note})
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    conn.request(
        "POST",
        "/decide",
        body=raw.encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp = conn.getresponse()
    resp.read()
    conn.close()
    return resp.status


def test_script_in_payload_is_not_served_as_live_markup():
    payload = {"task": "</pre><script>alert(1)</script>"}
    gate, t, box = _start(payload, context="review")
    try:
        status, html = _get(gate.port)
        assert status == 200
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        _post_decide(gate.port, "skip")
        t.join(timeout=3)
    finally:
        if gate._server:
            try:
                gate._server.server_close()
            except Exception:
                pass
        gate._event.set()


def test_script_in_context_is_not_served_as_live_markup():
    gate, t, box = _start({"task": "ok"}, context='<img onerror=alert(1) src=x>')
    try:
        status, html = _get(gate.port)
        assert status == 200
        assert "<img onerror=" not in html
        assert "&lt;img onerror=alert(1) src=x&gt;" in html
        _post_decide(gate.port, "skip")
        t.join(timeout=3)
    finally:
        if gate._server:
            try:
                gate._server.server_close()
            except Exception:
                pass
        gate._event.set()


def test_normal_approve_flow_is_unaffected():
    gate, t, box = _start({"task": "plain text"}, context="normal review")
    try:
        status, html = _get(gate.port)
        assert status == 200
        assert "plain text" in html
        assert "normal review" in html
        _post_decide(gate.port, "approve", note="looks good")
        t.join(timeout=3)
        assert "error" not in box, box.get("error")
        result = box["result"]
        assert result.decision == GateDecision.APPROVE
        assert result.note == "looks good"
        assert result.content == {"task": "plain text"}
    finally:
        if gate._server:
            try:
                gate._server.server_close()
            except Exception:
                pass
        gate._event.set()
