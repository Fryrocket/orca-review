from http.client import HTTPConnection
from http.server import HTTPServer
import re
from threading import Thread
from urllib.parse import urlencode

import pytest

from mao.errors import OrcaConfigError
from mao.human import GateDecision
from mao.web_gate import WebHumanGate


def test_human_gate_cannot_bind_to_lan():
    with pytest.raises(OrcaConfigError, match="loopback"):
        WebHumanGate(host="192.168.7.30")


def test_human_gate_rejects_cross_site_decision_and_accepts_current_form():
    gate = WebHumanGate(port=0)
    gate._payload = {"task": "fixture"}
    server = HTTPServer(("127.0.0.1", 0), gate._make_handler())
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    try:
        connection.request("GET", "/", headers={"Host": "untrusted.example"})
        response = connection.getresponse()
        response.read()
        assert response.status == 421
        connection.request("POST", "/decide", body="decision=approve",
                           headers={"Content-Type": "application/x-www-form-urlencoded"})
        response = connection.getresponse()
        response.read()
        assert response.status == 403
        assert gate._result is None
        connection.request("GET", "/")
        response = connection.getresponse()
        html = response.read().decode()
        token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        connection.request("POST", "/decide", body=urlencode({"decision": "approve", "csrf_token": token}),
                           headers={"Content-Type": "application/x-www-form-urlencoded"})
        response = connection.getresponse()
        response.read()
        assert response.status == 200
        assert gate._result.decision is GateDecision.APPROVE
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
