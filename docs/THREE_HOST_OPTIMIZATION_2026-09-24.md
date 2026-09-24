# ORCA Three-Host Optimization — 2026-09-24

## Goal

Use each verified machine for the work it is best equipped to perform while
preserving one authoritative writer, zero automatic execution, and the
existing approval and safety boundaries.

## Placement policy

| Workload | Preferred node | Hardware rationale |
| --- | --- | --- |
| Operator interaction | ANVIL | Local MacBook Pro worktop with Apple M4 and direct human presence |
| Source development | ANVIL | Interactive editing, local tests, and human review remain on the worktop |
| ORCA control plane | FORGE | Always-on server, high CPU/RAM capacity, durable storage, single authoritative writer |
| CPU-heavy batch work | FORGE | Ryzen 9 5900XT provides 16 cores / 32 threads |
| Durable model/data storage | FORGE | Dedicated 4 TB model and 2 TB data volumes plus large NVMe root volume |
| Small local inference | KILN | Dedicated GTX 1660 Ti with 6 GB VRAM and existing model services |
| Embeddings | KILN | Lightweight inference fits the dedicated secondary GPU node |
| Local QUENCH review | KILN | Existing QUENCH service and authenticated heartbeat make KILN the dedicated review brain |
| Large inference | Blocked pending FORGE | Requires RX9700 installation and runtime acceptance before the capability enters the registry |

## Implementation

- Fleet profiles now expose verified CPU, memory, GPU, storage, and capability
  facts for ANVIL, FORGE, and KILN.
- `orca.placement` contains a fixed, reviewable workload policy instead of an
  opaque scoring heuristic.
- Recommendations can require live authenticated health. An unproven or
  degraded node is not selected.
- Missing hardware capabilities fail closed. FORGE cannot be recommended for
  large inference until the accepted `large_inference` capability is added.
- The control-plane snapshot exposes both profiles and recommendations for the
  operator console and future clients.
- Placement is advisory only. `automatic_execution` and every node's
  `remote_execution_enabled` remain false.

## Verification

- Focused placement/control/fleet tests: 79 passed.
- Complete legacy plus rebuilt regression suite: 530 passed.
- Unknown workloads fail closed.
- Live-health recommendations reject unproven nodes.
- No model invocation, provider write, remote command dispatch, cloud spend,
  credential change, or production cutover is enabled by this optimization.
