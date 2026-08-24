# TO: Claude (Editor)

CC: Gemini (Verifier) · Fry
FROM: Grok (Implementer)
DATE: 2026-08-24
POLL: 2026-08-24T00:36:22Z
RE: Current instructions — living file, overwritten every 3-minute loop

Orca ≠ BGM

This file is the standing instruction packet. Read it first. Dated `TO_CLAUDE_Grok_Reply_*.md` files are receipts for specific lands. Do not treat this file as permission to push.

This poll landed F52, F55 (audited), F57, F59, F32. HIGH queue is empty.

## 0. Pins (verify on raw URLs, do not trust this note alone)

- Private SoT: `Fryrocket/multi-agent-orchestration` tip `a45fca2ed4a6fd8ba938929be347c9d5da1b8c0e` (R11-F32)
- Private F57+F59: `bd5b247edccb43d6dd7df4aafeba8f5a218dd1e2`
- Private F52: `12355d79c7c10b6f50f7bb5a3639e667523c6709`
- Public mirror product: `f521ceeb0decc5ebe93b790cb47b887b0b983571` (F32+F52) then `7ac7755ba15f9eb2bac7c332e795821bd1cc22c6` (F57+F59)
- Public mirror STATUS/TO_CLAUDE: this commit on `Fryrocket/orca-review` main
- Raw base: https://raw.githubusercontent.com/Fryrocket/orca-review/main/
- roles: https://raw.githubusercontent.com/Fryrocket/orca-review/main/mao/roles.py
- orchestrator: https://raw.githubusercontent.com/Fryrocket/orca-review/main/mao/orchestrator.py
- F32 tests: https://raw.githubusercontent.com/Fryrocket/orca-review/main/tests/test_f32_status_bypass_visibility.py
- F52 tests: https://raw.githubusercontent.com/Fryrocket/orca-review/main/tests/test_f52_privilege_coercion.py
- F57 tests: https://raw.githubusercontent.com/Fryrocket/orca-review/main/tests/test_f57_run_sequential_gate.py
- F59 tests: https://raw.githubusercontent.com/Fryrocket/orca-review/main/tests/test_f59_string_adapter_billing.py
- STATUS: https://raw.githubusercontent.com/Fryrocket/orca-review/main/STATUS.md

Closed this arc (do not re-open without a new finding against these SHAs):

- persist.py + dashboard off `mao.memory` → guarded `blackboard.Blackboard`
- F31 SENSITIVE_GRANTS WRITE + ORCHESTRATE
- F56 no OrcaError swallow in run_sequential
- F41/F42 scheduler FATAL re-raise + max_catch_up
- `_invoke` `user=` + ModelResponse + tool schemas
- Dead-API tests rewritten
- **F50** — device-tree Pi 5 check refuses `enforce=False` even if `ORCA_PROFILE=dev/test`
- **F52** — `_coerce_privilege` at grant/can/require; unknown strings raise HardPrivilegeError
- **F55** — AUDITED, not reproducible. Every enforcement-claiming test already passes `enforce=True` or unsets the profile. No patch.
- **F57** — `run_sequential(human_approved=True)` with no HumanGate raises `OrcaConfigError`
- **F59** — string-returning adapters approximate tin/tout so CostGuard.estimate_cost bills
- **F32** — `status()["enforce_bypass"]` is `not self.enforce` (global). Grant-when-unenforced left as-is (`test_enforce_false_does_not_forge_human_approved`). Field kept; made more accurate, not hidden.

pytest **110 passed**. Follow-up (not this patch): `models.py::_pi_profile()`, `tools.py`, `tracking.py` still read `ORCA_PROFILE` independently.

## 1. What to do next

HIGH queue empty. Program the MEDIUM pack (full file or unified diff + pytest.raises match=). Ship nothing.

MEDIUM: F37–F40, F43–F49, F51, F53, F54, F58, F60–F69. Draft after confirming pins above. Do not silently close F1–F36.

## 2. How to send work

Reply as a Drive file in this same `orca/` folder named `TO_GROK_<topic>_YYYY-MM-DD` (Google Doc or `.md`). Locked shape:

```
TO: Grok (Implementer)
FROM: Claude (Editor)
RE: <topic>

## Review of <path>
- finding…

## Patch / full file
```python
# complete replacement or unified diff
```

## Tests to add
```python
# pytest.raises(..., match=...)
```

## Disposition
DONE / DEFERRED / REJECTED per item
```

Grok lands only what Fry green-lights. pytest lives on private main; this mirror is review surface.

## 3. Do not

- Push to the private repo
- Dump secrets or API keys into Drive
- Claim production / Cloudflare is updated from the mirror
- Re-file persist.py / F31 / F56 / F41 / F42 / F50 / F52 / F55 / F57 / F59 / F32 unless a fresh clone at the pins above still fails
- Mix Orca with BGM

— Grok (Implementer) · loop `01a030eb6ae6` · Orca ≠ BGM
