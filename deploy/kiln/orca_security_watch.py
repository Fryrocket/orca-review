#!/usr/bin/env python3
"""Advisory-only local security posture observer for ORCA nodes."""

import argparse
import json
import os
import stat
import time
from pathlib import Path


# Accepted Kiln baseline, verified against owning services during deployment.
DEFAULT_ALLOWED_PUBLIC_PORTS = {22, 80, 2222, 3000, 6379, 8788, 9000, 9001, 11435}
REQUIRED_DIRECTIVES = {
    "NoNewPrivileges=true",
    "ProtectSystem=strict",
    "ProtectHome=true",
}


def _decode_ipv4(value):
    raw = bytes.fromhex(value)
    return ".".join(str(part) for part in raw[::-1])


def read_listeners(paths=None):
    paths = paths or (Path("/proc/net/tcp"), Path("/proc/net/tcp6"))
    listeners = []
    for path in paths:
        try:
            lines = Path(path).read_text(encoding="ascii").splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) < 4 or fields[3] != "0A":
                continue
            address_hex, port_hex = fields[1].split(":")
            if len(address_hex) == 8:
                address = _decode_ipv4(address_hex)
            elif address_hex == "0" * 32:
                address = "::"
            else:
                address = "ipv6"
            listeners.append({"address": address, "port": int(port_hex, 16)})
    return listeners


def inspect_units(unit_paths):
    results = []
    for path in unit_paths:
        path = Path(path)
        try:
            text = path.read_text(encoding="utf-8")
            mode = stat.S_IMODE(path.stat().st_mode)
            missing = sorted(item for item in REQUIRED_DIRECTIVES if item not in text)
            results.append({
                "name": path.name,
                "world_writable": bool(mode & stat.S_IWOTH),
                "missing_hardening": missing,
            })
        except OSError as exc:
            results.append({"name": path.name, "unavailable": type(exc).__name__})
    return results


def evaluate(listeners, units, allowed_public_ports=None, now=None):
    now = int(time.time() if now is None else now)
    allowed = set(DEFAULT_ALLOWED_PUBLIC_PORTS if allowed_public_ports is None else allowed_public_ports)
    findings = []
    public = []
    for listener in listeners:
        if listener.get("address") not in {"0.0.0.0", "::"}:
            continue
        port = listener.get("port")
        accepted = port in allowed
        public.append({"port": port, "accepted": accepted})
        if not accepted:
            findings.append({"severity": "warning", "kind": "unexpected_public_listener", "port": port})
    for unit in units:
        name = unit.get("name", "unknown")
        if unit.get("unavailable"):
            findings.append({"severity": "warning", "kind": "unit_unavailable", "unit": name})
        if unit.get("world_writable"):
            findings.append({"severity": "critical", "kind": "world_writable_unit", "unit": name})
        for directive in unit.get("missing_hardening", []):
            findings.append({"severity": "advisory", "kind": "missing_hardening", "unit": name,
                             "directive": directive})
    state = "degraded" if any(item["severity"] in {"warning", "critical"} for item in findings) else "healthy"
    return {
        "schema_version": 1,
        "bot_id": "security_watch",
        "state": state,
        "observed_epoch": now,
        "authority": "advisory_metadata_observer",
        "public_listeners": sorted(public, key=lambda item: int(item["port"] or -1)),
        "unit_count": len(units),
        "findings": findings,
        "secret_content_read": False,
        "changes_applied": False,
    }


def write_report(report, output):
    target = Path(output)
    target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o640)
    os.replace(temporary, target)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="/var/lib/orca-security-watch/status.json")
    parser.add_argument("--unit", action="append", default=[])
    parser.add_argument("--allow-public-port", type=int, action="append", default=[])
    args = parser.parse_args()
    units = args.unit or [
        "/etc/systemd/system/orca-evidence-auditor.service",
        "/etc/systemd/system/orca-kiln-node.service",
    ]
    allowed = set(args.allow_public_port) or DEFAULT_ALLOWED_PUBLIC_PORTS
    report = evaluate(read_listeners(), inspect_units(units), allowed)
    write_report(report, args.output)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["state"] == "healthy" else 1


if __name__ == "__main__":
    raise SystemExit(main())
