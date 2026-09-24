# ORCA multi-host rollout and migration plan

Date: 2026-09-23
Status: Design and acceptance plan only; no deployment or remote execution authorized

## Safety boundary

The current ORCA build is a loopback-only local control plane. It rejects every
non-loopback HTTP bind. SQLite is local state and must never be placed on a
network filesystem or opened concurrently by hosts. Connector writes, remote
commands, bot runtimes, model spend, and autonomous failover remain disabled.

Any service placement, credential restoration, production migration, remote
execution, failover activation, or cutover is R3 and requires Fry's exact
approval after independent QUENCH review.

## Fleet roles

| Node | Planned relationship to ORCA | Current proof boundary |
| --- | --- | --- |
| ANVIL | Operator console, development, and review client | Inventory only; no production service placement |
| FORGE | Primary infrastructure/Gitea; candidate authoritative ORCA host | Authenticated heartbeat logic tested locally; live state unproven |
| KILN | Inference/supporting-services worker | Local model inventory read only; runtime and commands disabled |
| EMBER | Backup, monitoring, UPS/NUT, and recovery observer | No live ORCA enrollment or restore role proven |
| IRIS | BGM edge client for MQTT/logging/calibration/inference/dashboard signals | Separate BGM lane; physical/production effects are R3 |

This table does not choose the production ORCA host. That placement is a release
decision. Until then every node is a client identity and starts `unproven`.

## Production topology requirements

1. One authoritative writer owns mutable ORCA state. Nodes never share or copy a
   writable SQLite database.
   Schema-v4 state revisions remain digest-bound to their referenced evidence
   head; startup and health must fail closed if either side is invalid.
2. Every API mutation uses a per-identity credential over authenticated,
   encrypted transport; the local operator token is not a multi-host identity
   system.
3. Enrollment stores only key fingerprints. Secret key material remains in the
   approved host-scoped secret system and is never written to evidence, Drive,
   Notion, git, or the UI.
4. Heartbeats carry the node identity, timestamp, monotonic nonce, and signature.
   Replay, clock-window failure, unknown identity, bad signature, and stale
   contact fail closed and pause new work.
5. Every mutation carries an idempotency key, expected state revision, actor,
   lane, job/correlation ID, permission level, and approval reference when
   required. Stale revisions and duplicate/conflicting keys fail closed.
6. Remote commands remain unavailable until a separately reviewed transport,
   command grammar, per-node allowlist, timeout, output bound, rollback, and
   emergency-stop path all pass live acceptance.
7. Automatic active/standby promotion is prohibited initially. A human-approved
   failover restores a verified backup, proves evidence-chain continuity, and
   records the new authority before mutations resume.

## Schema and release migration protocol

1. Identify an approved release by immutable commit/release digest; reject a
   dirty working tree as a production source.
2. Enter maintenance mode, stop mutations, and verify the current evidence hash
   chain, state digest/evidence-head binding, and schema version.
3. Create a recoverable database copy, checksum it, and record its location
   without copying secret material.
4. Restore the copy in an isolated directory and run the release's migration and
   complete rebuilt test suite before touching authoritative state.
5. Apply each ordered migration in one transaction. A missing step, newer schema,
   checksum mismatch, or failed postcondition aborts the release.
6. Start loopback-only, verify integrity health, state counts, approvals, pauses, incidents,
   retention, costs, security records, fleet enrollment fingerprints, emergency
   stop, and evidence-chain continuity.
7. Only after QUENCH signs the evidence may Fry approve transport exposure and
   controlled client enrollment. Keep writes, runtimes, and commands disabled
   during the first observation window.
8. On any discrepancy, stop mutations, preserve failed artifacts, restore the
   pre-migration copy, verify its chain, and open an incident.

## Hardware acceptance matrix

For each of ANVIL, FORGE, KILN, EMBER, and IRIS preserve evidence for:

- expected node fingerprint and lane;
- successful fresh signed heartbeat and replay/stale/bad-signature rejection;
- healthy -> degraded -> offline transitions and automatic node pause;
- emergency-stop behavior while connected and while disconnected;
- read-only degraded operation with connectors, model runtime, and commands off;
- recovery after restart without nonce rollback or duplicate mutation;
- no secret value in logs, state snapshots, alerts, or UI;
- QUENCH review and Fry decision for every release-impacting exception.

IRIS additionally requires an explicit BGM safety review before any MQTT write,
calibration change, cellular action, physical output, or body-adjacent workflow.

## Release evidence required

- approved release digest and clean-build record;
- schema pre/post versions, backup checksum, and rollback result;
- rebuilt and combined regression test outputs;
- rendered desktop/phone UI evidence;
- per-node authenticated heartbeat and fault-injection results;
- connector read/write counts proving writes remained disabled unless separately
  approved;
- cost report proving the approved cap was not exceeded;
- independent QUENCH disposition;
- Fry's exact R3 approval naming commit/push/merge/deploy/cutover and any legacy
  archive or deletion separately.

This plan is not deployment approval and does not establish live node health.
The offline readiness checker can inventory fixed-schema, revision-bound local
artifacts, but reports them only as `present_unverified` and keeps them blocking.
Local JSON cannot authenticate QUENCH, credential restoration, or deployment;
clearing those checks requires a separately trusted verifier with pinned trust
roots that is not available in this rebuild.
