from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import ipaddress
import json
from typing import Iterable, Mapping


MANAGEMENT_NETWORKS = (
    ipaddress.ip_network("192.168.4.0/24"),
    ipaddress.ip_network("192.168.7.0/24"),
    ipaddress.ip_network("100.64.0.0/10"),
)


@dataclass(frozen=True)
class Exposure:
    port: int
    protocol: str
    purpose: str
    scopes: tuple[str, ...]
    required: bool = True


@dataclass(frozen=True)
class NodeSecurityProfile:
    node_id: str
    platform: str
    exposures: tuple[Exposure, ...]
    require_firewall: bool = True
    require_unattended_security_updates: bool = True
    require_key_only_ssh: bool = True
    require_root_ssh_disabled: bool = True
    require_intrusion_throttling: bool = True


@dataclass(frozen=True)
class SecurityFinding:
    node_id: str
    severity: str
    check_id: str
    summary: str
    remediation: str
    evidence: str


@dataclass(frozen=True)
class SecurityAssessment:
    node_id: str
    disposition: str
    findings: tuple[SecurityFinding, ...]
    autonomous_actions: tuple[str, ...]
    owner_gates: tuple[str, ...]
    fingerprint: str

    def snapshot(self) -> dict:
        return {
            "node_id": self.node_id,
            "disposition": self.disposition,
            "findings": [asdict(item) for item in self.findings],
            "autonomous_actions": list(self.autonomous_actions),
            "owner_gates": list(self.owner_gates),
            "fingerprint": self.fingerprint,
        }


PROFILES = {
    "anvil": NodeSecurityProfile(
        "anvil", "macos",
        (
            Exposure(8788, "tcp", "ORCA Studio gateway", ("loopback", "management")),
            Exposure(11434, "tcp", "local Ollama", ("loopback",)),
        ),
        require_unattended_security_updates=False,
        require_key_only_ssh=False,
        require_root_ssh_disabled=False,
        require_intrusion_throttling=False,
    ),
    "forge": NodeSecurityProfile(
        "forge", "linux",
        (
            Exposure(22, "tcp", "managed SSH", ("management", "private_link", "tailscale")),
            Exposure(2222, "tcp", "Gitea SSH", ("private_link",)),
            Exposure(3000, "tcp", "Gitea web", ("private_link",)),
            Exposure(8787, "tcp", "ORCA control plane", ("loopback",)),
            Exposure(8790, "tcp", "media broker", ("loopback",)),
            Exposure(8188, "tcp", "CRUCIBLE ComfyUI", ("loopback",)),
            Exposure(11436, "tcp", "Qwen inference", ("loopback",)),
        ),
    ),
    "kiln": NodeSecurityProfile(
        "kiln", "linux",
        (
            Exposure(22, "tcp", "managed SSH", ("management",)),
            Exposure(80, "tcp", "local Studio entry", ("management",)),
            Exposure(8788, "tcp", "ORCA Studio gateway", ("management",)),
            Exposure(3000, "tcp", "Gitea web relay", ("management",)),
            Exposure(2222, "tcp", "Gitea SSH relay", ("management",)),
            Exposure(9000, "tcp", "MinIO API", ("management",)),
            Exposure(9001, "tcp", "MinIO console", ("management",)),
            Exposure(6379, "tcp", "Redis", ("loopback", "container")),
            Exposure(11435, "tcp", "QUENCH inference", ("tailscale",)),
            Exposure(8790, "tcp", "media relay", ("tailscale", "loopback")),
            Exposure(3080, "tcp", "container dashboard", ("tailscale",)),
            Exposure(11437, "tcp", "Codex bridge", ("loopback",)),
        ),
    ),
    "ember": NodeSecurityProfile(
        "ember", "linux",
        (
            Exposure(22, "tcp", "managed SSH", ("management",)),
            Exposure(3493, "tcp", "NUT UPS service", ("management",)),
            Exposure(8790, "tcp", "monitor relay", ("tailscale", "loopback")),
        ),
    ),
    "temper": NodeSecurityProfile(
        "temper", "linux",
        (
            Exposure(22, "tcp", "managed SSH", ("management",)),
            Exposure(8088, "tcp", "signed Hailo broker", ("loopback",)),
            Exposure(41883, "tcp", "credentialed MQTT", ("management",)),
        ),
    ),
}


AUTONOMOUS_ACTIONS = (
    "record redacted evidence and alert only on material exceptions",
    "reject unauthenticated, replayed, stale, malformed, or over-budget work",
    "pause the affected connector or bounded job queue without stopping the fleet",
    "restart an explicitly allowlisted stateless monitor up to three times in five minutes",
    "restore the monitor's last verified configuration when its own activation fails",
    "rate-limit abusive requests and expire temporary capability leases",
)

OWNER_GATES = (
    "activate or broaden firewall and routing policy",
    "change SSH trust, long-lived credentials, or account permissions",
    "rotate or revoke recovery keys",
    "install a major OS release, reboot, or power-cycle hardware",
    "delete evidence or alter backup retention",
    "move money, accept legal terms, publish, purchase, or contact outsiders",
)


def _scope(address: str) -> str:
    if address in {"127.0.0.1", "::1", "localhost"}:
        return "loopback"
    if address in {"0.0.0.0", "::", "*"}:
        return "all"
    try:
        parsed = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return "unknown"
    if parsed.version == 4 and parsed in ipaddress.ip_network("192.168.7.0/24"):
        return "private_link"
    if parsed.version == 4 and parsed in ipaddress.ip_network("100.64.0.0/10"):
        return "tailscale"
    if any(parsed in network for network in MANAGEMENT_NETWORKS):
        return "management"
    return "host"


def _finding(node_id: str, severity: str, check_id: str, summary: str,
             remediation: str, evidence: str) -> SecurityFinding:
    return SecurityFinding(
        node_id=node_id, severity=severity, check_id=check_id,
        summary=summary, remediation=remediation, evidence=evidence[:240],
    )


def assess_node(*, node_id: str, listeners: Iterable[Mapping], firewall_active: bool,
                sshd: Mapping[str, str] | None = None,
                unattended_updates_active: bool | None = None,
                intrusion_throttling_active: bool | None = None) -> SecurityAssessment:
    if node_id not in PROFILES:
        raise ValueError(f"unknown security profile: {node_id}")
    profile = PROFILES[node_id]
    findings: list[SecurityFinding] = []
    if profile.require_firewall and not firewall_active:
        findings.append(_finding(
            node_id, "critical", "firewall-inactive", "Host firewall is not enforcing policy",
            "Stage the node profile, arm an automatic rollback, prove management access, then activate.",
            "firewall_active=false",
        ))
    allowed = {(item.protocol, item.port): item for item in profile.exposures}
    observed: set[tuple[str, int]] = set()
    for raw in listeners:
        try:
            protocol = str(raw.get("protocol", "tcp")).lower()
            port = int(raw["port"])
            address = str(raw["address"])
        except (KeyError, TypeError, ValueError):
            findings.append(_finding(
                node_id, "warning", "listener-malformed", "Listener evidence is malformed",
                "Repair the observer before relying on its firewall decision.", repr(dict(raw)),
            ))
            continue
        observed.add((protocol, port))
        exposure = allowed.get((protocol, port))
        scope = _scope(address)
        if exposure is None:
            if scope not in {"loopback"}:
                findings.append(_finding(
                    node_id, "critical" if scope == "all" else "warning",
                    "listener-unapproved", "Service is listening outside its approved profile",
                    "Identify the owning service, then bind it narrowly or add a reviewed profile entry.",
                    f"{protocol} {address}:{port} scope={scope}",
                ))
            continue
        if scope == "all" and "all" not in exposure.scopes:
            findings.append(_finding(
                node_id, "critical", "listener-overbroad",
                f"{exposure.purpose} listens on every interface",
                "Bind the service to its approved interface or enforce the approved source zones at the firewall.",
                f"{protocol} {address}:{port} approved={','.join(exposure.scopes)}",
            ))
        elif scope not in exposure.scopes and scope not in {"all"}:
            findings.append(_finding(
                node_id, "warning", "listener-scope-drift",
                f"{exposure.purpose} is outside its approved scope",
                "Rebind the service or update the profile only after independent review.",
                f"{protocol} {address}:{port} scope={scope} approved={','.join(exposure.scopes)}",
            ))
    for exposure in profile.exposures:
        if exposure.required and (exposure.protocol, exposure.port) not in observed:
            findings.append(_finding(
                node_id, "advisory", "required-service-absent",
                f"Expected service is not listening: {exposure.purpose}",
                "Confirm whether the service is intentionally stopped before changing policy.",
                f"{exposure.protocol}/{exposure.port}",
            ))
    sshd = {str(key).lower(): str(value).lower() for key, value in (sshd or {}).items()}
    if profile.require_key_only_ssh and sshd.get("passwordauthentication") not in {"no", "false"}:
        findings.append(_finding(
            node_id, "critical", "ssh-password-enabled", "SSH password authentication is enabled",
            "Prove two independent key-based sessions and recovery access before disabling passwords.",
            f"passwordauthentication={sshd.get('passwordauthentication', 'unknown')}",
        ))
    if profile.require_root_ssh_disabled and sshd.get("permitrootlogin") != "no":
        findings.append(_finding(
            node_id, "warning", "ssh-root-not-disabled", "Root SSH is not fully disabled",
            "Set PermitRootLogin no after proving non-root sudo and break-glass recovery.",
            f"permitrootlogin={sshd.get('permitrootlogin', 'unknown')}",
        ))
    if (profile.require_unattended_security_updates
            and unattended_updates_active is not True):
        findings.append(_finding(
            node_id, "warning", "security-updates-inactive",
            "Automatic security updates are not active",
            "Enable security-only unattended updates with reboot suppression and exception reporting.",
            f"unattended_updates_active={unattended_updates_active}",
        ))
    if profile.require_intrusion_throttling and intrusion_throttling_active is not True:
        findings.append(_finding(
            node_id, "warning", "intrusion-throttling-inactive",
            "No accepted login-abuse throttling service is active",
            "Install and validate fail2ban or an equivalent bounded SSH rate limiter.",
            f"intrusion_throttling_active={intrusion_throttling_active}",
        ))
    disposition = (
        "block_activation" if any(item.severity == "critical" for item in findings)
        else "review" if findings else "pass"
    )
    material = json.dumps([asdict(item) for item in findings], sort_keys=True, separators=(",", ":"))
    return SecurityAssessment(
        node_id=node_id, disposition=disposition, findings=tuple(findings),
        autonomous_actions=AUTONOMOUS_ACTIONS, owner_gates=OWNER_GATES,
        fingerprint=sha256(material.encode("utf-8")).hexdigest(),
    )


def firewall_plan(node_id: str) -> dict:
    """Return a reviewable plan. This function never changes a host firewall."""
    if node_id not in PROFILES:
        raise ValueError(f"unknown security profile: {node_id}")
    profile = PROFILES[node_id]
    if profile.platform == "macos":
        actions = [
            "enable application firewall and stealth mode",
            "allow only signed, explicitly approved applications",
            "bind ORCA and local model services to loopback",
        ]
    else:
        actions = [
            "capture current nftables and service-listener evidence",
            "verify two independent key-based management sessions",
            "schedule an automatic rollback before policy activation",
            "set default inbound deny and default outbound allow",
            "preserve established traffic, loopback, ICMP and Tailscale transport",
        ]
        actions.extend(
            f"allow {item.protocol}/{item.port} for {item.purpose} from {','.join(item.scopes)}"
            for item in profile.exposures if any(scope != "loopback" for scope in item.scopes)
        )
        actions.extend([
            "apply matching Docker-USER restrictions before relying on host rules",
            "verify every required route from a second session",
            "cancel rollback only after signed health and service probes pass",
        ])
    payload = {"node_id": node_id, "platform": profile.platform, "actions": actions,
               "changes_applied": False, "requires_verified_rollback": True}
    payload["plan_fingerprint"] = sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return payload
