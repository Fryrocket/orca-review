# STATE.md — v11
AS OF 2026-09-24T1430Z — Codex consultant, ORCA observation deployment.
Supersedes v10 (2026-09-21T1618Z). Read this FIRST every session. Cap 100 lines.

## AUTHORITY AND ROSTER

- cc-bridge is the operational handoff; newest verified packet wins over stale state.
- Codex is a consultant seat. No seat authority; ROSTER_LOCK holds. Merges and
  pushes remain Fry's gate. Grok has been out of all seats since 2026-09-13.
- Current design identities: ORCA routes/policies; SMITH implements; QUENCH
  reviews; security gate advises only; Fry decides R2/R3 and merge/deploy.
- No identity may author, approve/review, and deploy the same change.

## LANES AND REPOS

- FORGE — LIVE at `192.168.7.30`; Gitea 1.27.3 is primary. KILN retains rollback.
  INV active; BGM quiet; CLOUDFLARE live.
- v10 repo pins remain the last verified deployed/operations state: orca
  `352a4e6`, forge-ops `bf9ac09`, forge-vis `3315619`; all had one unpushed
  commit and forge-vis had a dirty `nodes.forge.json`.
- NEW LOCAL ORCA REBUILD: `/Users/fryrocket/claude-server/orca-rebuild`, branch
  `agent/orca-rebuild-v1`, cloned from GitHub `Fryrocket/orca-review`; local
  release commit `28340bd` is unpushed and deployed loopback-only on FORGE.
- Older local `orca` and `orca_verify` trees are stale/dirty. Do not treat them
  as authority. They remain rollback/history surfaces; nothing deleted.

## ORCA REBUILD — IMPLEMENTED AND TESTED LOCALLY

- New policy-first `orca/` package; legacy `mao/` retained pending R3 cutover.
- Stable ORCA/SMITH/QUENCH/security-gate/Fry registry and project lanes.
- R0–R3 classifier; push/merge/deploy/remote/production are Fry-only R3.
- Separation-of-duties checks; job states; approval-preserving pause/resume.
- Schema v4 binds evidence head/receipt set; reads use one SQLite snapshot and exact schema guards.
- All Notion/Linear/GitHub/Gitea/Slack/Drive/Cloudflare actions are classified;
  every connector write remains disabled.
- Local-first routing; cloud fallback requires Fry R3 plus a positive cost cap.
- Responsive operator console: overview, work, approvals, evidence, incidents,
  security, agents, fleet, connectors, and costs. Loopback bind by default.
- Hardware fleet registry: ANVIL, FORGE, KILN, EMBER, and IRIS. Targeted jobs fail
  closed while unproven; rekey invalidates health, receiver time drives expiry,
  and nonce state is locked under an owner-controlled directory plus injected transport.
- Core bot definitions: ORCA, SMITH, QUENCH, and independent advisory security
  gate. Author/review separation and pause propagation are enforced; model/tool
  runtimes remain disabled and the security gate has no approval/deploy authority.
- SQLite persists control/security/retention, omission-detecting receipts, and a
  leased outbox; attempts reserve before unlocked provider calls and uncertainty is explicit.
- All token modes require actor-bound idempotency/revision envelopes; replay verifies integrity and conflicts fail closed.
- Explicit maintenance ticks and retry/dead-letter transitions persist; no scheduler/delivery is enabled.
- Strict bot contracts/evals, bounded security/supply-chain scans, deny-by-default tools, budget status,
  and a $0 cap are implemented; actual bot runtime remains disabled.
- Provider/action profiles and R0 Notion→Linear→Gitea→Drive reads are verified.
- Non-loopback bind and POST default disabled; strong-token/Host/CSP gates apply.
- Per-identity credentials bind actors; shared compatibility mode is Fry-bound.
- Rebuild: **273 passed**; legacy: **243 passed**; combined: **516 passed**.
- Review regressions and later adversarial race cases are fixed; see the code review and implementation log.

## ORCA REBUILD — OPEN / UNPROVEN

- Release `28340bd` runs as a hardened loopback-only FORGE service; no push, PR, merge, Gitea write, provider write, GPU runtime, or cutover. See `DEPLOYMENT_FORGE_2026-09-24.md`.
- ANVIL reaches the console through a persistent loopback tunnel relayed by KILN; no LAN listener exists.
- Alert delivery stays disabled; retention is guarded/audited with zero deletion.
- Clean install/reconstruction passed 273 tests on schema v4 with integrity checks.
- Bounded live reads passed for ANVIL/FORGE/KILN/EMBER and six provider systems; IRIS, heartbeat lifecycle, Cloudflare, credential restore, and multi-host deployment remain open. See `LIVE_FLEET_PROVIDER_TEST_2026-09-24.md`.
- Autonomous cloud budget remains zero. No model/API purchase is authorized.
- Rendered desktop and 390×844 phone QA passed with no browser warnings/errors.
- QUENCH verified exact clean commit `9eb7638`: 516 tests and isolated schema-v4 recovery passed. Trusted external evidence, approved-release/secret restore, and deployment drills remain open.
- Legacy removal/archive is R3: stop for Fry after acceptance and rollback proof.

## VERIFIED FORGE STATE CARRIED FROM v10

- SSH was verified two-way Forge↔KILN/EMBER; authorized-key change was explicitly
  Fry-approved. Default constraint against editing `authorized_keys` remains.
- Prior PASS counts (not failures): Orca 266; FORGE-VIS 149 + 35 subtests; backup safety 9;
  gitea-rebind 8; inventory 7. Those counts apply to legacy/current deployed
  code, not the new rebuild.
- Six backup scripts and installed gitea-rebind byte-matched tracked copies.
- P1 LAN auth retest allowed loopback and refused LAN/tailnet without token.
- Restore monitor remained `awaiting_first_run`; first scheduled unattended run
  was 2026-09-27 04:15. Outcome not verified in this update.

## OPEN FOR FRY / STANDING

- Existing unpushed repo commits remain unresolved; this update does not push.
- Forge is repairable, not yet proven fully rebuildable. Compose, `.env`, and
  `/srv/vault` capture decisions remain open. Never put secret values in Drive/git.
- Same-building-only backup, KILN rollback Compose, Gitea update policy, DHCP,
  WoL, Tailscale, key-only SSH, credential rotation, WD replacement, and EMBER
  NUT exposure remain as in v10 unless a newer verified packet proves otherwise.
- BGM plaintext MQTT-password artifact remains a secret-exposure issue. Do not
  repeat or copy the value.

## DO NOT REOPEN / SAFETY

- Lanes do not mix. Fry gates merges/pushes. Never bypass permission classifier.
- Deletion, secrets, spend, publication, physical/body actions, and production
  impact are R3. Preserve evidence and rollback; plans are not proof.
- Disk identity is by SERIAL, never `/dev` name. `ssh-keyscan` is not login proof.
- Verify live state before acting; this file is a dated snapshot.

END STATE.md — AS OF 2026-09-24T1430Z
