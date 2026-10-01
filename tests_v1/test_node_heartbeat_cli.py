import io
import json

import pytest

from scripts import kiln_heartbeat_agent as node_agent


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return io.BytesIO(json.dumps(self.payload).encode())

    def __exit__(self, *args):
        return False


@pytest.mark.parametrize(
    "payload",
    [{"status": "healthy"}, {"status": "pass"}, {"data": [{"id": "model"}]}],
)
def test_health_check_accepts_control_plane_or_model_inventory(monkeypatch, payload):
    monkeypatch.setattr(node_agent, "urlopen", lambda *args, **kwargs: FakeResponse(payload))
    node_agent.check_endpoint("http://127.0.0.1/health")


@pytest.mark.parametrize("payload", [{}, {"status": "unhealthy"}, {"data": []}, []])
def test_health_check_rejects_missing_capacity(monkeypatch, payload):
    monkeypatch.setattr(node_agent, "urlopen", lambda *args, **kwargs: FakeResponse(payload))
    with pytest.raises(RuntimeError, match="health endpoint"):
        node_agent.check_endpoint("http://127.0.0.1/health")


def test_cli_supports_all_three_node_profiles():
    parser = node_agent.build_parser()
    args = parser.parse_args([
        "--node-id", "forge",
        "--key-file", "/private/key",
        "--state-file", "/private/state",
        "--check-url", "http://127.0.0.1/api/health",
    ])
    assert args.node_id == "forge"
    assert args.check_url == ["http://127.0.0.1/api/health"]
