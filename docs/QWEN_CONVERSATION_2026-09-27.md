# ORCA conversational model migration

User requested replacing DeepSeek with Qwen3.5-35B-A3B and explicitly approved
a FORGE reboot. KILN remains the Studio UI; CRUCIBLE hosts the model.

## Model and controls

- Unsloth `Qwen3.5-35B-A3B-Q4_K_M.gguf`, 22,016,023,168 bytes.
- Source revision: `bc014a17be43adabd7066b7a86075ff935c6a4e2`.
- Verified SHA256: `3b46d1066bc91cc2d613e3bc22ce691dd77e6f0d33c9060690d24ce6de494375`.
- Existing llama.cpp commit `4e74811`; alias `ORCA-QWEN`.
- Loopback `127.0.0.1:11436`, 16K context, one slot, thinking disabled.
- No new action authority. Existing structured output validation, role checks,
  and read-only broker remain. Native tool list remains empty.
- Qwen service replaces `orca-deepseek-inference.service`.

## Measured acceptance evidence

- 352 tests passed locally with loopback test-server permission.
- Six consecutive real-model checks passed before and after reboot: greeting,
  project ideas, science explanation, arithmetic, planning, and verified
  `file.read` of `pyproject.toml` returning `orca-control-plane`.
- Post-reboot model checks took 2.11–2.63 seconds each, including planning.
- ORCA health remained healthy after every request.
- Boot ID changed from `933a58b0-55e7-49e2-a8a0-af670886f1eb` to
  `cf7073ce-db9f-4da1-ab35-4c80d76f7bb0`; Qwen started automatically.
- Rollback service test: stopped Qwen, restarted DeepSeek, verified healthy
  endpoint and old model alias, then disabled DeepSeek before reboot.
- Qwen occupied 22,708,215,808 of 34,208,743,424 VRAM bytes before reboot.
- Post-reboot SDXL image via KILN returned HTTP200, 768x768 PNG, 954755 bytes,
  worker CRUCIBLE, prompt ID `6e7c2331-d969-46d2-bc4e-636f59d521e8`.
- QUENCH review `chatcmpl-BRhWLPTgQRlaUVLEoT5jLDRnrfFPZAcx` was conditional
  on the reboot and image checks, both subsequently passed. Its broad safety
  claims are advisory, not proof that prompting prevents injection.

## Recovery

Previous service and acceptance files are preserved in
`/var/lib/orca/qwen-migration-20260927` on FORGE. Previous release is
`81debc13cccb7922f2ba0300aa68c6630b3ec8ed`. Restore all corresponding route,
acceptance, and model-service settings together; never run both GPU models
on the shared port at once.
