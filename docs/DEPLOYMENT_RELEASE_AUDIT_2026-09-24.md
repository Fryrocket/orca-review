# ORCA Deployment Release Audit — 2026-09-24

Mode: read-only post-deployment verification. No provider write, inference
request, credential change, remote execution, spend, push, or cutover.

## Release identity

- Authoritative source repository HEAD:
  `9f35bb706bb7ce6ae154a56ad2f4be240a4d9e69` (documentation-only commits
  follow the deployed source).
- Deployed source release:
  `c7b44f36094b9563e09d1daaa79b343547f2b1c2`.
- Release archive SHA-256:
  `a46e8c81dfd7ae5bc6259215716999de344a78475e4c9a30b9c7437abec9ded8`.
- FORGE and KILN release trees produced the same aggregate byte manifest:
  `869896ca68b36490b658d38a3926e6f5ba70f1ba771dc8f985b2de21cbaed066`.

The only repository changes after the deployed source release are the KILN
deployment evidence and STATE update. No uncommitted repository changes were
present during this audit.

## Live state

- FORGE `/opt/orca/current` resolves to the deployed source release.
- KILN `/opt/orca-node/current` resolves to the same deployed source release.
- FORGE `orca.service`: active; `/api/health` healthy; integrity valid.
- KILN `orca-kiln-node`, `orca-forge-tunnel`, `smith-inference`, and
  `quench-inference`: active.
- Prior signed-heartbeat verification established KILN healthy and
  authenticated, both inference inventories present, and nonce persistence
  across a controlled agent restart.

## Readiness result

The offline readiness checker inspected clean repository revision
`9f35bb706bb7ce6ae154a56ad2f4be240a4d9e69` and correctly returned
`production_ready: false` with these blockers:

- `evidence_manifest`
- `independent_review`
- `credential_restore`
- `deployment_verification`

This audit is local evidence. It does not clear those blockers, authenticate
an external reviewer, prove restored credentials, authorize writes, or grant
production/cutover approval.
