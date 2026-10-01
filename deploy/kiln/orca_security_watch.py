#!/usr/bin/env python3
"""Advisory-only local security posture observer for ORCA nodes."""

import argparse
import json
import os
import stat
import time
from pathlib import Path


# Ports that may be reachable through an active, source-scoped KILN firewall.
# A wildcard listener is never accepted when the firewall is inactive. Redis
# is intentionally absent: it must remain loopback/container-only.
DEFAULT_ALLOWED_PUBLIC_PORTS = {22, 80, 2222, 3000, 8788, 9000, 9001}
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


def read_ufw_enabled(path="/etc/ufw/ufw.conf"):
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    values = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip().upper()] = value.strip().lower()
    return values.get("ENABLED") == "yes"


def read_protected_public_ports(path="/run/orca-kiln-docker-firewall/protected-ports.json"):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return set()
    if payload.get("schema_version") != 1 or payload.get("firewall") != "ORCA-DOCKER-FILTER":
        return set()
    return {int(port) for port in payload.get("protected_public_ports", [])
            if isinstance(port, int) and 0 < port < 65536}


def evaluate(listeners, units, allowed_public_ports=None, now=None,
             firewall_active=None, protected_public_ports=None):
    now = int(time.time() if now is None else now)
    allowed = set(DEFAULT_ALLOWED_PUBLIC_PORTS if allowed_public_ports is None else allowed_public_ports)
    protected = set(protected_public_ports or ())
    findings = []
    public = []
    if firewall_active is False:
        findings.append({
            "severity": "critical",
            "kind": "firewall_inactive",
            "remediation": "activate the reviewed source-scoped policy with timed rollback",
        })
    for listener in listeners:
        if listener.get("address") not in {"0.0.0.0", "::"}:
            continue
        port = listener.get("port")
        accepted = (port in allowed or port in protected) and firewall_active is not False
        public.append({"port": port, "accepted": accepted, "protected": port in protected})
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
        "firewall_active": firewall_active,
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
    parser.add_argument("--ufw-config", default="/etc/ufw/ufw.conf")
    args = parser.parse_args()
    units = args.unit or [
        "/etc/systemd/system/orca-evidence-auditor.service",
        "/etc/systemd/system/orca-kiln-node.service",
    ]
    allowed = set(args.allow_public_port) or DEFAULT_ALLOWED_PUBLIC_PORTS
    report = evaluate(
        read_listeners(), inspect_units(units), allowed,
        firewall_active=read_ufw_enabled(args.ufw_config),
        protected_public_ports=read_protected_public_ports(),
    )
    write_report(report, args.output)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["state"] == "healthy" else 1


if __name__ == "__main__":
    raise SystemExit(main())
