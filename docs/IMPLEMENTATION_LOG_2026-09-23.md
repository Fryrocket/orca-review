# ORCA implementation continuation — 2026-09-23

This record continues the local policy-first rebuild on ANVIL. It does not
authorize a push, deployment, remote exposure, connector write, model runtime,
spend, or cutover.

## Implemented

- Added per-identity bootstrap-token authentication for all HTTP mutations.
- Bound authenticated identities to `actor` and `requested_by` fields so a
  valid credential cannot impersonate another registered identity.
- Added endpoint authorization for incident creation and security-gate scans.
- Stored configured tokens only as in-memory SHA-256 digests; no token is
  written to SQLite, evidence, snapshots, logs, or the UI.
- Added an owner-only, regular, non-symlink JSON token-file loader. Group/world
  access, malformed files, unknown identities, short tokens, and reused tokens
  fail closed.
- Kept the existing shared operator token as an explicit loopback compatibility
  mode, but bound it to Fry and required the same idempotency/revision envelope.
  The server rejects configurations that enable both authentication modes.
- Updated the console to select an acting identity and send identity-bound
  credentials. Authorization still comes from the control plane; selecting an
  identity does not grant its authority without the matching credential.

## Verification

- Rebuild suite: **273 passed**.
- Combined retained-legacy and rebuild suite: **516 passed**.
- Clean-install/reconstruction drill: **passed**, including **273 tests** in a
  fresh temporary directory with no downloaded dependencies.
- Python compilation: passed for `orca`, `mao`, scripts, and both test trees.
- JavaScript syntax: `node --check orca/static/app.js` passed on the local Mac.
- `git diff --check`: passed.
- Rendered console QA: passed at the default desktop viewport and a 390×844
  phone viewport, with no browser warnings or errors. The identity controls
  remain labeled, readable, and single-column on the phone breakpoint.

## Continuation tranche

- Added append-only SQLite mutation receipts. Identity-authenticated writes now
  require both `Idempotency-Key` and `X-ORCA-Expected-Revision`; a receipt, the
  state change, and its evidence commit atomically or roll back together.
- Bound receipts to the authenticated identity, operation, and request digest.
  Exact retries return the stored redacted response; key reuse with different
  content, identities, or operations fails closed. Stale revisions are rejected.
- Added a restart-safe heartbeat agent that persists its next nonce in an
  owner-only regular file before transport. Failed or unacknowledged attempts
  burn their nonce, and corrupt, replaced, missing, or rolled-back state fails
  closed. Transport remains injected and no network client was enabled.
- Added a persistent notification outbox with deterministic queued, retry,
  delivered, and dead-letter transitions; bounded backoff; payload redaction;
  hashed idempotency keys; and duplicate suppression. S2/S3 incidents enqueue
  safe notification records, but no delivery transport is configured or run.
- Added restart/corruption/stale-instance coverage across jobs, approvals,
  pauses, incidents, exceptions, retention, costs, fleet nonces, and emergency
  stop state. Added HTTP envelope replay/conflict/rollback coverage.
- Corrected and separately styled the operator-control form after rendered QA;
  the desktop grid and phone layout were both inspected in the real console.

## Fail-closed hardening audit

- Moved integrity verification ahead of idempotent replay. A stored response can
  no longer be replayed while the evidence chain, control snapshot, or receipt
  table is corrupt.
- Upgraded the database through schema v4. Receipts digest every durable field,
  validate canonically on startup and mutation, migrate from v2, and remain
  append-only. Expected revision is part of the request digest; stale revisions
  are HTTP conflicts, and responses expose both current and receipt revisions.
- Required the saved control-state evidence head to equal the current verified
  chain head. Evidence-only control paths now checkpoint state; an orphaned or
  extended chain without a corresponding snapshot fails startup.
- Added owner-only inter-process heartbeat locking and multiprocess contention
  tests. Only explicit positive acknowledgements succeed; rejections and
  sanitized transport failures burn their nonces. State/detail inputs are bounded.
- Made receiver time authoritative for heartbeat freshness. Key rotation resets
  health to unproven, pauses targeted work, invalidates the prior key, and needs
  a fresh signed heartbeat plus explicit resume. Unproven targeted jobs fail closed.
- Hardened notification delivery with explicit positive acknowledgements,
  content-bound duplicate detection, payload/count/retry bounds, concurrency
  locking, persistent evidence-backed outcomes, and provider idempotency keys.
  The old duplicate alert list is now a read-only projection of one canonical
  outbox. No provider/network transport is built in or enabled.
- Incident evidence now records the authenticated Fry/ORCA actor rather than
  attributing every incident to ORCA.

## Unattended-safe continuation

- Anchored the complete mutation-receipt set in schema v4. Missing receipt
  tables and deleted first, middle, last, or all rows now fail integrity checks;
  exact table/trigger shapes and raw field types are validated, migrations and
  nested writes roll back atomically, and multi-query reads share one snapshot.
- Split notification processing into a durable pre-provider attempt reservation,
  an injected transport call outside the global control-plane/SQLite lock, and
  a transactional outcome commit. Items are leased only immediately before
  delivery; crash-expired attempts become explicit unconfirmed retry/dead-letter
  outcomes, completion time drives backoff, and all derived times are bounded.
  No delivery transport was configured.
- Added a clock-injected, explicit `MaintenanceTicker.tick()` foundation for
  stale-node expiry. It has no thread, scheduler, service, or network client;
  repeated ticks are idempotent and transitions persist across restart.
- Anchored heartbeat state, lock, temporary writes, replace, cleanup, and fsync
  to an owner-controlled non-symlink directory descriptor. Symlink swaps,
  non-owner parents, broad write permissions, and rollback loss fail closed.
- Bounded connector result size, item count, and depth; rejected cycles,
  unsupported values, redaction-key collisions, and non-finite values; and
  removed provider exception context from the returned failure.
- Browser mutations now capture one immutable body/key/revision/header envelope
  and reuse it once only after transport uncertainty. HTTP responses are never
  automatically retried, and mutation controls remain disabled while pending.
- Added an offline, read-only release-readiness checker. Local tracked artifacts
  can only become `present_unverified`; they stay blocking because this rebuild
  has no external pinned verifier. The checker never grants production readiness.
- Security-scan evidence now records the authenticated requester separately
  from the advisory engine and subject author. Mutation revision headers are
  taken from the atomic receipt rather than a later concurrent state read.
- Before syncing, ANVIL received a rollback copy at
  `/tmp/orca-pre-tranche4-20260924T0432Z`. A checksum dry run confirmed the
  tested files exactly match the local copies. The final recovery report is at
  `/tmp/orca-recovery-final-20260924T051305Z.json` on ANVIL; it completed at
  `2026-09-24T05:13:05Z` with database SHA-256
  `594211f729744f28a841f8c3218a73403dc5b44c261c564f42d11283809fffd5`.

## Boundary

This closes the local shared-token actor-impersonation, duplicate-mutation,
receipt-omission, old-evidence-head, transport-lock, replay-integrity, and local
nonce-parent gaps, but it is not the multi-host identity solution. Non-loopback
binding remains disabled. Reviewed encrypted transport, independent node/service
credentials, credential rotation/revocation, a deployed scheduler, live
notification delivery, live fleet acceptance, and external trust anchors remain
work. The RX9700 is not required for those control-plane tasks; model-runtime
enablement and quality acceptance remain a separate later phase.
