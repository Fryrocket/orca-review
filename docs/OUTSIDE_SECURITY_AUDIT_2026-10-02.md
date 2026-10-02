# ORCA / FORGE Outside Security Audit — 2026-10-02

## Scope and handling

This audit examined a frozen, read-only export of commit
`5e315d9d396cd01501f515c454323e12e47e3f5a`. The source archive SHA-256 is
`52efa56f21c573258be2caac5cc1a946c024e301639243dd65d8a0234be469fc`.
No production credentials were copied into the audit set, no live configuration
was changed, and no remediation was applied during the audit.

The review covered 393 tracked files: Python services, HTTP surfaces, systemd
units, firewall assets, connector boundaries, dependency manifests, and the
existing security and regression tests. Deterministic checks included secret
pattern scanning, command-execution review, network-listener review, filesystem
mutation review, service-hardening review, and comparison with live read-only
listener/firewall evidence. Semgrep, CodeQL, and Codex Security were not
available locally, so this is an independent manual/deterministic audit rather
than a claim that every specialized scanner ran.

## Executive result

**Conditional pass with remediation required.** No embedded production secrets,
arbitrary shell execution, unsafe deserialization, destructive installer pipe,
or world-writable tracked file was found. The core control plane remains
loopback-only and the reviewed bot services generally use strong systemd
sandboxing. One high-severity trust-boundary weakness and two medium-severity
hardening gaps should be resolved before ORCA is treated as safe on a network
containing untrusted clients.

## Validated findings

### ORCA-SEC-001 — High — LAN/Tailnet gateway grants unauthenticated owner authority

The Studio gateway is deliberately described as login-free, binds to
`0.0.0.0:8788`, forwards arbitrary GET/HEAD/POST paths and client headers, and is
allowed through KILN's firewall from the `192.168.4.0/22` LAN and through the
Tailscale interface. The FORGE control plane is launched with
`--trusted-network-no-auth`; its mutation authenticator therefore assigns every
proxied mutation the owner identity `fry` without a credential.

An untrusted device that can reach KILN port 8788 can therefore attempt any ORCA
mutation endpoint as the owner. Revision and idempotency preconditions reduce
accidental replay but are not authentication and can be learned from readable
state. This is a trust-boundary bypass, not merely a missing login screen.

Evidence:

- `deploy/kiln/orca-studio-gateway.service`: description and `0.0.0.0:8788` bind.
- `deploy/orca_studio_gateway.py`: unrestricted path proxy and forwarded headers.
- `deploy/forge/orca.service`: `--trusted-network-no-auth`.
- `orca/web.py`: trusted-network mode returns owner identity without checking a token.
- Live read-only verification: UFW permits 8788 from the LAN; the process listens on all IPv4 interfaces.

Recommended remediation:

1. Remove `--trusted-network-no-auth` from the control plane.
2. Give the gateway a dedicated, least-privilege identity token stored in an
   owner-only credential file; inject it server-side and strip all client-supplied
   ORCA identity/authentication headers.
3. Replace arbitrary proxying with an explicit route-and-method allowlist.
4. Restrict 8788 to Tailscale or a mutually authenticated reverse proxy; do not
   expose the owner control surface to the general LAN.
5. Add negative tests proving anonymous requests, forged identity headers, and
   unlisted mutation routes fail closed.

### ORCA-SEC-002 — Medium — Studio traffic is plaintext and unaudited on the LAN

Port 8788 serves HTTP directly. The gateway suppresses access logging and does
not add an authenticated transport boundary. On the local LAN, prompts,
business records, and responses can be observed or altered by a capable network
attacker. Tailscale protects its own path, but the explicit LAN firewall rule
leaves a separate plaintext route.

Recommended remediation: terminate TLS with a private CA or remove the LAN
exposure and require Tailscale; retain privacy-safe request metadata and security
event logs without recording prompt bodies or secrets.

### ORCA-SEC-003 — Medium — Media broker parses large inputs while running as root

`orca-image-broker.service` runs the Python HTTP/media broker as `root`. Root is
used to start and stop model services, but the same process also parses large
image/video requests and communicates with ComfyUI. `NoNewPrivileges`, an empty
capability bounding set, and filesystem protections are valuable controls, but
they do not make a root parser equivalent to an unprivileged service.

Recommended remediation: run the broker as a dedicated unprivileged account and
move the fixed service-switch operation into a tiny, allowlisted privileged
helper or tightly scoped policy rule. Add `PrivateDevices`, `ProtectKernelLogs`,
`ProtectHostname`, `ProtectClock`, `MemoryDenyWriteExecute`, and explicit resource
limits where compatible.

## Positive controls verified

- The ORCA control plane itself binds only to loopback.
- Codex bridge execution is ephemeral, read-only, single-flight, schema-bounded,
  and loopback-only.
- Public web reads reject credentials, nonstandard ports, private addresses, and
  redirects.
- Local command execution uses absolute executables, fixed grammars, no shell,
  bounded output, and timeouts.
- Browser Operator validates plans but does not execute external actions.
- Most services run unprivileged with `NoNewPrivileges`, strict filesystem
  protection, private temporary directories, and empty capability sets.
- Secret-pattern matches were synthetic test fixtures; no production secret was
  found in the tracked export.
- Pinned optional math dependencies are limited to `sympy==1.14.0` and
  `mpmath==1.3.0`.

## Remediation order and acceptance gates

1. **P0:** Authenticate the Studio gateway and remove trusted-network owner
   impersonation. Gate: anonymous and forged requests receive 401/403 while the
   authenticated ORCA UI and all approved workflows pass regression.
2. **P1:** Eliminate plaintext general-LAN access or add authenticated TLS. Gate:
   no direct HTTP listener is reachable from an untrusted LAN client.
3. **P1:** De-privilege the media broker. Gate: image and 33-frame video jobs pass
   while the broker runs non-root and cannot start arbitrary services.
4. **P2:** Run Semgrep, CodeQL, dependency-vulnerability, and dedicated secret
   scanners against the same frozen revision when those approved tools are
   available; deduplicate results against this report.
5. Repeat the full regression, external-site test suite, negative permission
   tests, and an eight-hour five-node soak before closing the security release.

## Owner-present gates still outstanding

Physical power-loss, UPS-on-battery behavior, ANVIL reboot, and macOS
administrator-only controls remain untested and must not be represented as
accepted.
