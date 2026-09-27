from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.client import HTTPConnection
from itertools import count
import base64
import json
import pytest

from orca import Action
from orca.control_plane import ControlPlane
from orca.fleet import Heartbeat, sign_heartbeat
from orca.web import OrcaHTTPServer, STATIC_ROOT
from orca.inventory import InventoryReadError


REQUEST_IDS = count(1)


def _operator_headers(server: OrcaHTTPServer, token: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-ORCA-Operator-Token": token,
        "Idempotency-Key": f"operator-request-{next(REQUEST_IDS):08d}",
        "X-ORCA-Expected-Revision": str(server.control_plane.state_revision),
    }


def test_operator_console_assets_exist_and_include_required_views():
    html = (STATIC_ROOT / "index.html").read_text()
    for required in ("Overview", "Work", "Approvals", "Evidence", "Incidents", "Security", "Agents", "Fleet", "Connectors", "Costs"):
        assert required in html
    assert "viewport" in html
    assert "operator-token" in html
    assert "toggle-stop" in html
    assert "cost-breakdown" in html
    assert "budget-policy" in html
    assert "security-list" in html
    assert "retention-summary" in html
    assert "generate-image" in html
    assert "Generate on CRUCIBLE" in html
    js = (STATIC_ROOT / "app.js").read_text()
    assert "data-approval" in js
    assert "data-pause-job" in js
    assert "data-job-action" in js
    assert "renderAgents" in js
    assert "stop_condition" in js
    assert "rationale" in js
    assert "/api/images/generate" in js


def test_console_mutations_reuse_one_envelope_only_for_transport_retry():
    js = (STATIC_ROOT / "app.js").read_text()

    # A logical mutation serializes its body and captures its key/revision once,
    # before either transport attempt. Every POST goes through this one helper.
    assert "function mutationEnvelope(url,payload,auth)" in js
    assert "body:JSON.stringify(payload)" in js
    assert "Object.freeze({url,body:JSON.stringify(payload),headers,key,expectedRevision})" in js
    assert "for(let attempt=0;attempt<2;attempt+=1)" in js
    assert "response=await fetch(envelope.url" in js
    assert js.count("method:'POST'") == 1

    # Once fetch returns an HTTP response, JSON/status handling is outside the
    # retry catch. HTTP rejection is surfaced and is never retried automatically.
    transport_guard = js.index("if(!response)throw lastTransportError")
    response_decode = js.index("response.json()", transport_guard)
    response_rejection = js.index("if(!response.ok)", response_decode)
    assert transport_guard < response_decode < response_rejection

    # Mutating controls and credentials are frozen in the UI until the logical
    # mutation finishes, including its one uncertainty retry.
    assert "control.disabled=mutationPending" in js
    assert "setMutationPending(true)" in js
    assert "finally{setMutationPending(false)}" in js
    assert "||mutationPending)return" in js


def test_state_endpoint_is_readable_and_truthful():
    server = OrcaHTTPServer(("127.0.0.1", 0), ControlPlane())
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f"http://127.0.0.1:{server.server_port}/api/state") as response:
            data = json.load(response)
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
        assert "img-src 'self' blob:" in response.headers["Content-Security-Policy"]
        assert data["evidence_chain_valid"] is True
        assert {a["id"] for a in data["agents"]} == {
            "orca", "smith", "quench", "security_gate", "fry"}
        assert {b["id"] for b in data["bots"]} == {
            "orca", "smith", "quench", "security_gate"}
        assert all(b["runtime_enabled"] is False for b in data["bots"])
        assert {n["id"] for n in data["nodes"]} == {"anvil", "forge", "kiln", "ember", "iris"}
        assert all(n["state"] == "unproven" for n in data["nodes"])
        assert all(c["writes_enabled"] is False for c in data["connectors"])
    finally:
        server.shutdown()
        server.server_close()


def test_forest_background_is_served_as_an_image():
    server = OrcaHTTPServer(("127.0.0.1", 0), ControlPlane())
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        with urlopen(f"http://127.0.0.1:{server.server_port}/moonlit-forest.png") as response:
            assert response.headers["Content-Type"] == "image/png"
            assert response.read(8) == b"\x89PNG\r\n\x1a\n"
    finally:
        server.shutdown()
        server.server_close()


def test_chat_keyboard_hints_and_safety_guards():
    html = (STATIC_ROOT / "index.html").read_text()
    js = (STATIC_ROOT / "app.js").read_text()
    assert "Enter to send · Shift+Enter for a new line" in html
    assert "!event.shiftKey && !event.isComposing && event.keyCode !== 229" in js
    assert "if (!event.repeat && !inferencePending)" in js
    submit = js.split("$('#prompt-form').addEventListener('submit'", 1)[1].split("});", 1)[0]
    assert submit.index("if (inferencePending || !prompt.trim()) return") < submit.index(".value = ''")


def test_chat_images_are_local_and_downloadable():
    html = (STATIC_ROOT / "index.html").read_text()
    js = (STATIC_ROOT / "app.js").read_text()
    assert 'data-mode="photo"' in html
    assert "await generateChatImage(imagePrompt)" in js
    assert "download.download = `ORCA-photo-" in js
    assert "image.alt = imagePrompt" in js
    assert "imagePrompt.length > 1500" in js
    assert "for (const url of chatImageURLs) URL.revokeObjectURL(url)" in js


def test_inventory_endpoint_is_read_only_and_fails_closed():
    class Provider:
        def snapshot(self):
            return {"ok": True, "read_only": True, "items": [{"name": "Resistor"}]}

    server = OrcaHTTPServer(
        ("127.0.0.1", 0), ControlPlane(), inventory_provider=Provider())
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f"http://127.0.0.1:{server.server_port}/api/inventory") as response:
            result = json.load(response)
        assert result["read_only"] is True
        assert result["items"][0]["name"] == "Resistor"
    finally:
        server.shutdown()
        server.server_close()

    class BrokenProvider:
        def snapshot(self):
            raise InventoryReadError("secret provider detail")

    server = OrcaHTTPServer(
        ("127.0.0.1", 0), ControlPlane(), inventory_provider=BrokenProvider())
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(HTTPError) as error:
            urlopen(f"http://127.0.0.1:{server.server_port}/api/inventory")
        assert error.value.code == 502
        assert json.load(error.value)["error"] == "inventory source is unavailable"
    finally:
        server.shutdown()
        server.server_close()


def test_loopback_console_rejects_unallowlisted_host_header():
    server = OrcaHTTPServer(("127.0.0.1", 0), ControlPlane())
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = HTTPConnection("127.0.0.1", server.server_port)
        connection.request("GET", "/api/state", headers={"Host": "attacker.example"})
        response = connection.getresponse()
        assert response.status == 421
        assert json.loads(response.read())["error"] == "host header is not allowlisted"
        connection.close()
    finally:
        server.shutdown()
        server.server_close()


def test_console_refuses_non_loopback_bind_until_transport_is_reviewed():
    for host in ("0.0.0.0", "::", "192.168.7.30", "orca.internal"):
        with pytest.raises(ValueError, match="non-loopback"):
            OrcaHTTPServer((host, 0), ControlPlane())


def test_post_mutations_are_disabled_without_operator_token():
    server = OrcaHTTPServer(("127.0.0.1", 0), ControlPlane())
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(f"http://127.0.0.1:{server.server_port}/api/jobs",
                          data=b"{}", method="POST", headers={"Content-Type": "application/json"})
        with pytest.raises(HTTPError) as error:
            urlopen(request)
        assert error.value.code == 503
    finally:
        server.shutdown()
        server.server_close()


def test_trusted_network_mode_allows_login_free_fry_inference():
    class Gateway:
        def invoke(self, **payload):
            assert payload == {
                "service_id": "forge_smith", "bot_id": "smith", "prompt": "plan"
            }
            return {"summary": "done", "evidence": [],
                    "uncertainty": "none", "next_gate": "review"}

    server = OrcaHTTPServer(
        ("127.0.0.1", 0), ControlPlane(), runtime_gateway=Gateway(),
        trusted_network_no_auth=True,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f"http://127.0.0.1:{server.server_port}/api/config") as response:
            assert json.load(response) == {
                "authentication_required": False,
                "deployment": "trusted-network",
            }
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/inference",
            data=json.dumps({
                "service_id": "forge_smith", "bot_id": "smith", "prompt": "plan"
            }).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request) as response:
            assert json.load(response)["summary"] == "done"
    finally:
        server.shutdown()
        server.server_close()


def test_inference_endpoint_is_fry_authenticated_and_schema_bounded():
    class Gateway:
        def invoke(self, **payload):
            assert payload == {
                "service_id": "forge_smith", "bot_id": "smith", "prompt": "plan"
            }
            return {"summary": "done", "evidence": ["fixture"],
                    "uncertainty": "none", "next_gate": "review"}

    token = "t" * 32
    server = OrcaHTTPServer(
        ("127.0.0.1", 0), ControlPlane(), operator_token=token,
        runtime_gateway=Gateway(),
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/api/inference"
        body = json.dumps({
            "service_id": "forge_smith", "bot_id": "smith", "prompt": "plan"
        }).encode()
        with pytest.raises(HTTPError) as unauthenticated:
            urlopen(Request(url, data=body, method="POST",
                            headers={"Content-Type": "application/json"}))
        assert unauthenticated.value.code == 401
        request = Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json", "X-ORCA-Operator-Token": token},
        )
        with urlopen(request) as response:
            assert json.load(response)["summary"] == "done"
        invalid = Request(
            url, data=json.dumps({"service_id": "forge_smith"}).encode(), method="POST",
            headers={"Content-Type": "application/json", "X-ORCA-Operator-Token": token},
        )
        with pytest.raises(HTTPError) as error:
            urlopen(invalid)
        assert error.value.code == 400
    finally:
        server.shutdown()
        server.server_close()


def test_auto_chat_is_authenticated_and_preserves_history():
    history = [{"role": "user", "content": "My project is Cedar."}]
    class Gateway:
        def chat(self, **payload):
            assert payload == {"prompt": "What is its name?", "history": history}
            return {"mode": "reason", "result": {"summary": "Cedar"}}

    token = "t" * 32
    server = OrcaHTTPServer(("127.0.0.1", 0), ControlPlane(),
                           operator_token=token, runtime_gateway=Gateway())
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/api/chat"
        payload = {"prompt": "What is its name?", "history": history}
        headers = {"Content-Type": "application/json"}
        with pytest.raises(HTTPError) as denied:
            urlopen(Request(url, data=json.dumps(payload).encode(), headers=headers))
        assert denied.value.code == 401
        headers["X-ORCA-Operator-Token"] = token
        with urlopen(Request(url, data=json.dumps(payload).encode(), headers=headers)) as response:
            assert json.load(response)["result"]["summary"] == "Cedar"
        payload["approved"] = True
        with pytest.raises(HTTPError) as invalid:
            urlopen(Request(url, data=json.dumps(payload).encode(), headers=headers))
        assert invalid.value.code == 400
    finally:
        server.shutdown()
        server.server_close()


def test_memory_endpoint_is_authenticated_and_retrieved_in_chat(tmp_path):
    from orca.chat_memory import ChatMemory
    memory = ChatMemory(tmp_path / 'memory.db')
    class Gateway:
        def chat(self, **payload):
            assert any('Cedar' in m['content'] for m in payload['history'])
            return {'mode': 'reason', 'result': {'summary': 'Cedar'}}
    token = 't' * 32
    server = OrcaHTTPServer(('127.0.0.1', 0), ControlPlane(), operator_token=token,
                           runtime_gateway=Gateway(), chat_memory=memory)
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f'http://127.0.0.1:{server.server_port}'
        body = json.dumps({'request_id': 'request-one', 'messages': [
            {'role': 'user', 'content': 'My telescope project is Cedar.'}]}).encode()
        headers = {'Content-Type': 'application/json'}
        with pytest.raises(HTTPError) as denied:
            urlopen(Request(base + '/api/memory', data=body, headers=headers))
        assert denied.value.code == 401
        headers['X-ORCA-Operator-Token'] = token
        with urlopen(Request(base + '/api/memory', data=body, headers=headers)) as response:
            assert json.load(response)['capacity'] == 300000
        with urlopen(Request(base + '/api/chat', data=json.dumps({
                'prompt': 'What is the telescope project?', 'history': []}).encode(), headers=headers)) as response:
            assert json.load(response)['result']['summary'] == 'Cedar'
    finally:
        server.shutdown()
        server.server_close()
        memory.close()


def test_signed_heartbeat_endpoint_authenticates_without_operator_token():
    control = ControlPlane()
    key = b"kiln-live-heartbeat-key-material-000001"
    control.enroll_node("kiln", actor="fry", key=key)
    server = OrcaHTTPServer(("127.0.0.1", 0), control)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        heartbeat = Heartbeat("kiln", int(__import__("time").time()), 1, "healthy", "models healthy")
        payload = json.dumps({
            "heartbeat": heartbeat.__dict__,
            "signature": sign_heartbeat(heartbeat, key),
            "key": base64.b64encode(key).decode("ascii"),
        }).encode()
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/heartbeats",
            data=payload, method="POST", headers={"Content-Type": "application/json"})
        with urlopen(request) as response:
            result = json.load(response)
        assert result == {"accepted": True, "node_id": "kiln", "nonce": 1,
                          "status": "accepted"}
        assert control.node_health["kiln"]["state"] == "healthy"

        with pytest.raises(HTTPError) as replay:
            urlopen(request)
        assert replay.value.code == 400
    finally:
        server.shutdown()
        server.server_close()


def test_post_mutations_require_exact_operator_token():
    token = "t" * 32
    server = OrcaHTTPServer(("127.0.0.1", 0), ControlPlane(), operator_token=token)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/api/control/emergency-stop"
        body = json.dumps({"actor": "fry", "active": True, "reason": "test"}).encode()
        bad = Request(url, data=body, method="POST",
                      headers={"Content-Type": "application/json", "X-ORCA-Operator-Token": "wrong"})
        with pytest.raises(HTTPError) as error:
            urlopen(bad)
        assert error.value.code == 401
        good = Request(url, data=body, method="POST",
                       headers=_operator_headers(server, token))
        with urlopen(good) as response:
            assert json.load(response)["emergency_stop"] is True

        malformed = Request(
            url, data=json.dumps({"actor": "fry", "active": "false", "reason": "bad type"}).encode(),
            method="POST",
            headers=_operator_headers(server, token))
        with pytest.raises(HTTPError) as error:
            urlopen(malformed)
        assert error.value.code == 400
        assert server.control_plane.emergency_stop is True

        # Resume is an authenticated mutation, and even a valid token cannot
        # override an active stop. Releasing the stop alone does not resume.
        job = server.control_plane.submit(
            title="resume HTTP fixture", lane="orca", requested_by="orca",
            assigned_to="smith", action=Action("read", "fixture"))
        resume_url = f"http://127.0.0.1:{server.server_port}/api/jobs/{job.id}/resume"
        resume_body = json.dumps({"actor": "fry", "reason": "HTTP fixture"}).encode()
        # The API represents policy/state denials as 400, authentication as 401.
        for supplied, expected_status in (("wrong", 401), (token, 400)):
            headers = (
                _operator_headers(server, token)
                if supplied == token
                else {"Content-Type": "application/json",
                      "X-ORCA-Operator-Token": supplied}
            )
            request = Request(
                resume_url, data=resume_body, method="POST",
                headers=headers)
            with pytest.raises(HTTPError) as error:
                urlopen(request)
            assert error.value.code == expected_status
            if supplied == token:
                assert "control boundary" in json.loads(error.value.read())["error"]
            assert job.status.value == "paused"
        release = Request(
            url, data=json.dumps({"actor": "fry", "active": False, "reason": "resume fixture"}).encode(),
            method="POST",
            headers=_operator_headers(server, token))
        with urlopen(release) as response:
            assert json.load(response)["emergency_stop"] is False
        assert job.status.value == "paused"
        resume = Request(
            resume_url, data=resume_body, method="POST",
            headers=_operator_headers(server, token))
        with urlopen(resume) as response:
            assert json.load(response)["status"] == "ready"
    finally:
        server.shutdown()
        server.server_close()


def test_authenticated_advisory_security_and_retention_controls():
    token = "t" * 32
    server = OrcaHTTPServer(("127.0.0.1", 0), ControlPlane(), operator_token=token)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        secret = "xai-abcdefghijklmnopqrstuv"
        body = json.dumps({
            "author": "smith", "lane": "orca",
            "artifacts": {"settings.env": f"api_key={secret}"},
        }).encode()
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/security/scan",
            data=body, method="POST",
            headers=_operator_headers(server, token),
        )
        with urlopen(request) as response:
            payload = json.load(response)
        assert payload["disposition"] == "block_and_escalate"
        assert secret not in str(payload)
        retention = Request(
            f"http://127.0.0.1:{server.server_port}/api/governance/retention-audit",
            data=json.dumps({"actor": "fry"}).encode(), method="POST",
            headers=_operator_headers(server, token),
        )
        with urlopen(retention) as response:
            retention_payload = json.load(response)
        assert retention_payload["mode"] == "dry_run"
        assert retention_payload["automatic_deletions"] == 0
        assert server.control_plane.evidence.verify()
    finally:
        server.shutdown()
        server.server_close()


def test_operator_token_and_json_envelope_are_strict():
    with pytest.raises(ValueError, match="32-512"):
        OrcaHTTPServer(("127.0.0.1", 0), ControlPlane(), operator_token="short")

    token = "t" * 32
    server = OrcaHTTPServer(("127.0.0.1", 0), ControlPlane(), operator_token=token)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/jobs",
            data=b"[]", method="POST",
            headers={"Content-Type": "application/json", "X-ORCA-Operator-Token": token},
        )
        with pytest.raises(HTTPError) as error:
            urlopen(request)
        assert error.value.code == 400
        assert "JSON object" in json.loads(error.value.read())["error"]

        stop_url = f"http://127.0.0.1:{server.server_port}/api/control/emergency-stop"
        missing_envelope = Request(
            stop_url,
            data=json.dumps({"actor": "fry", "active": True, "reason": "fixture"}).encode(),
            method="POST",
            headers={"Content-Type": "application/json",
                     "X-ORCA-Operator-Token": token},
        )
        with pytest.raises(HTTPError) as error:
            urlopen(missing_envelope)
        assert error.value.code == 428

        impersonation = Request(
            stop_url,
            data=json.dumps({"actor": "orca", "active": True,
                             "reason": "must remain Fry"}).encode(),
            method="POST",
            headers=_operator_headers(server, token),
        )
        with pytest.raises(HTTPError) as error:
            urlopen(impersonation)
        assert error.value.code == 403
        assert server.control_plane.emergency_stop is False
    finally:
        server.shutdown()
        server.server_close()


def test_integrity_failure_makes_state_and_health_unavailable():
    control = ControlPlane()
    control.submit(title="proof", lane="orca", requested_by="orca",
                   assigned_to="smith", action=Action("read", "fixture"))
    control.evidence.db.execute("DROP TRIGGER events_no_update")
    control.evidence.db.execute("UPDATE events SET payload='{}' WHERE seq=1")
    control.evidence.db.commit()
    server = OrcaHTTPServer(("127.0.0.1", 0), control)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for path in ("/api/state", "/api/health"):
            with pytest.raises(HTTPError) as error:
                urlopen(f"http://127.0.0.1:{server.server_port}{path}")
            assert error.value.code == 503
    finally:
        server.shutdown()
        server.server_close()
