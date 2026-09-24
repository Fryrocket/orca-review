# ORCA v1 control-plane rebuild — implementation handoff

Date: 2026-09-23
From: Codex consultant
To: Claude / ORCA owner
Lane: ORCA / Forge
Status: Local implementation tested and reviewed by its implementer; not independently reviewed, committed, pushed, merged, deployed, or connected to live write-capable services.

## Latest checkpoint - 2026-09-23 21:19 UTC

This checkpoint supersedes test counts in the historical slices below. Fry asked to address "-266 failures", provide a printable action list, and review/test the local code. The fresh baseline was 332 passing tests, with no failing tests. The 266 in STATE was a historical deployed-code pass count; the user's specific "-266" display has not been identified.

The review reproduced 23 newly added failing regression cases, then fixed them. The final combined corpus passes **355 tests: 112 rebuilt and 243 legacy**. Both JavaScript files pass syntax checks; Python compilation across `orca`, `mao`, `scripts`, `tests_v1`, and `tests` passes. The isolated clean-install/recovery drill passes with all 112 rebuilt tests, schema-v2 evidence/state verification, emergency stop, and simulated node recovery/stale-contact checks.

Fixes cover named-credential redaction, approval-preserving pause/resume, terminal-state protection, strict permission/cloud/cap input validation, same-key heartbeat replay protection, serialized shared-database cost accounting, independent review of R0 ORCA/QUENCH work, explicit LAN bind authentication, legacy cost/metadata recovery validation, supplied message-bus preservation, and request/CSRF protection for the legacy human approval gate.

Full review: `CODE_REVIEW_2026-09-23.md`. Printable owner checklist: `output/pdf/ORCA_action_checklist_2026-09-23.pdf`. No connected browser was available, so rendered desktop/phone QA remains open. No independent QUENCH review, production deployment, cloud spend, connector writes, or live fleet acceptance is claimed.

## Request

Fry asked for Orca to be rebuilt from the accumulated conversation history, Google Drive, Notion, GitHub, Forge Gitea, Linear, the adopted permission model, the intended AI stack, agent tasks, and the visual interface requirements.

## Sources reconciled

- `cc-bridge/STATE.md` v10 and the latest Forge connector operating-model handoff.
- Notion: ORCA Rules & Permission Ladder.
- Notion: Forge — Agent Identity, Evidence & Incident Standard.
- Notion: Forge — Jobs, Models & Cost Registry.
- Notion: FORGE-VIS and Forge Infrastructure & Operations.
- Linear FOR-5: Implement the Agent Identity, Evidence & Incident Standard.
- GitHub `Fryrocket/orca-review`, current public tip `a3f524b`.
- Forge Gitea repository inventory, including `fry/orca-review` with pull-only access for the inspected identity.
- Local `~/claude-server/orca` and `orca_verify` trees, both stale/dirty and retained only as historical context.

## Architecture decision

The August `mao` implementation is retained as a regression corpus and rollback surface, but it is not the new architecture. It models an earlier Claude/Grok orchestration loop. The adopted September operating model instead requires stable identities and separation of duties:

- ORCA: policy, routing, approval boundaries, lane isolation, and escalation.
- SMITH: coding and implementation.
- QUENCH: independent technical review and verification.
- Fry: R2/R3 decisions, exceptions, merges, pushes, deployments, spending, publication, secrets, physical work, and recovery authorization where required.

No identity may author, review/approve, and deploy the same change.

## Local workspace and branch

- Clean rebuild clone: `/Users/fryrocket/claude-server/orca-rebuild`
- Branch: `agent/orca-rebuild-v1`
- Source remote: `https://github.com/Fryrocket/orca-review.git`
- Legacy trees were not deleted. Deletion/cutover remains R3 and requires Fry.

## Implemented in the first vertical slice

1. Stable identity registry for ORCA, SMITH, QUENCH, and Fry.
2. Explicit Forge/BGM/Inventory/Cloudflare/AWS/PCCG/ORCA project lanes.
3. R0–R3 policy classifier.
4. R2/R3 approval objects that only Fry can decide.
5. Separation-of-duties enforcement.
6. Job lifecycle with ready, waiting-approval, paused, denied, review, complete, and failed states.
7. Per-job pause with evidence.
8. Append-only SQLite evidence events with correlation IDs and a SHA-256 hash chain.
9. Evidence-chain verification and correlation filtering.
10. Connector registry for Notion, Linear, GitHub, Forge Gitea, Slack, Google Drive, and Cloudflare.
11. Connector writes disabled by default.
12. Local-first model routing with explicit cloud-approval and budget-cap checks.
13. Responsive operator dashboard and JSON API.
14. Dashboard views: Overview, Work, Approvals, Evidence, Agents, Connectors, and Costs.
15. UI truth states, R-level badges, approval-required banner, evidence integrity display, and phone/desktop responsive rules.
16. Loopback binding by default; no secret values stored or displayed.
17. Rebuild specification and cutover acceptance gates in `docs/REBUILD_SPEC.md`.

## Verification

- New rebuild suite: **9 passed**.
- Policy boundary regression found and corrected during testing: read-only actions were initially over-classified because rollback logic was applied to R0 reads. The classifier now applies rollback escalation only to state-changing actions.
- Local HTTP test verified `/api/state`, evidence integrity, the four identities, and that every connector is read-only by default.
- Static UI test verifies all required views and responsive viewport configuration.
- Rendered browser QA is still open because no in-app or external browser connection was available in the session.

## First-slice gaps (historical; later entries supersede resolved items)

This checkpoint records what remained after the initial nine-test slice. Later
dated sections and the final acceptance slice are authoritative for current state.

- No commit, push, pull request, merge, Gitea write, deployment, systemd service, container, or production cutover.
- No live connector write path.
- No Slack alert routing.
- No S0–S3 incident persistence/routing or deduplication yet.
- No global emergency stop or per-agent pause yet; only per-job pause exists.
- Jobs and approvals are currently in-memory; evidence persists in SQLite.
- No retention/access-control policy implementation.
- No secret scanner/redaction middleware.
- No cost metering or approved cloud budget; autonomous cloud budget is zero.
- No advisory-only end-to-end connector drill.
- No independent QUENCH review.
- No restore/rebuild drill.
- Legacy `mao` remains present; no destructive removal was performed.

## Fleet expansion — 2026-09-23

ORCA now treats the hardware fleet as a first-class control surface. The registry includes ANVIL, FORGE, KILN, EMBER, and IRIS with stable IDs, duties, lanes, address labels, permission floors, pause state, and explicit remote-execution state. Jobs may target a node; unknown nodes and cross-lane targets fail closed. Per-node pause blocks newly submitted work and records hash-chained evidence. Node health supports healthy, degraded, offline, and unproven states with last-verification timestamps.

The operator console includes a Fleet view. Inventory presence is not reported as live health: every node starts unproven. Remote execution remains disabled on every node. No SSH action, service change, deployment, or physical action was performed.

The expanded fleet rebuild suite passed **12 tests**.

## Bot build slice — 2026-09-23

The current stable bot roster is now represented as inert, policy-gated definitions: ORCA routes orchestration work, SMITH receives coding/documentation/operations-plan work, and QUENCH receives independent review/security-review/verification work. A deterministic queue endpoint routes a declared task type and lane to exactly one bot, then records both submission and routing in the evidence chain. Bots can be paused independently.

No model or tool runtime is enabled. AMPERE and RELAY are preserved as legacy migration candidates and are not active identities. The durable next queue is: transactional state persistence; versioned prompt/output contracts; deny-by-default tool manifests; sandboxed local adapters with zero cloud budget; offline evaluations; an explicit AMPERE/RELAY decision; then an independent security-bot design without merge/deploy authority.

The expanded rebuild suite passes **15 tests**.

## Persistence and incident slice — 2026-09-23

Transactional SQLite snapshots now preserve jobs, approvals, incidents, bot/node/lane pauses, node health, and global emergency-stop state across restart. The emergency stop is Fry-only and new work fails closed into paused state while it is active.

The S0–S3 incident lifecycle supports open → contained → closed, requires Fry or independent QUENCH to close, persists across restart, and emits correlated evidence. Secret-shaped strings are redacted before evidence or incident details are stored. The console now exposes incidents and emergency-stop state.

The expanded rebuild suite passes **19 tests**.

## Runtime contract and cost slice — 2026-09-23

ORCA, SMITH, and QUENCH now have versioned v1 prompt contracts and required output fields for summary, evidence, uncertainty, and next gate. An offline evaluator rejects missing fields and secret-shaped output. Runtime invocation remains hard-disabled until a sandboxed local adapter is reviewed.

The tool catalog and per-bot manifests deny every tool by default, including unknown tools. A persistent cost ledger attributes usage by job, bot, lane, model, and connector; negative usage is rejected and the default hard cap remains $0, so paid execution fails closed.

The expanded rebuild suite passes **24 tests**.

## Authenticated fleet and connector slice — 2026-09-23

Fleet enrollment is Fry-only and stores a SHA-256 key fingerprint, never the node key. HMAC-SHA256 heartbeats validate node identity, timestamp freshness, signature, and a monotonically increasing nonce. Bad keys, forged signatures, replay, stale timestamps, and unauthenticated claims of healthy status fail closed. Loss-of-contact transitions enrolled nodes to degraded/offline and automatically pauses new work on the node. Remote command execution remains disabled.

A connector gateway now prepares classified R0 requests for declared read/get/list/search operations across the registered connectors. Unknown connectors and all mutation operations fail closed. This is capability preparation only; it performs no live provider calls or writes.

The expanded rebuild suite passes **29 tests**.

## Operator authentication and recovery slice — 2026-09-23

All HTTP POST mutations now default to unavailable. When explicitly configured, they require an exact `X-ORCA-Operator-Token`; missing configuration returns 503 and incorrect credentials return 401. The console includes an in-memory-only token field, required reason, and emergency-stop toggle. Token values are not persisted or displayed.

Read-only adapters enforce connector identity, canonical paths, allowlisted origins, and GET-only injected transports. Scoped node executors validate explicit target addresses and a small read-only command allowlist, but execution remains hard-disabled pending review and approval.

`docs/RECOVERY_RUNBOOK.md` now defines inputs, restore verification, authentication checks, stale-node handling, evidence requirements, failure rollback, and the acceptance evidence for a real drill. At this checkpoint no drill had yet been claimed; the local recovery section below supersedes that status.

The expanded rebuild suite passes **33 tests**.

## Governance, alerting, and cost visibility slice — 2026-09-23

Open incidents now deduplicate by normalized lane/title fingerprint. S2/S3 incidents create one persistent Slack-targeted alert record with status `queued_write_disabled`; this is evidence of intended routing, not delivery. Connector writes remain disabled.

The control-plane snapshot now publishes explicit retention and access declarations: evidence is append-only with no automatic deletion, historical records have minimum retention targets, deletion remains Fry R3, and evidence deletion is granted to no agent. At this checkpoint enforcement beyond append-only evidence and a real retention drill remained open; the final hardening section records the later dry-run guard and audit implementation.

The cost ledger now reports token and dollar attribution by bot, lane, model, and connector. The console renders recorded usage and the approved hard cap from live state rather than static text. The autonomous hard cap remains $0.

The expanded rebuild suite passes **35 tests**.

## Operator interaction and visual-QA checkpoint — 2026-09-23

The console now renders pending approval approve/deny controls and per-job pause controls. They reuse the in-memory operator token and require a reason/note; the server independently enforces authentication and Fry-only approval decisions. JavaScript syntax validation and the full automated suite pass.

Rendered phone/desktop QA was attempted against a successfully started loopback server, but the browser runtime reported no available in-app or extension browser. Browser inventory was explicitly empty. No visual-pass claim is made; this gate remains open.

## Persistence concurrency slice — 2026-09-23

SQLite now uses a busy timeout and WAL for file-backed databases. Evidence appends acquire an immediate write transaction before reading the previous hash, preventing concurrent connections from creating sibling chain entries. A 100-event, eight-worker, two-connection test preserves a valid chain.

Control-plane snapshots use optimistic revisions. Every mutating operation rejects a stale controller instance before changing state or appending evidence, preventing silent last-writer-wins overwrites. The restored state test confirms the newer writer remains authoritative. This is local multi-connection evidence, not a multi-host deployment claim.

The expanded rebuild suite passes **37 tests**.

## Schema and local-model boundary slice — 2026-09-23

The database now records an explicit schema version. Databases from a newer ORCA build fail closed, and missing future migration steps cannot be skipped. This checkpoint introduced version 1; the final durability slice below migrates the current baseline to schema v2.

The sandboxed local-model adapter accepts loopback HTTP `/api/generate` only, requires an explicit model allowlist, bounds prompt and output size, disables streaming and tools, requests JSON, and rejects malformed or contract-failing output. It has no cloud fallback and remains unbound to live bot execution.

A read-only Ollama inventory check on ANVIL returned one installed model: `llama3.2:3b` with digest beginning `a80c4f17`. Inventory is not runtime approval. No model generation was invoked and the ORCA bot runtime remains disabled.

The expanded rebuild suite passes **41 tests**.

## Enforced job lifecycle slice — 2026-09-23

Jobs now move through ready → running → review → complete under identity checks. Only the assigned bot may start and submit its work for review. The reviewer must be a registered review identity distinct from the author, and completion requires a non-empty evidence note. The console exposes start, request-review, and complete-review controls through the authenticated mutation API.

Pausing a bot now pauses its ready/running jobs. Engaging the global emergency stop pauses all ready/running work. An R2/R3 approval made while a bot, lane, node, or global stop is active remains paused rather than becoming runnable.

The expanded rebuild suite and dashboard JavaScript syntax pass with **44 tests**.

## Provider profiles and live advisory read — 2026-09-23

Provider profiles now constrain Notion, Linear, GitHub, Forge Gitea, Drive, Slack, and Cloudflare to declared origins and path prefixes. The in-process advisory workflow requires Notion, Linear, Gitea, and Drive readers, records only redacted result digests, and asserts `write_count == 0`.

A live R0 evidence pass successfully read the canonical Notion ORCA policy, Linear FOR-5 and Forge project results, public Forge Gitea `fry/orca-review` metadata, and canonical Drive STATE v11. No provider write, git operation, model call, or remote command occurred. `docs/LIVE_ADVISORY_READ_2026-09-23.md` preserves the verification boundary.

The expanded rebuild suite passes **46 tests**.

## Local recovery drill — 2026-09-23

The first direct drill attempt failed because the script entrypoint could not import the repository package; the script was corrected rather than counting the failed attempt. A later clean-package attempt also exposed missing build-backend metadata and package-data declarations; those packaging defects were fixed rather than waived. The final rerun copied the current rebuild into a fresh temporary directory, installed it without downloading dependencies, ran all 103 rebuilt tests from the copy, seeded and checksummed a SQLite database, reopened restored state, verified the evidence chain and schema-v2 state binding, exercised and cleared emergency stop, recovered authenticated FORGE state before proving stale/offline/pause transitions, and recovered paused KILN state.

`docs/RECOVERY_DRILL_2026-09-23.json` contains the machine-readable result, completed at `2026-09-23T20:10:23Z`, and database SHA-256 `3311ef639202957464b126b75d26c734b79cb92afa7251fa7ddab5de9e527d93`. This proves local reconstruction from the current uncommitted working tree. It does not prove restoration from an approved release, secret restoration, deployment, or independent QUENCH review.

## Independent security-gate slice — 2026-09-23

A neutral `security_gate` identity and bot definition now provide deterministic, advisory-only inspection of supplied text artifacts. The gate detects secret-shaped values, privileged containers, disabled TLS verification, world-writable permissions, downloads piped to shells, and wildcard network binds. Secret detection shares the central redaction rules, and persisted excerpts contain only the exact matched construct. It emits bounded redacted evidence, stable finding fingerprints, severity, remediation, and a pass/review/block-and-escalate recommendation.

Reports persist transactionally, enter the hash-chained evidence log, and appear in a dedicated operator-console Security view. An authenticated local API can submit a scan, but the gate has no repository or connector reader, tool manifest, model runtime, author/reviewer/approval authority, merge authority, deployment authority, or autonomous enforcement. Submitted source artifacts are not persisted. S2/S3 recommendations do not change job state automatically.

`docs/SECURITY_GATE_THREAT_MODEL.md` records the trust boundary, bounded-input rules, current checks, acceptance criteria, independent adjudication, Fry-only record-only exceptions, and gates before enforcement. The canonical cc-bridge copy is [CC_ORCA_security_gate_threat_model_2026-09-23.md](https://drive.google.com/file/d/1u7oek8nRub-MWK_bVWJ5loC-wthlTUy3/view?usp=drivesdk). Detection, redaction, authority, persistence, adjudication, exception, retention, HTTP, and UI-source tests are included in the rebuilt suite. JavaScript syntax and a clean local reconstruction drill also pass. This is not a deployed operational security bot and has not received independent QUENCH review.

## Control hardening and acceptance slice — 2026-09-23

The internal control plane now authenticates mutation actors instead of relying only on HTTP routing. Only ORCA or Fry can submit work and pause/resume bots, lanes, or nodes. Push, merge, deploy, publish, spend, remote execution, production changes, cutover, destructive actions, and legacy archival remain explicit R3 actions. Approval records retain the classification rationale and rollback detail.

Every declared connector action is classified. Advisory reads are R0; connector writes are R2 or R3 and remain disabled at the gateway. URL adapters reject encoded traversal, credentials, origin escape, and noncanonical bases. Remote command envelopes now use per-command argument grammars and remain execution-disabled. The runtime evaluator validates an exact bounded result contract, refuses secret-shaped output and unexpected execution fields, and permits cloud fallback only with Fry R3 approval plus a positive cost cap; the current cap is zero.

Evidence rows are append-only under database UPDATE/DELETE triggers. Mutable state and its associated evidence now commit in one immediate SQLite transaction; a failed event or snapshot write rolls back the database, revision, and in-memory objects together. Fault-injected INSERT/UPDATE failures, concurrent append tests, stale-controller tests, and direct tamper tests cover the boundary. Retention is deny-by-default: evidence cannot be deleted, minimum periods are enforced, eligibility requires Fry R3, and the current implementation is dry-run only with zero automatic deletions. Security-gate scans are size/count bounded, independently adjudicated by QUENCH or Fry, and may receive only time-bounded record-only S1/S2 exceptions from Fry; S3 cannot be excepted and no exception changes enforcement.

The operator console now exposes work routing and stop conditions, approval rationale and rollback, evidence retention, security reports/adjudications/exceptions, agent assignments/incidents/pauses/routes/tools/runtime status, fleet enrollment/health, connector action levels, and zero-spend budget status. Host allowlisting and CSP/frame/no-sniff/referrer headers harden the loopback web surface. Automated source and syntax checks pass, but rendered phone/desktop visual QA remains open: two Safari computer-control capture attempts hung, Chrome was unavailable, and the local Playwright installation could not load. A later Safari WebDriver fallback reached the local driver, but session creation timed out because Remote Automation was not enabled; the host configuration could not be authorized non-interactively. The loopback server and driver were stopped, and no rendered-pass claim is made.

The rebuilt v1 suite passes **103 tests**; a combined run of the retained legacy regression corpus and v1 suite passes **332 tests**. The reconstruction drill exercises the 103-test rebuilt package and also proves an offline clean install, restored schema-v2 state/evidence integrity, emergency-stop persistence, authenticated heartbeat recovery, stale/offline degradation, and node pause behavior. Multi-host operation, approved-release restoration, live secret restoration, live hardware heartbeats, delivery writes, deployment, and independent QUENCH acceptance remain unproven.

## Dependency, provenance, and supplied repository-control slice — 2026-09-23

The advisory scanner is now `deterministic-v2`. In addition to secret and unsafe-configuration checks, it detects mutable CI action branch references, workflow-wide write permissions, explicitly disabled branch protection, empty/disabled required status checks, remote Docker `ADD`, mutable `:latest` images, unpinned Python requirements, and dependency manifests supplied without same-directory lockfiles. Artifact-specific matching avoids treating ordinary prose as a requirements file, commented examples are ignored, control characters in artifact names fail closed, and lockfile presence is evaluated within each supplied directory.

These are bounded input-level signals, not proof of live repository policy, vulnerability status, signatures, package integrity, or upstream provenance. The gate still has no connector, model, tool, enforcement, merge, or deployment authority. New adversarial tests cover risky and safe fixtures; final verification counts are **103 rebuilt tests** and **332 combined legacy+v1 tests**.

## Multi-host and migration design slice — 2026-09-23

The HTTP server now refuses every non-loopback bind until reviewed transport security exists, closing accidental LAN/tailnet exposure through a CLI flag. `docs/MULTI_HOST_ROLLOUT_PLAN.md` defines a single-authoritative-writer topology, per-identity authenticated transport requirements, idempotency/revision fields, manual failover, transactional release migration, rollback evidence, and a hardware acceptance matrix for ANVIL, FORGE, KILN, EMBER, and IRIS. It explicitly forbids network-shared SQLite, automatic failover, connector writes, remote execution, secret copying, and production placement before the applicable reviews and Fry R3 decision. The canonical cc-bridge copy is [CC_ORCA_multi_host_rollout_2026-09-23.md](https://drive.google.com/file/d/1rtSBuoI2bvVSSrszkmjwJzJa8Jyufqq8/view?usp=drivesdk).

This is a design and fail-closed local control, not production deployment. Host placement, live credentials, transport implementation, real heartbeats, and migration execution remain unproven.

## Final durability and boundary-hardening slice — 2026-09-23

Schema v2 adds a SHA-256 digest over every serialized control-state revision and its referenced evidence-chain head. The v1→v2 migration upgrades existing snapshots transactionally. Startup, mutation, snapshots, and HTTP health now fail closed on a changed state payload, missing evidence reference, broken evidence chain, stale controller, or newer unsupported schema. Mutable state and its related event still commit in one immediate transaction, and injected state failures restore both SQLite and the existing in-memory object graph.

Durable inputs are redacted before persistence, including dictionary keys, job/action fields, approvals, node detail, cost dimensions, connector results, and model output. Evidence, actions, security artifacts, HTTP bodies, prompts, model responses, and operator notes are bounded; non-finite JSON and type-coercion tricks fail closed. Read adapters reject credentials, query/fragment smuggling, double encoding, traversal, origin escape, and path-prefix confusion. Runtime adapters remain loopback-only and reject secret-shaped prompts, oversized responses, invalid gates, and non-finite cost/output values.

Policy action kinds are normalized, unknown mutations are at least R2, destructive synonyms and production effects are R3, and booleans/permission levels require exact types. State-changing jobs require an author-capable assignee; assignee, approver, and reviewer separation is enforced. Lane, bot, node, degraded/offline/stale-contact, and global pauses propagate to already ready/running jobs; releasing a pause never auto-resumes work. Incident closure requires an identity different from the owner. Cost preflight/recording is transaction-safe under concurrent nonzero-cap tests, while the configured production boundary remains zero spend.

The loopback operator surface now requires a 32–512-character runtime token before POSTs can be enabled, accepts only bounded JSON objects, redacts client-facing errors, and refuses to serve state or report healthy if integrity fails. Non-loopback binding remains prohibited. The final local evidence is **103 rebuilt tests**, **332 combined tests**, JavaScript syntax validation, no diff-whitespace errors, and a clean no-download schema-v2 reconstruction drill. No commit, push, PR, merge, deployment, connector write, model execution, spend, remote command, legacy removal, or secret restoration occurred.

## Next implementation slice

1. Add alert delivery only after connector writes are explicitly approved; implement production transport/migration from the completed design only after independent review and Fry R3 approval.
2. Keep bot runtime and security enforcement disabled pending independent QUENCH review; add package-advisory, cryptographic signature/lock, and live repository/provenance verification only through a separately reviewed design.
3. Run authenticated live R0 provider probes only after independent transport-profile review; keep connector writes and remote execution disabled.
4. Independently review provider profiles, command grammars, cost policy, and preserved live advisory-read evidence.
5. Set nonzero model-cost warning and hard-stop thresholds only with explicit Fry approval; retain the current zero-spend boundary.
6. Complete rendered phone/desktop visual QA in a working browser runtime.
7. Repeat recovery from an approved release artifact with real secret restoration and live hardware heartbeat checks, then obtain QUENCH acceptance.
8. Only after those gates pass, request explicit Fry R3 approval for commit/push/merge/deploy/cutover and any legacy archive or deletion.

## Files

- `docs/REBUILD_SPEC.md`
- `orca/domain.py`
- `orca/policy.py`
- `orca/evidence.py`
- `orca/security.py`
- `orca/security_gate.py`
- `orca/state.py`
- `orca/runtime.py`
- `orca/tools.py`
- `orca/costs.py`
- `orca/fleet.py`
- `orca/governance.py`
- `orca/connectors.py`
- `orca/adapters.py`
- `orca/executor.py`
- `orca/schema.py`
- `docs/RECOVERY_RUNBOOK.md`
- `docs/LIVE_ADVISORY_READ_2026-09-23.md`
- `docs/RECOVERY_DRILL_2026-09-23.json`
- `docs/SECURITY_GATE_THREAT_MODEL.md`
- `docs/MULTI_HOST_ROLLOUT_PLAN.md`
- `scripts/recovery_drill.py`
- `orca/workflow.py`
- `orca/registry.py`
- `orca/models.py`
- `orca/control_plane.py`
- `orca/web.py`
- `orca/static/index.html`
- `orca/static/app.css`
- `orca/static/app.js`
- `pyproject.toml`
- `tests_v1/test_control_plane.py`
- `tests_v1/test_web.py`
- `tests_v1/test_security_gate.py`

## Safety and authority

This handoff reports local code and test evidence only. It does not authorize deployment, connector writes, spending, publication, merge, push, legacy deletion, secret access, or production change. No secret values are included.
