# Distributed Model Sharding Backlog

Date recorded: 2026-09-24
Linear: `FOR-6`
Status: backlog; not implemented

## Requirement

ORCA must eventually be able to split one model across multiple authenticated
machines when the model cannot fit or run efficiently on any one accepted node.
The present implementation routes each complete workload to one capable,
healthy node; it does not pool model memory or orchestrate distributed shards.

## Fleet constraint

- ANVIL: Apple Metal with 16 GB unified memory.
- FORGE: 16-core / 32-thread Ryzen CPU with 62 GiB usable RAM; this is the
  present home for SMITH, embeddings, canonical model files, and CPU inference.
- KILN/BILLOWS: NVIDIA CUDA with 6 GiB VRAM and about 31 GiB usable system RAM;
  live QUENCH already reserves roughly 4.8 GiB of that VRAM.
- EMBER: 8 GB ARM sentinel and UPS observer; it is not a model-shard target.
- FORGE/CRUCIBLE: AMD Radeon AI PRO R9700 with 32 GiB VRAM and ROCm 7.2.1;
  hardware compute passed, while model-service and independent acceptance remain open.

These are separate, heterogeneous memory pools. Installed capacity must never be
reported as allocatable pooled model memory unless the selected runtime proves
the exact cross-node and cross-backend configuration. ORCA may coordinate these
machines as one cognitive system, but coordination does not turn their RAM or
VRAM into one physical memory pool.

## Work

1. Select and benchmark a compatible distributed inference runtime.
2. Define a versioned shard manifest for model digest, layers/tensors, device
   identity, RAM/VRAM budgets, precision, context, transport, and fallback.
3. Add live allocatable-memory telemetry and reservation.
4. Add a health-gated planner and authenticated workers with bounded transport,
   artifact verification, cancellation, and correlated evidence.
5. Test incompatibility, oversubscription, node loss, partial load, stale health,
   restart, rollback, output equivalence, latency, throughput, network load,
   thermals, and power.

## Acceptance

- A representative model too large for any single accepted node completes
  inference across at least two authenticated nodes.
- ORCA records the exact shard-to-device map and peak RAM/VRAM usage.
- Invalid or unhealthy combinations fail before execution.
- Worker loss cancels or safely recovers without presenting partial output as complete.
- QUENCH independently verifies repeatability, evidence, performance, and recovery.
- Fry explicitly approves runtime activation and any production exposure.

Provider writes, paid cloud fallback, autonomous remote execution, deployment,
and cutover remain separate gates and are not authorized by this backlog item.
