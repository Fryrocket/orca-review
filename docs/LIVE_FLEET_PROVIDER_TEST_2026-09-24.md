# ORCA live fleet and provider verification — 2026-09-24

Mode: authorized live verification, read-only. Provider writes, deployment, credential rotation, remote execution, model inference, spend, physical actions, and cutover performed: **0**.

## Fleet observations

| Node | Evidence | Result |
| --- | --- | --- |
| ANVIL | Local review host identified as `ANVIL.local`; ORCA commit and test worktree were clean before this evidence update. | Reachable; development/review surface only. |
| FORGE | Gitea `GET /api/v1/version` returned 1.27.3; public `fry/orca-review` repository metadata returned read-only permissions; Forge dashboard returned HTTP 200. ORCA was subsequently deployed loopback-only and its integrity health check passed. | Read surfaces and the constrained ORCA observation service are healthy. |
| KILN | SSH succeeded; host uptime and filesystem were readable; no failed system services; six containers were running and Open WebUI was healthy. `smith-inference`, `quench-inference`, and Caddy were active. OpenAI-compatible `/v1/models` returned `SMITH` on port 11434 and `QUENCH` on port 11435. | Core read-only runtime surfaces healthy. `forge-feed`, `forge-otlp`, and `llama-swap` systemd units reported inactive; Forge dashboard remained healthy through its configured front door. No inference request was made. |
| EMBER | SSH succeeded; no failed system services; `nut-server`, `nut-monitor`, `nut-driver@cyberpower`, `ember-oled`, `tailscaled`, `forge-vis-backup`, and `forge-vis-backup-nodes` were active. NUT listed UPS `cyberpower`; Tailscale reported `Running` for host `ember`. | Monitoring/backup surfaces healthy. No restore or power action was performed. |
| TEMPER | Fleet configuration states `via: none` and "Not on the tailnet yet. Setup needs Fry at the Pi." | **Blocked/unproven.** No network, MQTT, calibration, cellular, physical-output, or body-adjacent test attempted. |

The original observations proved reachability and named read surfaces only. A later deployment enrolled KILN with a host-scoped key, accepted signed heartbeats through the loopback SSH relay, verified both inference inventories, and proved nonce persistence across an agent restart. Unit/integration tests cover replay, stale timestamp, bad signature, and wrong-key rejection. Live disconnect transition, key rotation, failure recovery, and emergency-stop exercises remain unproven.

## Provider reads

| Provider | Read performed | Result |
| --- | --- | --- |
| Notion | Connected workspace identity, then `ORCA Rules & Permission Ladder` by stable page ID. | Passed. Authority and R0–R3 rules were readable. The page's implementation-status section is stale (103/332 tests, schema v2, pre-QUENCH). |
| Linear | Issue `FOR-5`, including relations. | Passed. The issue remains Backlog in project `Forge — Operationally Proven`; its text explicitly withholds privileged/deployment authority. |
| GitHub | Repository metadata for `Fryrocket/orca-review`. | Passed. Repository is readable; no branch, commit, push, PR, or mutation was performed. |
| Forge Gitea | Version and `fry/orca-review` repository metadata over the live API. | Passed. Repository API reported pull/read access without push permission. |
| Google Drive | Canonical `STATE.md` by stable file ID. | Passed. The connected copy is stale (2026-09-23T2010Z; schema v2; pre-commit/pre-QUENCH). No update was made. |
| Slack | List authenticated workspaces. | Passed. Workspace `Fry` was visible. No channel, message, draft, reaction, or profile mutation was made. |
| Cloudflare | No connected read tool or approved host-local read path was available in this session. | **Blocked/unproven.** No DNS, tunnel, access, or deployment action attempted. |

Live provider systems read: **6**. Read operations: **8** (Notion workspace + policy page, Linear issue, GitHub repository, Gitea version + repository, Drive state, and Slack workspace inventory). Live provider write count: **0**.

## Verdict

- **PASS:** bounded reachability and read-only service/provider observations for ANVIL, FORGE, KILN, EMBER, Notion, Linear, GitHub, Gitea, Drive, and Slack.
- **BLOCK:** production fleet/provider acceptance and cutover. TEMPER, live heartbeat failure/recovery and key-rotation exercises, real restored credentials, Cloudflare reads, stale provider-side policy copies, trusted external review, and formal deployment evidence acceptance remain unresolved.
- The readiness checker must remain `production_ready: false`. This evidence must not be represented as credential restoration, deployment proof, or authorization to enable writes.
