# ORCA operating workflow

## Roles

- **Fry:** owner; decides R2/R3, push, merge, deployment, cutover, provider
  writes, secrets, spend, deletion, and physical work.
- **ORCA:** policy, routing, lane isolation, approvals, and evidence correlation.
- **SMITH:** implementation and authored change evidence.
- **QUENCH:** independent technical review and verification.
- **Security gate:** bounded advisory findings only; no approval or deployment authority.

No identity may author, review/approve, and deploy the same change.

## Change path

1. Read `docs/STATE_v12_upload.md` and the active-document index.
2. Classify the action R0–R3 and declare the stop condition.
3. Work on an agent branch; preserve correlation and rollback evidence.
4. Run the focused checks, then the complete rebuilt + legacy test corpus when
   the change can affect runtime behavior.
5. QUENCH independently reviews release-impacting work.
6. Fry explicitly approves every push, merge, deployment, provider write, and cutover.

## Connector roles

- Notion: durable policy and architecture.
- Linear: actionable work and project status.
- Git/GitHub/Gitea: implementation and immutable revision evidence.
- Slack: urgent coordination and alerts, not durable authority.
- Google Drive `cc-bridge`: handoffs, current state, and recovery artifacts.
- Cloudflare: edge state only after explicit authorization.

Keep one current summary per surface. Move superseded records into dated
archives; do not delete evidence. Never copy secret values into any connector.

## Current deployment boundary

FORGE is the authoritative loopback-only observation host. ANVIL, FORGE, and
KILN publish signed health. Remote execution, provider writes, ORCA model calls,
automatic failover, and production cutover remain disabled. CRUCIBLE—the
installed AMD Radeon AI PRO R9700 for FORGE—has passed hardware, amdgpu,
ROCm 7.2.1, and controlled load acceptance. GPU model service activation still
waits for model/runtime selection, a post-reboot repeat, QUENCH review, and Fry's
explicit cutover decision.

The target four-host cognitive fabric keeps one authority while specializing
execution: ANVIL provides fast private interaction, FORGE owns shared context
and deep SMITH CPU inference, KILN provides independent QUENCH GPU review, and
EMBER provides deterministic monitoring/UPS/watchdog service. Large CPU
inference no longer waits for CRUCIBLE; only the accelerated GPU tier does.
See `docs/FOUR_HOST_AI_STACK_2026-09-25.md`. These placements do not themselves
authorize model invocation, service installation, enrollment, or deployment.
