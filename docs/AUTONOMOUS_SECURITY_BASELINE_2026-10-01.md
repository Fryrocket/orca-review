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

## 2026-10-01 activated baseline

| Node | Existing strengths | Material gaps |
| --- | --- | --- |
| ANVIL | macOS application firewall and FileVault enabled; Ollama loopback-only; signed heartbeat healthy | Stealth mode remains off because changing it requires an owner-present macOS administrator authorization; ORCA gateway remains intentionally reachable on the management network |
| FORGE | UFW active with source-scoped SSH and Gitea rules; key-only SSH; root login disabled; fail2ban active; unattended security updates active with automatic reboot disabled; ORCA, Qwen, CRUCIBLE and media broker loopback-only | Physical reboot and power-loss recovery remain owner-present tests |
| KILN | UFW active; key-only SSH; fail2ban active; unattended security updates active with automatic reboot disabled; Docker `DOCKER-USER` filter blocks Redis and scopes Gitea/MinIO to management LAN or Tailscale; Security Watch healthy | Physical reboot and power-loss recovery remain owner-present tests |
| EMBER | UFW active; key-only SSH; root login disabled; fail2ban active; unattended security updates active with automatic reboot disabled; NUT restricted to the management LAN; relay restricted to Tailscale | Physical UPS/power-loss drill remains owner-present |
| TEMPER | UFW active; key-only SSH; root login disabled; fail2ban and unattended security updates active with automatic reboot disabled; authenticated MQTT only; Hailo, signed jobs, camera liveness and TEMPER Watch healthy | Physical field-data validation, model conversion and power-loss testing remain future gates |

Every Linux firewall was activated one node at a time with saved configuration,
a five-minute automatic rollback, fresh independent SSH and service probes, and
rollback cancellation only after required paths passed. No node reboot or
power-cycle was performed.

## Target zones

- `loopback`: private to the owning host.
- `private_link`: FORGE's dedicated `192.168.7.0/24` infrastructure segment.
- `management`: trusted LAN `192.168.4.0/22`, private link, and Tailscale
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

## Activation evidence

- KILN: UFW, fail2ban and the persistent Docker filter are active. Gitea and
  MinIO remained reachable from the LAN, the ORCA/Tailscale gateway remained
  reachable, and Redis was independently confirmed unreachable from the LAN.
  Security Watch now consumes a root-produced, non-secret protected-port
  attestation and reports healthy with zero findings.
- FORGE: UFW and fail2ban are active. Effective SSH policy is
  `PasswordAuthentication no`, `PermitRootLogin no`, and
  `PubkeyAuthentication yes`. Fresh nested SSH, Gitea and ORCA probes passed.
- EMBER: UFW and fail2ban are active. Fresh SSH, NUT, Tailscale relay, backup,
  recovery, wake and monitoring timers remained available.
- TEMPER: UFW, fail2ban and unattended security updates are active. Effective
  SSH is key-only with root disabled. The unused anonymous MQTT listener was
  retired; the authenticated local client reconnected on 41883. The camera
  liveness probe reads one frame to `/dev/null`, retains no imagery, and feeds
  TEMPER Watch, which reports healthy with zero exceptions. HailoRT, the signed
  node, dashboard, telemetry and Pironman services remained active at about
  49°C.
- The complete ORCA source suite passed **1,113/1,113** after the changes. All
  four Linux nodes showed no failed units at final verification. ORCA health and
  integrity were valid, and all five signed node heartbeats were healthy.

## Remaining owner-present gates

- Turn on macOS stealth mode and narrow ANVIL's ORCA gateway after verifying the
  intended remote access route with an owner-present administrator approval.
- Review and explicitly clear any sticky ORCA node pause that was set by an
  earlier safety event; healthy heartbeats alone intentionally do not auto-resume
  execution.
- Perform supervised reboot, physical power-loss, UPS and recovery drills.
- Repeat the external 128-test acceptance lab, node-specific recovery tests,
  and the final multi-node soak after activation.
