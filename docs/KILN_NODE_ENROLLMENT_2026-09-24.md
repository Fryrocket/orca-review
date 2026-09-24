# KILN Node Enrollment — 2026-09-24

## Outcome

KILN is enrolled as an authenticated ORCA inference node reporting to the
authoritative FORGE control plane. Its SMITH and QUENCH model inventories are
checked before each heartbeat. The node reports `healthy` only when both are
available.

This deployment does not enable remote execution, provider writes, jobs,
cloud spend, or model invocation by ORCA.

## Deployed release

- Source commit: `c7b44f36094b9563e09d1daaa79b343547f2b1c2`
- Release archive SHA-256:
  `a46e8c81dfd7ae5bc6259215716999de344a78475e4c9a30b9c7437abec9ded8`
- FORGE release: `/opt/orca/releases/c7b44f36094b9563e09d1daaa79b343547f2b1c2`
- KILN release: `/opt/orca-node/releases/c7b44f36094b9563e09d1daaa79b343547f2b1c2`
- Full verification: 517 tests passed.
- The release was import-tested with KILN's installed Python 3.10 before activation.

## Authentication and transport

- KILN uses a 48-byte random heartbeat key stored only at
  `/var/lib/orca-node/kiln-heartbeat.key`, owned by `fryrocket`, mode `0600`.
- Enrollment transferred the key through the existing encrypted KILN→FORGE
  SSH path while FORGE's ORCA service was stopped. FORGE persists only the key
  fingerprint and heartbeat verification state.
- Heartbeats are HMAC-signed and sent to FORGE's loopback-only
  `/api/heartbeats` endpoint through `127.0.0.1:18787`, the existing SSH relay.
- Durable nonce state and its lock are owner-only `0600` files under the
  owner-only `0700` `/var/lib/orca-node` directory.
- A controlled service restart advanced the accepted nonce to 3, proving the
  local anti-replay sequence survives restart.

## Live verification

- `orca-kiln-node.service`: active.
- `orca-forge-tunnel.service`: active.
- `smith-inference.service`: active; model inventory returned data.
- `quench-inference.service`: active; model inventory returned data.
- FORGE `/api/health`: healthy; evidence chain valid.
- KILN fleet state on FORGE: healthy, authenticated, last nonce 3.
- Jobs: 0.
- KILN `remote_execution_enabled`: false.
- All provider connector `writes_enabled` values: false.

## Rollback

Stop and disable `orca-kiln-node.service` on KILN to stop heartbeats. Point
`/opt/orca-node/current` and `/opt/orca/current` to their prior immutable
release directories and restart the corresponding ORCA units. Do not reuse or
delete nonce state while the current enrollment remains valid; re-enrollment
with a new key is required for key rotation.
