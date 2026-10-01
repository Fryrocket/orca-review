# FORGE/ORCA autonomous security baseline

Date: 2026-10-01

## Objective

Operate the five-node FORGE/ORCA ecosystem unattended for routine work while
preserving a recoverable owner boundary. Automation should detect, contain,
recover, verify, and report ordinary faults without exposing credentials or
silently broadening its own authority.

Autonomous does not mean unaccountable. Firewall activation, SSH trust changes,
long-lived credential rotation, major OS upgrades, reboots, evidence deletion,
money, legal acceptance, publishing, purchasing, and outside communication
remain explicit gates. Once the reviewed baseline is activated, routine policy
enforcement and bounded service recovery are unattended.

## 2026-10-01 observed baseline

| Node | Existing strengths | Material gaps |
| --- | --- | --- |
| ANVIL | macOS application firewall and FileVault enabled; Ollama loopback-only | Stealth mode off; ORCA gateway currently listens broadly; several macOS sharing/continuity listeners need owner-intent classification |
| FORGE | ORCA, Qwen, CRUCIBLE and media broker are loopback-only; Gitea is restricted to the private link; unattended updates active | UFW inactive; SSH password authentication and root-key login allowed; no accepted login-abuse throttle |
| KILN | QUENCH and supporting relays use Tailscale or loopback; SSH is key-only; unattended updates active | UFW inactive; Docker publishes Gitea, Redis and MinIO on all host interfaces; Studio gateway listens on all interfaces; no accepted login-abuse throttle |
| EMBER | SSH is key-only; unattended updates active; monitor relay uses Tailscale; cool with ample capacity | No host firewall package/policy; NUT listens on all LAN interfaces; no accepted login-abuse throttle |
| TEMPER | Hailo broker is loopback-only; bounded signed jobs and read-only monitoring are active; cool with ample capacity | No host firewall; SSH passwords and root-key login allowed; unattended updates absent; anonymous MQTT transition port and development services listen broadly; no accepted login-abuse throttle |

No firewall was activated during discovery. That prevents a remote lockout while
the exact route and Docker interaction rules are being proved.

## Target zones

- `loopback`: private to the owning host.
- `private_link`: FORGE's dedicated `192.168.7.0/24` infrastructure segment.
- `management`: trusted LAN `192.168.4.0/24`, private link, and Tailscale
  `100.64.0.0/10`, narrowed to exact peers where practical.
- `tailscale`: reachable only through the authenticated overlay.
- `container`: internal bridge traffic; never an unrestricted host publish.

The source of truth is `orca.autonomous_security.PROFILES`. It produces a
deterministic, non-executing firewall plan and a redacted assessment fingerprint
for each node.

## Safe activation sequence

1. Capture current listeners, routes, nftables/iptables state, Docker publishes,
   SSH effective configuration, and signed service health.
2. Prove two independent key-based management sessions and the local recovery
   path for the node.
3. Save the current firewall state and schedule a short automatic rollback.
4. Apply source-scoped host rules and equivalent Docker `DOCKER-USER` rules.
5. Re-probe SSH, signed heartbeats, tunnels, ORCA, models, storage, monitoring,
   backup, MQTT, media, and the node's required services from a second session.
6. Cancel rollback only after every required route passes and no unexpected
   listener remains.
7. Disable SSH passwords and root login only after the key and recovery tests.
8. Enable security-only unattended updates without automatic reboots, plus
   bounded login-abuse throttling and exception-only reports.
9. Run a node soak, then the five-node soak, then record the evidence hash.

## Autonomous Security Sentinel

The sentinel may run unattended to:

- compare listeners, firewall state, SSH policy, update status, and service
  hardening against the approved node profile;
- reject stale, replayed, malformed, unauthenticated, over-budget, or
  out-of-scope work;
- pause an affected connector or bounded job queue;
- restart an explicitly allowlisted stateless monitor at most three times in
  five minutes;
- restore only its own last verified configuration after a failed activation;
- rate-limit abuse, expire temporary capability leases, preserve evidence, and
  notify only on actionable exceptions.

It cannot widen a firewall, grant permissions, browse secrets, rotate recovery
keys, delete evidence, reboot hardware, move money, accept legal terms, publish,
purchase, or contact outsiders.

## Next activation gates

- Classify and either close or source-restrict KILN ports 6379, 9000, 9001,
  3000, 2222 and 8788.
- Retire TEMPER's anonymous MQTT listener after its credentialed cutover; close
  or source-restrict 34001, 8501 and 8086 after identifying their owners.
- Prove key-only recovery on FORGE and TEMPER, then disable password and root
  SSH access.
- Install and configure a firewall and bounded login-abuse throttle on each
  Linux node using rollback-first activation.
- Enable security-only unattended updates on TEMPER.
- Turn on macOS stealth mode and narrow ANVIL's ORCA gateway after verifying the
  intended remote access route.
- Repeat the external 128-test acceptance lab, node-specific recovery tests,
  and the final multi-node soak after activation.
