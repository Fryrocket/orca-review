from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
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
from orca.inbox import InboxStore


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
    assert 'id="cancel-chat-generation"' in html
    assert "cancelMediaGeneration" in js
    assert "Generation canceled. Change the prompt" in js


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
        assert "media-src 'self' blob:" in response.headers["Content-Security-Policy"]
        assert data["evidence_chain_valid"] is True
        assert {a["id"] for a in data["agents"]} == {
            "orca", "smith", "quench", "security_gate", "fry"}
        assert {b["id"] for b in data["bots"]} == {
            "orca", "smith", "quench", "security_gate"}
        assert all(b["runtime_enabled"] is False for b in data["bots"])
        assert {n["id"] for n in data["nodes"]} == {"anvil", "forge", "kiln", "ember", "temper"}
        assert all(n["state"] == "unproven" for n in data["nodes"])
        assert all(c["writes_enabled"] is False for c in data["connectors"])
    finally:
        server.shutdown()
        server.server_close()


def test_concurrent_health_state_and_business_reads_share_sqlite_safely():
    server = OrcaHTTPServer(("127.0.0.1", 0), ControlPlane())
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    paths = ("/api/health", "/api/state", "/api/business/state")

    def read(index):
        with urlopen(
            f"http://127.0.0.1:{server.server_port}{paths[index % len(paths)]}",
            timeout=10,
        ) as response:
            payload = json.load(response)
            return response.status, payload

    try:
        with ThreadPoolExecutor(max_workers=24) as pool:
            results = list(pool.map(read, range(600)))
        assert all(status == 200 for status, _ in results)
        assert all("error" not in payload for _, payload in results)
        assert server.control_plane.evidence.verify() is True
        assert server.control_plane.state_store.verify_integrity() is True
    finally:
        server.shutdown()
        server.server_close()


def test_bright_twilight_forest_background_is_served_as_an_image():
    server = OrcaHTTPServer(("127.0.0.1", 0), ControlPlane())
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        with urlopen(
            f"http://127.0.0.1:{server.server_port}/moonlit-forest-twilight-bright.png"
        ) as response:
            assert response.headers["Content-Type"] == "image/png"
            assert response.read(8) == b"\x89PNG\r\n\x1a\n"
        css = (STATIC_ROOT / "app.css").read_text()
        assert "url('/moonlit-forest-twilight-bright.png')" in css
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
    assert "width: 1024, height: 1024, steps: 28" in js
    assert "Edit in Canvas" in js
    assert "id=\"image-quality\"" in html
    assert "id=\"image-seed\"" in html
    assert "for (const url of chatImageURLs) URL.revokeObjectURL(url)" in js


def test_crucible_video_is_available_in_chat_and_canvas():
    html = (STATIC_ROOT / "index.html").read_text()
    js = (STATIC_ROOT / "app.js").read_text()
    assert 'data-mode="video"' in html
    assert 'id="video-prompt"' in html
    assert 'id="generate-video"' in html
    assert 'id="animate-canvas"' in html
    assert 'id="generated-video"' in html
    assert "'/api/videos/generate'" in js
    assert "'/api/videos/animate'" in js
    assert "await generateChatVideo(videoPrompt)" in js
    assert "Save MP4" in js
    assert "URL.revokeObjectURL(generatedVideoURL)" in js
    assert "cancel-video-generation" in js
    assert "cancel-image-generation" in js


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
        with urlopen(
                f"http://127.0.0.1:{server.server_port}/api/inventory/analysis") as response:
            analyzed = json.load(response)
        assert analyzed["snapshot"]["read_only"] is True
        assert analyzed["analysis"]["read_only"] is True
        assert analyzed["analysis"]["metrics"]["records"] == 1
        assert analyzed["analysis"]["controls"]["stock_changes"] == "disabled"
    finally:
        server.shutdown()
        server.server_close()


def test_edge_inference_endpoint_reports_accepted_camera_and_execution_gates():
    server = OrcaHTTPServer(("127.0.0.1", 0), ControlPlane())
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(
                f"http://127.0.0.1:{server.server_port}/api/edge-inference") as response:
            result = json.load(response)
        assert result["node_id"] == "temper"
        assert result["camera"]["state"] == "accepted_available"
        assert result["runtime"]["automatic_execution"] is False
        assert all(model["state"] == "runtime_benchmarked" for model in result["models"])
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


def test_business_chat_creates_tracked_job_and_records_result_for_review():
    class Gateway:
        def __init__(self):
            self.calls = 0

        def chat(self, **payload):
            self.calls += 1
            assert payload["prompt"] == "Research connector health"
            return {
                "mode": "reason",
                "result": {"summary": "Checked", "evidence": [],
                           "uncertainty": "none", "next_gate": "review"},
            }

    control = ControlPlane()
    gateway = Gateway()
    server = OrcaHTTPServer(
        ("127.0.0.1", 0), control, runtime_gateway=gateway,
        trusted_network_no_auth=True,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        create = Request(
            f"http://127.0.0.1:{server.server_port}/api/business/workflows",
            data=json.dumps({
                "workflow_id": "business-01-connector-health",
                "title": "Connector health",
            }).encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Idempotency-Key": "business-workflow-request-0001",
                "X-ORCA-Expected-Revision": str(control.state_revision),
            },
        )
        with urlopen(create) as response:
            job = json.load(response)
        assert response.status == 201
        assert job["status"] == "running"
        assert job["task_type"] == "business_workflow"

        chat = Request(
            f"http://127.0.0.1:{server.server_port}/api/chat",
            data=json.dumps({
                "prompt": "Research connector health",
                "history": [],
                "business_job_id": job["id"],
            }).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urlopen(chat) as response:
            result = json.load(response)
        assert result["result"]["summary"] == "Checked"
        tracked = control.jobs[job["id"]]
        assert tracked.status.value == "review"
        assert tracked.reviewer == "quench"
        events = control.evidence.list(correlation_id=tracked.correlation_id, limit=20)
        assert any(event["kind"] == "business.workflow.result" for event in events)

        duplicate = Request(
            f"http://127.0.0.1:{server.server_port}/api/chat",
            data=json.dumps({
                "prompt": "Research connector health",
                "history": [],
                "business_job_id": job["id"],
            }).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(HTTPError) as error:
            urlopen(duplicate)
        assert error.value.code == 400
        assert "not running" in json.loads(error.value.read())["error"]
        assert gateway.calls == 1
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


def test_inventory_vision_planning_endpoint_is_authenticated_and_non_executing():
    token = "t" * 32
    server = OrcaHTTPServer(
        ("127.0.0.1", 0), ControlPlane(), operator_token=token)
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        payload = {
            "name": "Bench vision", "version": "1.0",
            "labels": [{"id": "CAP-100", "sku": "CAP-100",
                        "name": "100 uF capacitor", "barcode": "CAP100"}],
            "source": "Owner-captured test fixtures", "license_name": "Owner-controlled",
            "target_images_per_label": 50, "session_id": "TEST-CAPTURE-1",
            "camera_profile": "TEMPER USB test camera",
        }
        url = f"http://127.0.0.1:{server.server_port}/api/temper/inventory-dataset/plan"
        request = Request(
            url, data=json.dumps(payload).encode(), method="POST",
            headers={"Content-Type": "application/json",
                     "X-ORCA-Operator-Token": token})
        with urlopen(request) as response:
            planned = json.load(response)
        assert planned["read_only"] is True
        assert planned["external_actions"] == 0
        assert planned["manifest"]["may_train"] is False
        assert planned["capture_plan"]["frames_planned"] == 50
        assert planned["capture_plan"]["frames_captured"] == 0
        assert planned["capture_plan"]["may_open_camera"] is False
    finally:
        server.shutdown()
        server.server_close()


def test_inbox_import_and_read_require_owner_auth_and_store_summaries_only():
    token = "t" * 32
    store = InboxStore(":memory:")
    server = OrcaHTTPServer(
        ("127.0.0.1", 0), ControlPlane(), operator_token=token,
        inbox_store=store,
    )
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/api/inbox"
        with pytest.raises(HTTPError) as unauthenticated:
            urlopen(url)
        assert unauthenticated.value.code == 401
        payload = {
            "request_id": "inbox-request-0001",
            "handoff_id": "muse-email-test123",
            "messages": [{
                "message_reference": "mail-001",
                "sender_display": "Example Vendor",
                "subject": "Invoice question",
                "received_at": "2026-10-01T12:00:00Z",
                "project_or_customer": "QuasarVolt",
                "category": "invoice",
                "priority": "normal",
                "summary": "The vendor asked which purchase order applies.",
                "follow_up": "Confirm the purchase order after review.",
                "deadline": None,
                "draft_reply": "Draft response for owner review.",
                "uncertainty": "The purchase order is not in the summary.",
            }],
        }
        request = Request(
            url + "/import", data=json.dumps(payload).encode(), method="POST",
            headers={"Content-Type": "application/json",
                     "X-ORCA-Operator-Token": token},
        )
        with urlopen(request) as response:
            result = json.load(response)
        assert result["imported"] == 1
        request = Request(url, headers={"X-ORCA-Operator-Token": token})
        with urlopen(request) as response:
            snapshot = json.load(response)
        assert snapshot["count"] == 1
        assert snapshot["messages"][0]["subject"] == "Invoice question"
        assert snapshot["raw_bodies_stored"] is False
        assert snapshot["attachments_stored"] is False
        assert snapshot["mailbox_mutations"] == 0
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/communications",
            headers={"X-ORCA-Operator-Token": token},
        )
        with urlopen(request) as response:
            communications = json.load(response)
        assert communications["counts"]["messages"] == 1
        assert communications["counts"]["follow_ups"] == 1
        assert communications["controls"]["mailbox_mutations"] == 0
        assert communications["controls"]["messages_sent"] == 0
        assert communications["controls"]["calendar_writes"] == 0
    finally:
        server.shutdown()
        server.server_close()


def test_solo_operator_catalog_and_action_plan_are_bounded_and_inert():
    token = "t" * 32
    server = OrcaHTTPServer(
        ("127.0.0.1", 0), ControlPlane(), operator_token=token,
    )
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/api/solo-operator/system"
        with urlopen(url) as response:
            catalog = json.load(response)
        assert catalog["module_count"] == 12
        assert catalog["external_actions"] == 0
        payload = {"signals": [{
            "source_id": "test-approval-1", "source": "simulation",
            "kind": "approval", "summary": "Review the disposable test",
            "priority": "high", "due_at": None, "workspace": "operations",
            "owner": "fry", "evidence": "fixture:test-1", "approval_required": True,
        }]}
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/solo-operator/action-plan",
            data=json.dumps(payload).encode(), method="POST",
            headers={"Content-Type": "application/json", "X-ORCA-Operator-Token": token},
        )
        with urlopen(request) as response:
            plan = json.load(response)
        assert plan["state"] == "owner_review_required"
        assert plan["external_actions"] == 0
        assert plan["jobs_created"] == 0
        assert plan["records_mutated"] == 0
        snapshot_payload = {"records": [{
            "record_id": "case-1", "module": "case_manager",
            "title": "Review disposable case", "status": "open",
            "priority": "high", "owner": "orca", "due_at": None,
            "source": "simulation", "evidence": "fixture:case-1",
            "related_ids": [], "approval_required": True,
            "untrusted": False,
        }]}
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/solo-operator/snapshot",
            data=json.dumps(snapshot_payload).encode(), method="POST",
            headers={"Content-Type": "application/json", "X-ORCA-Operator-Token": token},
        )
        with urlopen(request) as response:
            snapshot = json.load(response)
        assert snapshot["room_count"] == 12
        assert snapshot["rooms"]["case_manager"][0]["record_id"] == "case-1"
        assert snapshot["external_actions"] == snapshot["records_mutated"] == 0
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
            payload = json.load(response)
            assert payload['capacity'] == 50_000_000
            assert payload['capacity_lines'] == 50_000_000
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
