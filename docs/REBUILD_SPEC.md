# ORCA v1 rebuild specification

Status: implementation started 2026-09-23. The legacy `mao` package is retained as a rollback and test-reference surface until explicit R3 cutover approval.

## Product definition

ORCA is the policy-first control plane for Fry's local and connected agent stack. It routes work, classifies permission risk, preserves project-lane boundaries, requests approvals, records evidence, enforces separation of duties, tracks incidents and cost, and gives the operator a truthful visual interface.

ORCA is not the coding model, reviewer, security gate, source of truth for every connected system, or final approval authority.

Mutable state and its evidence commit in one immediate SQLite transaction. Schema
v4 stores a digest for each serialized state revision, binds it to the exact
verified evidence-chain head, digests every mutation receipt, and anchors the
complete receipt set so omitted rows or tables fail closed. Startup, mutation,
snapshots, and health checks reject state tampering, missing evidence references,
chain corruption, stale revisions, or databases from a newer schema.

## Fleet scope

ORCA governs work across the hardware fleet, not only the machine hosting the console. The initial registry contains ANVIL (operator workstation), FORGE (primary infrastructure and Gitea), KILN (inference and supporting services), EMBER (backup, monitoring and UPS/NUT), and TEMPER (BGM edge/AI). Future nodes must be registered before jobs may target them.

Every node-targeted job carries a stable node ID and project lane. Cross-lane targeting fails closed. Node health starts as `unproven`; inventory presence is not proof of reachability or service health. Per-node pause blocks new work for that node and emits hash-chained evidence. Enrollment is Fry-only, persists only a key fingerprint, and signed heartbeats enforce freshness and monotonic nonces. Stale contact degrades/offlines and pauses the node. Remote execution remains disabled until transport allowlists, scoped executors, rollback, emergency stop, and an independent review are implemented and approved.

## Stable identities

| Identity | Duty |
|---|---|
| ORCA | Policy, routing, approvals, lane isolation, escalation |
| SMITH | Coding and implementation |
| QUENCH | Independent technical review and verification |
| Security gate | Deterministic advisory security findings; no author/review/deploy authority |
| Fry | R2/R3 decisions, exceptions, merge, deploy, spend, publication, secrets, physical work |

No identity may author, review/approve, and deploy the same change.

The core bot definitions are deliberately inert until runtime gates are complete. ORCA routes `orchestration`; SMITH receives `coding`, `documentation`, and `operations_plan`; QUENCH receives `review`, `security_review`, and `verification`; the security gate accepts only advisory scan task types through its dedicated deterministic path. Its v2 scanner covers secret/configuration hazards plus supplied dependency, CI provenance, container, branch-protection, and required-status-check signals; it does not claim live provider or cryptographic verification. Queuing records submission, route, model route, and stop condition. Model runtime and tools remain disabled. Legacy AMPERE and RELAY definitions are migration candidates, not active identities; activating or replacing them requires an explicit roster decision.

## Permission model

- R0: read-only observation and analysis; proceed and retain evidence.
- R1: low-risk reversible change; rollback and verification are mandatory.
- R2: material operational change; plan, validation and explicit approval where policy requires.
- R3: irreversible or high-impact; stop for Fry. Includes deletion, secrets, spend, publication, push, merge, deployment, remote execution, cutover, production impact, physical actuation and body impact.

## Connector authority

- Notion: durable knowledge, architecture, policies, decisions and runbooks.
- Linear: work, owners, dependencies, milestones and acceptance criteria.
- Gitea/GitHub: code/configuration history, branches, review, checks and releases.
- Slack: urgent alerts, active coordination and approval requests.
- Drive: large evidence, artifacts, reports, recovery material and cc-bridge handoffs.
- Cloudflare: edge inventory/control; live writes require an approved task, validation and rollback.

Standard flow: Notion decision -> Linear work -> Git implementation/review -> Slack approval/alert -> Drive evidence -> approved edge action when applicable -> outcome back to Notion and Linear.

Every declared connector operation has an R0–R3 rule. The implemented gateway prepares classified R0 read/list/search/get requests only; unknown operations and every mutation fail closed. Provider adapters constrain exact origin and canonical path boundaries, reject credentials/query/fragment/double encoding, and redact returned data. No live provider call is made by the gateway itself.

## Required operator views

1. Overview: system truth, active lanes, degraded/unproven states and last-verified timestamps.
2. Fleet: node identity, duty, lane, address label, health, last verification, permission floor, pause state and remote-execution state.
3. Work: job state, actor, lane, permission badge, model route, connector and stop condition.
4. Approvals: exact proposed action, classification rationale, evidence, rollback and approve/deny controls.
5. Evidence and retention: correlation timeline, hash-chain health, retention mode and audit outcome.
6. Security: advisory findings, severity, remediation, reviews and record-only exceptions.
7. Agents: stable identity, current assignment, declared tools, runtime, incident count and per-agent pause.
8. Connectors: authority, classified action levels and disabled write state; never display secrets.
9. Incidents: S0-S3 severity, containment, owner and closure evidence.
10. Costs: usage by job/lane/model/connector, warning status, hard stop and degraded mode.

The interface must be responsive, distinguish healthy/degraded/offline/unproven, display R-level badges, put approval-required banners ahead of execution, and remain useful without any model or connector online.

## Acceptance gates before legacy removal

- Clean install and test from a fresh checkout.
- Policy tests cover every R0-R3 trigger and fail closed.
- Append-only evidence and schema-v4 state/evidence/receipt binding verify after restart and detect tampering or omission.
- Author/reviewer/deployer separation is enforced end to end.
- Every connector action is classified before execution.
- Per-job pause and global emergency stop are tested.
- Per-node pause, authenticated health reporting and fail-closed loss-of-contact behavior are tested on ANVIL, FORGE, KILN, EMBER and TEMPER.
- Dashboard works at phone and desktop widths without exposing secrets.
- At least one advisory-only live workflow completes across Notion, Linear, Git and Drive.
- Restore drill proves the control plane can be reconstructed from documented state.
- Fry explicitly approves R3 cutover and legacy deletion/archive.

## Source precedence used

1. Live read-only verification.
2. Newest verified cc-bridge packet and `STATE.md`.
3. Current repository state.
4. Notion operating standards and Linear work.
5. Historical August Orca documents.
