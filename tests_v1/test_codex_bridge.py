from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import json

import pytest

from orca.codex_bridge import CodexBridgeServer, _validated_request, run_codex


def request_payload():
    return {
        "model": "ORCA-CODEX", "stream": False,
        "messages": [{"role": "system", "content": "Answer safely."},
                     {"role": "user", "content": "Hello"}],
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "answer", "strict": True, "schema": {
                "type": "object", "properties": {"summary": {"type": "string"}},
                "required": ["summary"], "additionalProperties": False}}},
    }


def test_codex_bridge_request_is_bounded_and_model_allowlisted():
    prompt, schema = _validated_request(request_payload())
    assert "<user>\nHello\n</user>" in prompt
    assert "no tools were executed" in prompt
    assert schema["required"] == ["summary"]
    for mutation, message in [({"model": "anything"}, "allowlisted"),
                              ({"stream": True}, "streaming")]:
        payload = request_payload() | mutation
        error = PermissionError if "model" in mutation else ValueError
        with pytest.raises(error, match=message):
            _validated_request(payload)


def test_run_codex_uses_stdin_read_only_ephemeral_and_schema(tmp_path, monkeypatch):
    calls = []
    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        output = Path(command[command.index("--output-last-message") + 1])
        output.write_text('{"summary":"hello"}')
        return type("Completed", (), {"returncode": 0})()
    monkeypatch.setattr("orca.codex_bridge.subprocess.run", fake_run)
    result = run_codex(codex="/usr/bin/codex", workspace=tmp_path / "work",
                       prompt="private prompt", schema={"type": "object"},
                       timeout_seconds=60)
    assert json.loads(result) == {"summary": "hello"}
    command, kwargs = calls[0]
    assert "private prompt" not in command
    assert kwargs["input"] == "private prompt"
    assert "--ephemeral" in command and "read-only" in command
    assert "--output-schema" in command


def test_bridge_health_and_failed_execution_are_generic(tmp_path, monkeypatch):
    server = CodexBridgeServer(("127.0.0.1", 0), codex="codex",
                               workspace=tmp_path, timeout_seconds=30)
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        with urlopen(f"http://127.0.0.1:{server.server_port}/health") as response:
            assert json.load(response)["status"] == "healthy"
        monkeypatch.setattr("orca.codex_bridge.run_codex",
                            lambda **_: (_ for _ in ()).throw(RuntimeError("unavailable")))
        request = Request(
            f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
            data=json.dumps(request_payload()).encode(), method="POST",
            headers={"Content-Type": "application/json"})
        with pytest.raises(HTTPError) as error:
            urlopen(request)
        assert error.value.code == 502
        assert json.load(error.value)["error"] == "unavailable"
    finally:
        server.shutdown(); server.server_close()
