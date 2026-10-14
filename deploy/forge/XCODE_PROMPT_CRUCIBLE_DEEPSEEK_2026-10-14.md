# Xcode Prompt — Activate DeepSeek on CRUCIBLE + Rewire Coding Ladder
# Fryrocket / ORCA — 2026-10-14
#
# Paste this into the Xcode bot session. It points at the full instruction
# file already committed to the orca-review repo.

---

Read the file deploy/forge/CODEX_INSTRUCTIONS_CRUCIBLE_DEEPSEEK_2026-10-14.md
in the orca-review repo (https://github.com/Fryrocket/orca-review) and
execute it exactly as written.

Summary of what it does:

1. Verify the DeepSeek-R1-Distill-Qwen-32B-Q4_K_M.gguf model file exists
   on FORGE at /srv/models/orca/ and record its SHA-256. If missing,
   STOP and report — do not download.

2. Create /etc/systemd/system/orca-deepseek-inference.service — a
   llama-server unit running DeepSeek on the CRUCIBLE GPU (AMD Radeon
   AI PRO R9700, ROCm 7.2.1) at 127.0.0.1:11437, with -ngl 99, -c 16384,
   --reasoning on, HSA_OVERRIDE_GFX_VERSION=12.0.1, MemoryMax 32G. The
   existing Qwen3.5-35B service on port 11436 is NOT touched.

3. Enable and start the service. Verify with systemctl is-active,
   curl the /health endpoint, list /v1/models, and run a short bounded
   smoke test. Watch rocm-smi — VRAM should land around 20-24 GiB.
   If it exceeds 28 GiB, stop and report before retrying.

4. Rewire orca/ai_stack.py: insert forge_deepseek as the FIRST step of
   the coding ladder, before kiln_codex. Add the forge_deepseek
   AIServiceProfile (16_384 context, 24 GiB VRAM, may_author=True,
   deployment_state live_pending_acceptance). Fix the VRAM validator
   conflict by setting forge_qwen's vram_budget_gib to 0 with a comment
   that it shares CRUCIBLE with DeepSeek exclusively — one at a time.
   Run validate_ai_stack(); it must pass.

5. Update models.py DEFAULT_ROUTES: coding -> forge_deepseek primary,
   kiln_codex fallback. large_gpu_inference -> forge_deepseek primary.

6. Add a 2026-10-14 update section to
   docs/FOUR_HOST_AI_STACK_2026-09-25.md documenting that DeepSeek is
   now the first rung and cloud is fallback only.

7. Commit to main: "Activate DeepSeek on CRUCIBLE; coding ladder
   prefers local (2026-10-14)". Write a CC_ note to the cc-bridge Drive
   folder: CC_note_crucible-deepseek-activated_2026-10-14.md covering
   service status, health, smoke test, VRAM high-water, thermals,
   ladder diff, and validator result.

Safety: local service management and repo edits only. No remote
execution, no secrets, no connector writes, no cloud spend.

Report back when done.
