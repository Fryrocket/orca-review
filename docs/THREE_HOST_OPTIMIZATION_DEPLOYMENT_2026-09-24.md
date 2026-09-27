# ORCA Three-Host Optimization Deployment — 2026-09-24

## Outcome

The hardware-aware placement release is live on FORGE and KILN, and signed
health agents are live for ANVIL, FORGE, and KILN. All three report healthy to
the authoritative FORGE control plane.

## Release

- Source commit: `52d64889145fb5eb7b0338b8fed8c633ccd307a4`
- Archive SHA-256:
  `db4d69e3d928ea83c411777577b4c8279385266ee011fda82c6224c6185c5afb`
- Full test suite: 537 passed.
- KILN's installed Python 3.10 successfully loaded the release before activation.

## Live placement

| Workload | Selected node |
| --- | --- |
| Operator interaction | ANVIL |
| Development | ANVIL |
| Control plane | FORGE |
| CPU batch | FORGE |
| Durable storage | FORGE |
| Small inference | KILN |
| Embeddings | KILN |
| Local review | KILN |
| Large inference | Blocked until CRUCIBLE (AMD Radeon RX 9700) installation and runtime acceptance |

## Signed health

- ANVIL detail: `ANVIL operator tunnel healthy`.
- FORGE detail: `FORGE control plane healthy`.
- KILN detail: two required inference health endpoints available.
- All three enrollments are authenticated.
- Controlled agent restarts advanced ANVIL's nonce from 2 to 3 and FORGE's
  nonce from 3 to 4. KILN nonce persistence had already been verified and
  remained healthy during this deployment.
- Heartbeat keys and nonce state are owner-only. Raw keys are not present in
  repository state, evidence, logs, or this document.

## Services

- ANVIL: `com.fryrocket.orca-anvil-node` LaunchAgent.
- FORGE: `orca.service` and `orca-forge-node.service` systemd units.
- KILN: `orca-kiln-node.service`, `orca-forge-tunnel.service`,
  `smith-inference.service`, and `quench-inference.service`.
- FORGE health and evidence-chain integrity passed after activation.

## Safety state

- Automatic execution: false.
- Remote execution: false on every node.
- Provider writes: disabled.
- Model invocation by ORCA: disabled.
- Cloud spend: zero authorization.
- Large inference: blocked pending CRUCIBLE installation and runtime acceptance.
- No push, PR, merge, credential restoration, or production cutover occurred.
