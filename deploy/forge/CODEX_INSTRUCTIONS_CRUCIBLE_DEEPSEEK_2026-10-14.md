# Codex Instructions — Activate DeepSeek on CRUCIBLE + Rewire Coding Ladder
# Fryrocket / ORCA — 2026-10-14
#
# Context: Fry wants to save cloud data usage. DeepSeek is already installed
# on FORGE's CRUCIBLE (AMD Radeon AI PRO R9700, 32 GB GDDR6, ROCm 7.2.1).
# Goal: make forge_deepseek the FIRST rung of the coding ladder so ORCA
# prefers local inference over cloud (kiln_codex / gemini_free) whenever
# CRUCIBLE is healthy. Grok (cloud) should always know to use CRUCIBLE
# to its fullest power before escalating to paid providers.
#
# SAFETY: observation and local service management only. No remote
# execution, no secret changes, no connector writes, no cloud spend.
# Do not delete or overwrite the existing Qwen3.5-35B service — it stays
# as the conversational brain on port 11436. DeepSeek gets its own port.

## 1. Verify DeepSeek model artifact on FORGE
   ls -lh /srv/models/orca/ | grep -i deepseek
   # Expected: DeepSeek-R1-Distill-Qwen-32B-Q4_K_M.gguf (~20 GB)
   # Record its SHA-256:
   sha256sum /srv/models/orca/DeepSeek-R1-Distill-Qwen-32B-Q4_K_M.gguf
   # If the file is missing, STOP and report. Do not download during this
   # pass — model downloads are a separate gated step.

## 2. Create the DeepSeek CRUCIBLE service unit
   # File: /etc/systemd/system/orca-deepseek-inference.service
   # Content (adapt paths if your layout differs):
   #
   # [Unit]
   # Description=ORCA DeepSeek reasoner on FORGE CRUCIBLE (ROCm/HIP)
   # After=network-online.target
   # Wants=network-online.target
   # RequiresMountsFor=/srv/models/orca
   # ConditionPathExists=/opt/llama.cpp/llama-server
   # ConditionPathExists=/srv/models/orca/DeepSeek-R1-Distill-Qwen-32B-Q4_K_M.gguf
   #
   # [Service]
   # Type=simple
   # User=fryrocket
   # Group=fryrocket
   # UMask=0077
   # WorkingDirectory=/srv/models/orca
   # Environment=HSA_OVERRIDE_GFX_VERSION=12.0.1
   # Environment=LD_LIBRARY_PATH=/opt/llama.cpp/lib
   # ExecStart=/opt/llama.cpp/llama-server \
   #     --model /srv/models/orca/DeepSeek-R1-Distill-Qwen-32B-Q4_K_M.gguf \
   #     --host 127.0.0.1 --port 11437 -ngl 99 -c 16384 -np 1 \
   #     --alias ORCA-DEEPSEEK --reasoning on
   # Restart=on-failure
   # RestartSec=5
   # TimeoutStartSec=600
   # MemoryHigh=28G
   # MemoryMax=32G
   # TasksMax=512
   # NoNewPrivileges=true
   # PrivateTmp=true
   # ProtectSystem=strict
   # ProtectHome=true
   # ReadOnlyPaths=/srv/models/orca /opt/llama.cpp
   # RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
   # RestrictSUIDSGID=true
   # LockPersonality=true
   # CapabilityBoundingSet=
   #
   # [Install]
   # WantedBy=multi-user.target
   #
   # Notes on flags:
   # - Port 11437: distinct from SMITH (11434, CPU) and QWEN (11436, CRUCIBLE).
   # - -ngl 99: offload all layers to the R9700 (32 GB VRAM; 24 GiB target).
   # - --reasoning on: DeepSeek-R1 is a reasoning model; keep it.
   # - HSA_OVERRIDE_GFX_VERSION=12.0.1: the R9700 reports as gfx1201;
   #   ROCm 7.2.1 needs this override (same as the accepted CRUCIBLE runtime).
   # - MemoryMax 32G: hard cap at physical VRAM; do not overcommit.
   # - --no-mmproj omitted: DeepSeek has no multimodal projector.
   #
   sudo cp orca-deepseek-inference.service /etc/systemd/system/
   sudo systemctl daemon-reload

## 3. Start and verify
   sudo systemctl enable --now orca-deepseek-inference.service
   sleep 30
   systemctl is-active orca-deepseek-inference.service
   # Should print: active
   curl -s http://127.0.0.1:11437/health
   # Should return JSON with status ok.
   curl -s http://127.0.0.1:11437/v1/models | python3 -m json.tool
   # Should list ORCA-DEEPSEEK.
   # Smoke test (short, bounded):
   curl -s http://127.0.0.1:11437/v1/chat/completions \
     -H 'Content-Type: application/json' \
     -d '{"model":"ORCA-DEEPSEEK","messages":[{"role":"user","content":"Say hi in five words."}],"max_tokens":32}'
   # Watch thermals and VRAM during the test:
   rocm-smi
   # VRAM in use should be ~20-24 GiB. If it exceeds 28 GiB, stop the
   # service and report before retrying with a smaller -c.

## 4. Rewire the coding ladder (orca/ai_stack.py)
   # In AI_LADDERS["coding"], insert forge_deepseek as the FIRST step,
   # before kiln_codex. New order:
   #   coding: (forge_deepseek, kiln_codex, gemini_free, forge_qwen,
   #            kiln_quench, fry)
   # Rationale: cheapest sufficient LOCAL surface first. DeepSeek on
   # CRUCIBLE costs zero cloud data; kiln_codex (Codex CLI, OpenAI
   # authenticated) and gemini_free are cloud fallbacks. forge_qwen
   # (Qwen3.5-35B on the same CRUCIBLE) remains available as a deeper
   # local step but DeepSeek is preferred for coding because it is the
   # stronger reasoner.
   #
   # Also add a new service profile to AI_SERVICES:
   #   forge_deepseek = AIServiceProfile(
   #       "forge_deepseek", "forge",
   #       "preferred local coding, architecture, hard debugging, math and planning; zero cloud data usage",
   #       "DeepSeek-R1-Distill-Qwen-32B-Q4_K_M", "llama.cpp", "CRUCIBLE / AMD ROCm 7.2.1 / HIP",
   #       16_384, 1, 12, vram_budget_gib=24,
   #       deployment_state="live_pending_acceptance", may_author=True)
   #
   # And add to large_gpu_inference ladder if not already covered:
   #   large_gpu_inference: (forge_deepseek, forge_qwen, forge_crucible, fry)
   #
   # Run the validator after editing:
   #   python3 -c "from orca.ai_stack import validate_ai_stack; validate_ai_stack(); print('OK')"
   # It must pass. If it fails on VRAM (forge_deepseek 24 + forge_qwen 24
   # = 48 > 32), that is expected — they are NOT meant to run
   # simultaneously. The validator checks summed budgets, so either mark
   # one as not concurrently active or adjust: set forge_qwen's
   # vram_budget_gib to 0 with a comment that it shares CRUCIBLE with
   # DeepSeek exclusively (one at a time). Prefer the latter; it matches
   # reality.

## 5. Update models.py DEFAULT_ROUTES
   # coding: ModelRoute("coding", "forge_deepseek", "kiln_codex")
   # large_gpu_inference: ModelRoute("large_gpu_inference", "forge_deepseek", "human-runbook")
   # This makes the router prefer DeepSeek whenever local is capable.

## 6. Update the stack doc
   # In docs/FOUR_HOST_AI_STACK_2026-09-25.md, add a "2026-10-14 update"
   # section: DeepSeek-R1-Distill-Qwen-32B is now the first rung of the
   # coding ladder on CRUCIBLE. Cloud (Codex, Gemini) is fallback only.
   # Grok's standing instruction: always route coding work to CRUCIBLE
   # first; never burn cloud tokens when a local surface can do the job.

## 7. Commit and report
   # Commit all changes to main with message:
   #   "Activate DeepSeek on CRUCIBLE; coding ladder prefers local (2026-10-14)"
   # Report back: service status, health endpoint, smoke test output,
   # VRAM high-water, thermals, ladder diff, and validator result.
   # Write a CC_ note to the cc-bridge Drive folder:
   #   CC_note_crucible-deepseek-activated_2026-10-14.md
   # covering the same.

## 8. Out of scope (deliberate)
   # - No QUENCH review of this change in this pass (follow-up).
   # - No auto-restart logic, no remote shell from EMBER.
   # - No cloud provider changes.
   # - The Qwen3.5-35B conversational service on 11436 is untouched.
