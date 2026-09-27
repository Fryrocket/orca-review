# ORCA four-host acceptance — 2026-09-27

## Activated fabric

- ANVIL: `llama3.2:3b` reflex model on local Ollama; exact-response test passed.
- FORGE/CRUCIBLE: DeepSeek-R1-Distill-Qwen-32B-Q4_K_M on pinned ROCm llama.cpp;
  reboot recovery, inference, sustained load, responsiveness, and rollback passed.
- FORGE/SMITH: Qwen3-Coder-30B-A3B-Instruct-Q4_K_M on CPU; inference passed.
- KILN/QUENCH: Ministral-3-8B-Instruct-2512-IQ4_XS on BILLOWS; its
  authenticated LAN SSH tunnel is projected onto FORGE loopback; inference and
  independent CRUCIBLE review passed.
- EMBER: deterministic heartbeat, UPS, backup observation, and bounded wake
  services active; current UPS status was online at 100% charge.

## CRUCIBLE evidence

- Runtime: llama.cpp tag `b11193`, commit
  `4e7481175cbd4759df8bee2f1c1a0073effbebd7`, SHA-256
  `f62286c29871c82489b3e2b84d61801fa69da20cccce5ee8cf917b9c74eb225c`.
- Model SHA-256:
  `bed9b0f551f5b95bf9da5888a48f0f87c37ad6b72519c4cbd775f54ac0b9fc62`.
- Endpoint: `127.0.0.1:11436`, context 16,384, one parallel request, no model tools.
- Post-reboot exact inference passed at about 26.4 tokens/second.
- Three sequential 512-token generations completed at 26.3–26.4 tokens/second;
  ORCA remained HTTP 200 at about 0.15 seconds during and after the run.
- Stop/start rollback exercise withdrew the endpoint and restored healthy service.
- QUENCH review `chatcmpl-WAeHh3hPw3KrNwztNp42y8mbatsoRbrt` returned accepted.
- Fry authorized activation in the controlling conversation on 2026-09-27.

## Safety boundary

The activated gateway permits authenticated Fry-initiated inference only. Model
services are loopback-only, service/model/bot combinations are allowlisted,
prompts and responses are bounded and redacted, output contracts are enforced,
tool calls are empty, remote execution remains disabled, provider writes remain
separately governed, and Fry remains the approval authority.
