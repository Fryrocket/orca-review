#!/usr/bin/env python3
"""Deterministic, read-only audit of ORCA's sanitized connector registry."""

import argparse
import json
import os
import time
import urllib.request
from pathlib import Path


READ_OPERATIONS = {"get", "list", "search", "read"}
VALID_LEVELS = {"R0", "R1", "R2", "R3"}


def evaluate(state, now=None):
    now = int(time.time() if now is None else now)
    connectors = state.get("connectors")
    capabilities = state.get("connector_capabilities")
    findings = []
    rows = []

    if not isinstance(connectors, list) or not isinstance(capabilities, list):
        return {
            "schema_version": 1,
            "bot_id": "connector_steward",
            "state": "degraded",
            "observed_epoch": now,
            "authority": "read_only_registry_observer",
            "runtime_connectivity": "unproven",
            "connectors": [],
            "findings": ["connector registry or capability matrix unavailable"],
        }

    connector_ids = [item.get("id") for item in connectors if isinstance(item, dict)]
    capability_ids = [item.get("connector") for item in capabilities if isinstance(item, dict)]
    if len(connector_ids) != len(set(connector_ids)):
        findings.append("duplicate connector id")
    if len(capability_ids) != len(set(capability_ids)):
        findings.append("duplicate capability entry")
    if set(connector_ids) != set(capability_ids):
        findings.append("registry and capability matrix differ")

    capability_by_id = {
        item.get("connector"): item for item in capabilities if isinstance(item, dict)
    }
    for item in connectors:
        if not isinstance(item, dict):
            findings.append("malformed connector entry")
            continue
        connector_id = item.get("id")
        cap = capability_by_id.get(connector_id, {})
        operations = cap.get("operations", [])
        actions = cap.get("declared_actions", [])
        row_findings = []
        if not isinstance(connector_id, str) or not connector_id:
            row_findings.append("invalid id")
        if item.get("writes_enabled") is not False or cap.get("writes_enabled") is not False:
            row_findings.append("writes enabled or unspecified")
        if not isinstance(operations, list) or not operations or not set(operations).issubset(READ_OPERATIONS):
            row_findings.append("runtime operations are not read-only")
        if not isinstance(actions, list) or not actions:
            row_findings.append("declared action matrix missing")
        else:
            for action in actions:
                if not isinstance(action, dict) or action.get("level") not in VALID_LEVELS:
                    row_findings.append("invalid action risk level")
                    break
                if action.get("mutates") is False and action.get("level") != "R0":
                    row_findings.append("read action is not R0")
                    break
                if action.get("mutates") is True and action.get("level") == "R0":
                    row_findings.append("mutating action classified R0")
                    break
        findings.extend(f"{connector_id}: {finding}" for finding in row_findings)
        rows.append({
            "id": connector_id,
            "name": item.get("name"),
            "writes_enabled": item.get("writes_enabled"),
            "read_operations": sorted(operations) if isinstance(operations, list) else [],
            "declared_action_count": len(actions) if isinstance(actions, list) else 0,
            "registry_ok": not row_findings,
            "read_path": "unproven",
        })

    return {
        "schema_version": 1,
        "bot_id": "connector_steward",
        "state": "healthy" if not findings and rows else "degraded",
        "observed_epoch": now,
        "authority": "read_only_registry_observer",
        "runtime_connectivity": "unproven",
        "connectors": sorted(rows, key=lambda row: str(row.get("id"))),
        "findings": findings,
    }


def fetch_state(url, timeout=8):
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise ValueError(f"unexpected status {response.status}")
        return json.load(response)


def write_report(report, output):
    target = Path(output)
    target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o640)
    os.replace(temporary, target)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8787/api/state")
    parser.add_argument("--output", default="/var/lib/orca-connector-steward/status.json")
    args = parser.parse_args()
    try:
        report = evaluate(fetch_state(args.url))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = {
            "schema_version": 1,
            "bot_id": "connector_steward",
            "state": "degraded",
            "observed_epoch": int(time.time()),
            "authority": "read_only_registry_observer",
            "runtime_connectivity": "unproven",
            "connectors": [],
            "findings": [f"state endpoint unavailable: {type(exc).__name__}"],
        }
    write_report(report, args.output)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["state"] == "healthy" else 1


if __name__ == "__main__":
    raise SystemExit(main())
