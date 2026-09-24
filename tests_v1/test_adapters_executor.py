import pytest

from orca.adapters import (
    ReadOnlyAdapter,
    ReadRequest,
    ReadResponseError,
    ReadTransportError,
    provider_adapter,
)
from orca.control_plane import ControlPlane
from orca.executor import CommandSpec, ScopedNodeExecutor
from orca.workflow import AdvisoryWorkflow


def test_read_adapter_uses_get_and_allowlisted_origin_only():
    calls = []
    adapter = ReadOnlyAdapter("gitea", ("https://forge.example",),
                              lambda method, url: calls.append((method, url)) or {"ok": True})
    result = adapter.read(ReadRequest("gitea", "https://forge.example", "/api/v1/repos"))
    assert result == {"ok": True}
    assert calls == [("GET", "https://forge.example/api/v1/repos")]
    with pytest.raises(PermissionError, match="origin"):
        adapter.read(ReadRequest("gitea", "https://evil.example", "/api/v1/repos"))
    with pytest.raises(PermissionError, match="canonical"):
        adapter.read(ReadRequest("gitea", "https://forge.example", "/../secret"))
    with pytest.raises(PermissionError, match="canonical"):
        adapter.read(ReadRequest("gitea", "https://forge.example", "/api/%2e%2e/secret"))
    with pytest.raises(PermissionError, match="canonical"):
        adapter.read(ReadRequest("gitea", "https://forge.example", "/api/%252e%252e/secret"))
    with pytest.raises(PermissionError, match="canonical"):
        adapter.read(ReadRequest("gitea", "https://forge.example", "/api/v1/repos?token=unsafe"))
    with pytest.raises(PermissionError, match="canonical"):
        adapter.read(ReadRequest("gitea", "https://forge.example", "//evil.example/secret"))


def test_read_adapter_redacts_provider_data_before_returning_it():
    secret = "sk-abcdefghijklmnop"
    adapter = ReadOnlyAdapter(
        "drive", ("https://drive.example",),
        lambda *_: {
            "token": "opaque123",
            "password": "shortpass",
            "nested": {"access_token": "not-pattern-shaped", secret: secret},
        },
    )
    result = adapter.read(ReadRequest(
        "drive", "https://drive.example", "/files"))
    assert result["token"] == "[REDACTED]"
    assert result["password"] == "[REDACTED]"
    assert result["nested"]["access_token"] == "[REDACTED]"
    assert secret not in str(result)


def test_secret_named_fields_are_still_validated_against_response_bounds():
    adapter = ReadOnlyAdapter(
        "drive", ("https://drive.example",),
        lambda *_: {"token": "x" * 30},
        max_response_bytes=20,
    )
    with pytest.raises(ReadResponseError, match="byte limit"):
        adapter.read(ReadRequest("drive", "https://drive.example", "/files"))


def test_read_adapter_bounds_and_validates_provider_responses():
    request = ReadRequest("drive", "https://drive.example", "/files")
    oversized = ReadOnlyAdapter(
        "drive", ("https://drive.example",), lambda *_: {"value": "x" * 20},
        max_response_bytes=10,
    )
    with pytest.raises(ReadResponseError, match="byte limit"):
        oversized.read(request)

    too_many = ReadOnlyAdapter(
        "drive", ("https://drive.example",), lambda *_: [1, 2, 3],
        max_response_items=3,
    )
    with pytest.raises(ReadResponseError, match="item limit"):
        too_many.read(request)

    too_deep = ReadOnlyAdapter(
        "drive", ("https://drive.example",), lambda *_: [[[]]],
        max_response_depth=1,
    )
    with pytest.raises(ReadResponseError, match="depth limit"):
        too_deep.read(request)

    cyclic = []
    cyclic.append(cyclic)
    cycle_adapter = ReadOnlyAdapter(
        "drive", ("https://drive.example",), lambda *_: cyclic,
    )
    with pytest.raises(ReadResponseError, match="cycle"):
        cycle_adapter.read(request)

    non_json = ReadOnlyAdapter(
        "drive", ("https://drive.example",), lambda *_: {"bad": object()},
    )
    with pytest.raises(ReadResponseError, match="JSON-compatible"):
        non_json.read(request)

    colliding_keys = ReadOnlyAdapter(
        "drive", ("https://drive.example",),
        lambda *_: {"token=abcdefgh": 1, "password=abcdefgh": 2},
    )
    with pytest.raises(ReadResponseError, match="collide"):
        colliding_keys.read(request)


def test_read_adapter_sanitizes_transport_failures():
    secret = "sk-abcdefghijklmnop"

    def fail(*_):
        raise RuntimeError(f"provider leaked {secret}")

    adapter = ReadOnlyAdapter("drive", ("https://drive.example",), fail)
    with pytest.raises(ReadTransportError) as captured:
        adapter.read(ReadRequest("drive", "https://drive.example", "/files"))
    assert secret not in str(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_scoped_executor_validates_but_never_executes():
    executor = ScopedNodeExecutor({"forge": ("192.168.7.30",)})
    command = CommandSpec("service status", "/usr/bin/systemctl", ("status", "gitea"))
    executor.validate_target("forge", "192.168.7.30")
    executor.validate_command(command)
    with pytest.raises(PermissionError, match="execution is disabled"):
        executor.execute("forge", "192.168.7.30", command)
    with pytest.raises(PermissionError, match="transport target"):
        executor.execute("forge", "10.0.0.2", command)
    with pytest.raises(PermissionError, match="allowlist"):
        executor.validate_command(CommandSpec("shell", "/bin/sh", ("-c", "id")))
    with pytest.raises(PermissionError, match="mutating"):
        executor.validate_command(CommandSpec("restart", "/usr/bin/systemctl", ("status",), False))
    with pytest.raises(PermissionError, match="grammar"):
        executor.validate_command(CommandSpec(
            "injection", "/usr/bin/systemctl", ("status", "gitea;reboot")))
    with pytest.raises(PermissionError, match="git arguments"):
        executor.validate_command(CommandSpec(
            "unsafe git", "/usr/bin/git", ("log", "--output=/tmp/leak")))


def test_provider_profiles_restrict_paths_and_unknown_connectors():
    adapter = provider_adapter("github", lambda method, url: (method, url))
    assert adapter.read(ReadRequest("github", "https://api.github.com", "/repos/Fryrocket/orca-review"))[0] == "GET"
    with pytest.raises(PermissionError, match="provider profile"):
        adapter.read(ReadRequest("github", "https://api.github.com", "/orgs/Fryrocket"))
    linear = provider_adapter("linear", lambda method, url: (method, url))
    with pytest.raises(PermissionError, match="provider profile"):
        linear.read(ReadRequest("linear", "https://api.linear.app", "/graphql-evil"))
    with pytest.raises(PermissionError, match="no provider profile"):
        provider_adapter("unknown", lambda *_: None)


def test_connector_resources_are_bounded_and_never_accept_secrets():
    cp = ControlPlane()
    with pytest.raises(ValueError, match="bounded"):
        cp.prepare_connector_read(
            actor="orca", connector="drive", operation="read",
            resource="token=sk-abcdefghijklmnop")
    with pytest.raises(ValueError, match="bounded"):
        cp.prepare_connector_read(
            actor="orca", connector="drive", operation="read", resource="x" * 2_001)
    assert cp.evidence.list() == []


def test_advisory_workflow_reads_four_systems_and_never_writes():
    cp = ControlPlane()
    calls = []
    readers = {
        name: (lambda resource, connector=name: calls.append((connector, resource)) or
               {"connector": connector, "resource": resource})
        for name in ("notion", "linear", "gitea", "drive")
    }
    report = AdvisoryWorkflow().run(cp, readers)
    assert report["write_count"] == 0
    assert {row["connector"] for row in report["results"]} == set(readers)
    assert len(calls) == 4
    event = cp.evidence.list(correlation_id=report["correlation_id"])[0]
    assert event["kind"] == "workflow.advisory_read_completed"
    assert event["payload"]["write_count"] == 0
    assert cp.snapshot()["state_revision"] == 5
    saved_head = cp.evidence.db.execute(
        "SELECT evidence_head FROM control_state WHERE singleton=1"
    ).fetchone()[0]
    current_head = cp.evidence.db.execute(
        "SELECT event_hash FROM events ORDER BY seq DESC LIMIT 1"
    ).fetchone()[0]
    assert saved_head == current_head
