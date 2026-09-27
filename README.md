# ORCA control plane

ORCA is a policy-first, evidence-backed control plane for the Forge fleet. The
current observation deployment uses one authoritative writer on FORGE, with
signed health agents on ANVIL, FORGE, and KILN. Remote execution, connector
writes, ORCA-triggered model inference, cloud spend, and production cutover
remain disabled.

## Current topology

| Host | Role | Verified hardware/runtime |
| --- | --- | --- |
| ANVIL (`192.168.4.20`) | Operator worktop, development, and review | Apple M4, 16 GB unified memory; signed health and private loopback tunnel |
| FORGE (`192.168.7.30`, wired LAN `.29`, Wi-Fi `.30`) | Authoritative control plane, shared context, deep CPU inference, builds, ingestion, and durable storage | Ryzen 9 5900XT, 64 GB RAM, CRUCIBLE 32 GB plus Lexa display GPU, model/data volumes; loopback-only ORCA service and signed health |
| KILN (`192.168.4.28`, Tailscale `100.97.193.39`) | Independent QUENCH GPU review and relay | BILLOWS — NVIDIA GeForce GTX 1660 Ti 6 GB; QUENCH inventory and signed health |
| EMBER (`192.168.4.26`, Tailscale `100.87.165.66`) | Always-on sentinel, UPS/watchdog, and backup observer | Raspberry Pi 4, 8 GB RAM, USB SSD, Gigabit Ethernet, CyberPower UPS |

**CRUCIBLE** is FORGE's installed AMD Radeon AI PRO R9700: 32 GB GDDR6, 64 CUs,
`gfx1201`, amdgpu, and ROCm 7.2.1. Hardware detection, driver/runtime checks,
and controlled compute/load tests passed on 2026-09-26. ORCA GPU inference
remains disabled until a model-serving runtime, post-reboot model test, and
independent QUENCH acceptance are recorded.

## AI stack

- ANVIL is the fast private reflex using its installed `llama3.2:3b` model.
- FORGE is the deep SMITH author target for the existing 30.5B Q4 coder model,
  plus embeddings, retrieval, builds, ingestion, shared context, and model/data storage.
- KILN reserves its nearly full 6 GiB CUDA device for independent QUENCH review.
- EMBER runs deterministic monitoring only; it does not host a generative model.

The ordered hardware-aware ladders are exposed in the control-plane snapshot.
They remain advisory: model invocation and automatic execution are still off.
See [`docs/FOUR_HOST_AI_STACK_2026-09-25.md`](docs/FOUR_HOST_AI_STACK_2026-09-25.md).

## Verification baseline

- Deployed source: `52d64889145fb5eb7b0338b8fed8c633ccd307a4`.
- Last completed full regression: 294 rebuilt tests + 243 legacy tests = **537 passed**.
- Schema v4 state/evidence integrity and signed-heartbeat replay/restart behavior pass.
- Desktop and 390×844 phone rendering pass.
- The current repository may contain later documentation-only or registry-name
  changes; verify `git status`, `git log`, and the test output before release.

## Safety boundary

- Fry owns push, merge, deploy/cutover, provider writes, spending, secrets,
  destructive actions, and physical work.
- ORCA routes and enforces policy; SMITH implements; QUENCH independently
  reviews; the security gate is advisory only.
- No identity may author, review/approve, and deploy the same change.
- Secrets never belong in git, Drive, Notion, Linear, Slack, logs, or evidence.
- The service binds to loopback and fails closed on integrity, identity,
  idempotency, revision, health, or permission failures.

## Run locally

```sh
python -m pytest tests tests_v1
python -m orca --host 127.0.0.1 --port 8787 --database orca-events.db
```

Identity-bound mutations require an owner-only JSON credential file selected
with `ORCA_IDENTITY_TOKEN_FILE`. The compatibility `ORCA_OPERATOR_TOKEN` mode is
loopback-only, Fry-bound, and cannot be combined with identity mode.

## Documentation

- Current state: [`docs/STATE_v12_upload.md`](docs/STATE_v12_upload.md)
- Active-document index: [`docs/README.md`](docs/README.md)
- Hardware: [`docs/HARDWARE_INVENTORY_2026-09-24.md`](docs/HARDWARE_INVENTORY_2026-09-24.md) and the verified 2026-09-25 four-host audit summarized in the AI-stack plan
- Four-host AI stack: [`docs/FOUR_HOST_AI_STACK_2026-09-25.md`](docs/FOUR_HOST_AI_STACK_2026-09-25.md)
- Three-host deployment: [`docs/THREE_HOST_OPTIMIZATION_DEPLOYMENT_2026-09-24.md`](docs/THREE_HOST_OPTIMIZATION_DEPLOYMENT_2026-09-24.md)
- Recovery: [`docs/RECOVERY_RUNBOOK.md`](docs/RECOVERY_RUNBOOK.md)
- Historical evidence: [`docs/archive/`](docs/archive/)

The retained `mao/` package and August records are historical rollback and
regression surfaces, not the architecture or current status of the rebuilt
control plane.
