from __future__ import annotations

import json
import subprocess

import pytest

from orca.inventory import InventoryProvider, InventoryReadError


def _runner_for(payloads):
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        action = command[-1]
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps(payloads[action]).encode(), stderr=b""
        )

    return calls, runner


def test_inventory_provider_is_fixed_read_only_and_bounded():
    calls, runner = _runner_for({
        "catalog": {
            "ok": True,
            "locations": [{"code": "BENCH", "label": "Bench"}],
            "categories": ["Parts"],
            "units": ["ea"],
        },
        "list": {
            "ok": True,
            "items": [{"name": "Resistor", "qty": 10, "unit": "ea"}],
        },
    })
    provider = InventoryProvider(
        key_file="/state/key", known_hosts_file="/state/known-hosts",
        runner=runner,
    )
    snapshot = provider.snapshot()
    assert snapshot["read_only"] is True
    assert snapshot["items"][0]["name"] == "Resistor"
    assert [call[0][-1] for call in calls] == ["catalog", "list"]
    assert all(call[0][0] == "/usr/bin/ssh" for call in calls)
    assert all(call[1]["timeout"] == 12 for call in calls)
    with pytest.raises(ValueError, match="not allowlisted"):
        provider._command("submit")


def test_inventory_provider_fails_closed_on_transport_and_shape():
    def rejected(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout=b"", stderr=b"denied")

    provider = InventoryProvider(
        key_file="/state/key", known_hosts_file="/state/known-hosts",
        runner=rejected,
    )
    with pytest.raises(InventoryReadError, match="rejected"):
        provider.snapshot()

    def malformed(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout=b"[]", stderr=b"")

    provider.runner = malformed
    with pytest.raises(InventoryReadError, match="not successful"):
        provider.snapshot()


def test_inventory_provider_rejects_other_hosts_and_bad_timeout():
    with pytest.raises(ValueError, match="not allowlisted"):
        InventoryProvider(key_file="k", known_hosts_file="h", host="example.com")
    with pytest.raises(ValueError, match="timeout"):
        InventoryProvider(key_file="k", known_hosts_file="h", timeout_seconds=31)
