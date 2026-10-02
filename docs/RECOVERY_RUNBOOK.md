# ORCA recovery and validation runbook

Status: local rebuild alpha. This runbook does not authorize deployment, remote execution, connector writes, secret access, or legacy removal.

## Recovery inputs

- Fresh checkout of the reviewed ORCA branch or an approved release artifact.
- Python 3.11 or newer and the project virtual environment.
- The SQLite database containing `events`, `control_state`, and `costs`.
- Canonical `cc-bridge/STATE.md` and the newest verified ORCA handoff.
- Operator token of 32–512 characters supplied at runtime through `ORCA_OPERATOR_TOKEN`; never place its value in git, Drive, Notion, logs, or this runbook.
- Node authentication keys from the approved host-scoped secret store. The database contains fingerprints only.

## Restore procedure

1. Keep connector writes, bot runtimes, and remote execution disabled.
2. Restore the repository and database into a private working directory.
3. Run `python -m pytest tests_v1 -q`; stop on any failure.
4. Start on loopback only: `python -m orca --host 127.0.0.1 --database <restored-db>`.
5. Read `/api/health`; require `healthy` and `integrity_valid: true`.
6. Read `/api/state`; compare jobs, approvals, incidents, pauses, node enrollments, zero-dollar cost cap, and evidence status with the newest handoff.
7. Treat every node as unproven until a fresh authenticated heartbeat arrives.
8. Run loss-of-contact checks. Stale nodes must degrade/offline and pause.
9. Confirm POST requests fail with 503 without an operator token and 401 for a wrong token.
10. Exercise emergency stop with a temporary test database; only Fry may engage or release it.
11. Preserve output, database checksum, tests, operator, UTC time, and discrepancies as evidence.

## Failure and rollback

- Evidence-chain failure: stop mutation, preserve the database read-only, open an incident, and restore from the last verified copy.
- State corruption or state/evidence-head mismatch: do not overwrite the source database; copy it, retain checksums, and diagnose the copy.
- Lost node contact: pause the node with the durable `heartbeat_stale` reason.
  A later fresh authenticated healthy heartbeat may clear only this availability
  reason (and a node-reported transient-health reason). Operator, security,
  key-rotation, legacy and manual-health pauses never clear automatically.
- Credential exposure: never copy the value into evidence. Rotate it in the approved secret system and record only identifiers and timestamps.
- Unexpected mutation or execution: engage emergency stop, isolate it, preserve evidence, and require QUENCH review.

## Drill acceptance evidence

The checked-in `RECOVERY_DRILL_2026-09-23.json` is a historical local snapshot:
it exercised schema v2 and the then-current 112-test rebuilt suite. It is
retained for provenance and must not be presented as validation of the current
schema-v4 tree or an approved release. The current 2026-09-24 schema-v4
working-tree drill passed all 273 rebuilt tests and wrote its uncommitted report
to `/tmp/orca-recovery-final-20260924T051305Z.json` on ANVIL (database SHA-256
`594211f729744f28a841f8c3218a73403dc5b44c261c564f42d11283809fffd5`).
It is described in the state and implementation log but is not a checked-in
release artifact. Re-run `scripts/recovery_drill.py` against the exact
reviewed revision to produce current evidence rather than relabeling the old
snapshot. An approved-release drill is complete only
when it also restores approved secret material through the host-scoped secret
system, verifies live authenticated heartbeats, records discrepancies, and
receives independent QUENCH review. A written plan or successful process start is
not restore proof.

Paused jobs now have an explicit authenticated Resume action. It never overrides a remaining global, bot, lane, node, or approval boundary. A paused R2/R3 job returns to waiting approval if its approval is not yet granted; completion and denial remain terminal. See the September 23 regression review for restart/resume coverage.

## Autonomous power-return chain — 2026-10-02

1. EMBER stays on the CyberPower UPS and boots its enabled NUT, backup,
   heartbeat and recovery timers. If KILN is unreachable for three consecutive
   checks, EMBER sends bounded Wake-on-LAN packets and then verifies both KILN's
   SSH reachability and ORCA's integrity-valid health endpoint.
2. KILN boots Docker and its `unless-stopped` containers, SSH, tunnels, signed
   heartbeat, Studio gateway and graphical session. Its one-minute guard wakes
   FORGE after three failed checks and verifies the FORGE ORCA health endpoint.
3. FORGE starts ORCA and its signed heartbeat, inference, media, review and bot
   services through enabled systemd units. The live control plane automatically
   clears only outage-generated node pauses after fresh signed healthy evidence.
4. TEMPER and EMBER are Raspberry Pi nodes and boot when input power returns;
   their enabled timers restore signed telemetry and bounded edge services.
5. ANVIL's battery, enabled launch agents and Wake-on-LAN restore its optional
   operator/tunnel services. ORCA must remain functional while ANVIL is absent.
6. EMBER writes `/var/lib/orca-recovery/fleet-readiness.json` every minute. It
   reports ready only when evidence integrity is valid, emergency stop is off,
   all five required nodes have fresh healthy heartbeats and no node is paused.

The deployed wake and readiness programs are source-controlled under
`deploy/recovery/`; the host units are under `deploy/ember/` and `deploy/kiln/`.
Never interpret a successful software restart as proof of cold-power behavior.
The remaining acceptance gate is an owner-present whole-site power-cut test,
including UPS-on-battery behavior and firmware `Restore after AC loss` settings
on KILN and FORGE. ANVIL's macOS `autorestart` setting is also an owner-present
administrator action. Router, switch and modem power must be included in that
physical drill or placed on appropriate UPS capacity.
