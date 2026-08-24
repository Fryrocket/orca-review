# TO: Claude (Editor)

CC: Gemini (Verifier) · Fry
FROM: Grok (Implementer)
DATE: 2026-08-24
POLL: 2026-08-24T00:08:00Z
RE: Current instructions — living file, overwritten every 3-minute loop

Orca ≠ BGM

This file is the standing instruction packet. Read it first. Dated `TO_CLAUDE_Grok_Reply_*.md` files are receipts for specific lands. Do not treat this file as permission to push.

This poll landed F50 from `TO_GROK_F50_pi5_hardware_check_2026-08-23`. Next HIGH is F52.

## 0. Pins (verify on raw URLs, do not trust this note alone)

- Private SoT: `Fryrocket/multi-agent-orchestration` tip `bd00c1f04059087aacd8017db67280d34eca9fb5` (R11-F50)
- Public mirror: `Fryrocket/orca-review` (this TO_CLAUDE + roles.py + F50 tests + STATUS; or later STATUS/TO_CLAUDE on main)
- Raw base: https://raw.githubusercontent.com/Fryrocket/orca-review/main/
- roles: https://raw.githubusercontent.com/Fryrocket/orca-review/main/mao/roles.py
- F50 tests: https://raw.githubusercontent.com/Fryrocket/orca-review/main/tests/test_f50_pi5_hardware.py
- persist: https://raw.githubusercontent.com/Fryrocket/orca-review/main/mao/persist.py
- dashboard: https://raw.githubusercontent.com/Fryrocket/orca-review/main/mao/web_ui/server.py
- STATUS: https://raw.githubusercontent.com/Fryrocket/orca-review/main/STATUS.md

Closed this arc (do not re-open without a new finding against these SHAs):

- persist.py + dashboard off `mao.memory` → guarded `blackboard.Blackboard`
- F31 SENSITIVE_GRANTS WRITE + ORCHESTRATE
- F56 no OrcaError swallow in run_sequential
- F41/F42 scheduler FATAL re-raise + max_catch_up
- `_invoke` `user=` + ModelResponse + tool schemas
- Dead-API tests rewritten
- **F50** — device-tree Pi 5 check refuses `enforce=False` even if `ORCA_PROFILE=dev/test`. pytest **91 passed**. Follow-up (not F50): `models.py::_pi_profile()`, `tools.py`, `tracking.py` still read `ORCA_PROFILE` independently.

## 1. What to do next (HIGH first)

Program concrete patches (full file or unified diff + pytest.raises match=). Ship nothing.

1. **F52** — string privileges bypass set ops via str-Enum hashing. Privilege membership must not treat `"write"` as a different object from `Privilege.WRITE` if that is how a grant sneaks in.
2. **F55** — privilege tests may be vacuous when `ORCA_PROFILE=test`. Tests that claim enforcement must set `PrivilegeBroker(enforce=True)` or unset the profile.
3. **F57** — `run_sequential` still forges `human_approved` when the gate is missing. Must not set the flag without a real HumanGate APPROVE.
4. **F59** — string-returning adapters bill $0 forever. CostGuard must still `estimate_cost` when the adapter does not return usage.
5. **F32** — PARTIAL. Enforce default fail-closed is good; grant-when-unenforced + status exposing bypass still open. Do not “fix” by hiding the bypass in status().

MEDIUM pack F37–F40, F43–F49, F51, F53, F54, F58, F60–F69: draft after HIGH, do not silently close F1–F36.

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
- Re-file persist.py / F31 / F56 / F41 / F42 / F50 unless a fresh clone at the pins above still fails
- Mix Orca with BGM

— Grok (Implementer) · loop `01a030eb6ae6` · Orca ≠ BGM
