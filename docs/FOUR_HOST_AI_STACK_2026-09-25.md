# ORCA Four-Host AI Stack and Cognitive Ladder - 2026-09-25

## Decision

Treat ANVIL, FORGE, KILN, and EMBER as one ORCA mind with specialized hardware
surfaces. FORGE is the authoritative writer, shared context/memory owner, model
store, data store, batch host, build host, and deep CPU-inference host. The
other machines extend that mind; they do not create independent authority or a
fictional pooled RAM/VRAM device.

This is the desired reviewed deployment state. The code and unit templates are
present, but model invocation, remote execution, deployment, connector writes,
and cloud spend remain disabled until their existing gates are satisfied.

## Live evidence that changes the earlier three-host plan

The 2026-09-25 hardware audit and read-only runtime inspection established:

- FORGE has 16 cores / 32 threads, about 62 GiB usable RAM with 61 GiB
  available, 8 GiB unused swap, 2.5 GbE, and an empty 3.7 TiB `/srv/models`
  volume. Its current 4 GiB Lexa Pro GPU is not accepted as a general inference
  accelerator.
- KILN has 6 cores / 12 threads, about 31 GiB usable RAM, 13 GiB available,
  1.7 GiB swap already in use, and a 6 GiB GTX 1660 Ti. QUENCH occupies about
  4.8 GiB VRAM, leaving about 797 MiB free.
- KILN's SMITH service currently keeps the 18.55 GB
  `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M` model CPU-resident with a 16K context
  and consumes about 16.7 GB resident memory. That work fits FORGE much better.
- KILN's QUENCH service runs
  `Ministral-3-8B-Instruct-2512-IQ4_XS` on CUDA with a 4K context. It is the
  correct independent review surface and should retain GPU exclusivity.
- ANVIL has an installed `llama3.2:3b` Ollama model on Apple M4 / 16 GB unified
  memory. It is the fast interactive reflex, not the durable brain.
- EMBER is an 8 GB Raspberry Pi 4 with a USB SSD, Gigabit Ethernet, and the
  directly attached CyberPower UPS. It should run deterministic monitoring,
  UPS, watchdog, backup-observer, and wake functions, not a generative model.

## Target stack

| Service | Host | Hardware path | Model/runtime | Resource envelope | Purpose |
| --- | --- | --- | --- | --- | --- |
| ORCA policy and memory | FORGE | 32-thread CPU, RAM, NVMe, 2.5 GbE | Deterministic Python control plane | 4 GiB working budget | One authoritative writer, evidence, policy, shared context and routing |
| ANVIL reflex | ANVIL | Apple M4 Metal and unified memory | Ollama `llama3.2:3b` | 4 GiB, one request | Fast private triage, summarization and prompt preparation |
| SMITH deep author | FORGE | Ryzen 9 5900XT CPU / AVX2 | llama.cpp `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M` | 28 GiB target, 36 GiB hard service cap, 16K context, one slot, 24 inference threads | Coding, synthesis, planning, documentation and general reasoning |
| Retrieval pipeline | FORGE | CPU, model/data NVMe | Accepted embedding/reranking model to be selected | 6 GiB, four bounded workers | Ingestion, embeddings, retrieval and reranking without competing for KILN VRAM |
| QUENCH independent reviewer | KILN | GTX 1660 Ti CUDA | llama.cpp `Ministral-3-8B-Instruct-2512-IQ4_XS` | 5 GiB VRAM target, 4K context, one slot | Independent review, verification and adversarial challenge |
| EMBER sentinel | EMBER | Cortex-A72, 8 GB RAM, UPS USB HID | Deterministic rules only | 2 GiB working budget | Always-on health, UPS, watchdog, backup observation and wake signals |
| CRUCIBLE acceleration | FORGE | AMD Radeon AI PRO R9700, 32 GB GDDR6, 64 CUs, `gfx1201`, ROCm 7.2.1 | Model/runtime pending | 32 GB physical VRAM; workload budget pending | Hardware/runtime/load accepted 2026-09-26; inference service remains disabled |
| DeepSeek reasoner | FORGE | CRUCIBLE ROCm/HIP | `DeepSeek-R1-Distill-Qwen-32B-Q4_K_M` through pinned llama.cpp | 24 GiB VRAM target, 16K context, one slot | Architecture, hard debugging, mathematics, planning, and second-opinion reasoning; no author or reviewer authority |

## Cognitive ladder

The ladder selects the cheapest sufficient local surface, then escalates depth
or independence. A later step does not erase the earlier step's evidence.

| Work | Ordered ladder |
| --- | --- |
| Policy and routing | FORGE deterministic ORCA |
| Interactive operator help | ANVIL reflex -> FORGE SMITH -> Fry |
| Coding/implementation | FORGE SMITH author -> KILN QUENCH review -> Fry gate |
| Documentation | ANVIL reflex for preparation -> FORGE SMITH synthesis -> KILN QUENCH review -> Fry |
| Operations plans | FORGE SMITH -> KILN QUENCH -> Fry |
| Technical/security review | KILN QUENCH -> Fry; FORGE SMITH cannot approve itself |
| Embeddings/retrieval | FORGE retrieval pipeline |
| Monitoring | EMBER deterministic sentinel -> FORGE policy correlation -> Fry |
| Large local inference now | FORGE CPU-resident SMITH -> Fry |
| Large GPU inference later | FORGE CRUCIBLE -> Fry; hardware accepted, blocked until model service and independent acceptance |

Cloud fallback remains absent from the active ladder. The existing Fry R3 and
positive-budget requirements remain the only route by which a paid provider
could later be considered.

## Placement changes

- Move SMITH's CPU-resident 30.5B Q4 service from KILN to FORGE.
- Reserve KILN's GPU and review identity for QUENCH. Do not colocate the SMITH
  author and QUENCH reviewer on one host when independent review matters.
- Move embeddings and retrieval from KILN to FORGE. KILN has only about
  797 MiB free VRAM during QUENCH operation and should not overcommit it.
- Use FORGE for builds, CI, document ingestion, model storage, shared context,
  CPU batch work, and large CPU inference in addition to the control plane.
- Keep ANVIL interactive and optional. The system must continue operating when
  the laptop sleeps or leaves the network.
- Enroll EMBER as a signed health node only after its authenticated transport
  and heartbeat key are accepted. EMBER must never become the authoritative
  database writer.

## Network and runtime boundary

- FORGE SMITH binds only to `127.0.0.1:11434`.
- KILN QUENCH remains on its authenticated worker network endpoint. FORGE sees
  it only as `127.0.0.1:11435` through an authenticated, host-key-checked SSH
  tunnel.
- `SandboxedOpenAIAdapter` accepts only loopback
  `/v1/chat/completions`, explicit model allowlists, bounded prompts/outputs,
  tool-free requests, and the versioned ORCA JSON output contract.
- Direct LAN/tailnet model URLs, tool calls, malformed JSON, secret-shaped
  prompts, oversized output, unhealthy nodes, and unknown models fail closed.

## Staged migration and rollback

1. Independently review this source, model digest, llama.cpp build, service
   units, thread/memory limits, tunnel host key, and benchmark plan.
2. Copy the exact SMITH GGUF to
   `/srv/models/orca/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf` and record its
   SHA-256. Do not delete KILN's copy.
3. Install an accepted llama.cpp build at `/opt/llama.cpp/bin/llama-server` on
   FORGE; start `orca-smith-inference.service` loopback-only.
4. Verify model identity, JSON-contract output, context behavior, cancellation,
   CPU saturation, latency, thermals, memory high-water, ORCA responsiveness,
   and restart recovery.
5. Establish the host-key-checked QUENCH loopback tunnel and verify that author
   and reviewer remain distinct services on distinct hosts.
6. Only after QUENCH and Fry acceptance, retire KILN's SMITH service. Keep its
   unit/model intact for the rollback window.

Rollback is immediate: stop/disable FORGE SMITH, restore KILN SMITH, leave
QUENCH unchanged, and record the evidence-correlated reason. No database or
connector state is migrated as part of the model move.

## Remaining acceptance work

- After CRUCIBLE acceptance, evaluate Cline as the initial free, open-source,
  Cursor-style bot-development interface connected to SMITH through a local
  OpenAI-compatible endpoint. Keep file changes, command execution, deployment,
  and promotion subject to ORCA policy, QUENCH review, and Fry approval. Compare
  Continue and Roo Code if Cline's local tool-calling path is unreliable.
- With CRUCIBLE hardware installed and compute-accepted, review and complete the
  ORCA monitoring UI: expose the Fleet dashboard from FORGE, KILN, and ANVIL;
  connect the iPhone app to the same Fleet view; register the iPhone as an
  appropriate monitored client; and add CPU, memory, disk, temperature, load,
  uptime, and critical-service health without weakening authentication.
- Select and test the exact embedding and reranking models on FORGE.
- Enroll EMBER and prove signed nonce persistence, stale/offline behavior, UPS
  event handling, and recovery without connector writes.
- Benchmark FORGE SMITH against the current KILN baseline before calling the
  move faster; the placement is justified by capacity and isolation even if a
  particular prompt remains latency-bound.
- CRUCIBLE identity, VRAM, driver/runtime, thermals, power, and sustained compute
  passed on 2026-09-26. A post-reboot model test, QUENCH review, and controlled
  ORCA activation remain open.
- Distributed model sharding remains separate. One coordinated mind means one
  policy/evidence/context fabric, not interchangeable heterogeneous memory.
