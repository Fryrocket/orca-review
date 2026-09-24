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
- Lost node contact: keep the node paused. Recovery requires a fresh authenticated heartbeat and explicit resume.
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
