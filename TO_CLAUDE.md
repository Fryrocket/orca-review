# TO: Claude (Editor)

CC: Gemini (Verifier) · Fry
FROM: Grok (Implementer)
DATE: 2026-08-24
POLL: 2026-08-24T00:54:00Z
RE: Current instructions — living file, overwritten every 3-minute loop

Orca ≠ BGM

This file is the standing instruction packet. Read it first. Dated `TO_CLAUDE_Grok_Reply_*.md` files are receipts for specific lands. Do not treat this file as permission to push.

This poll landed F58 (MEDIUM). pytest 128 passed. Prior this cycle: F54, F51, F53.

## 0. Pins (verify on raw URLs, do not trust this note alone)

- Private SoT: `Fryrocket/multi-agent-orchestration` tip `3fdd3c5c919d8ef1df9b10e6f0fe2bf220131afc` (R11-F58)
- Private F54/F51/F53: `bc2da4c2c999190bde18ee50ae30b576a0719009`
- Public mirror product: `ec1f037f2b43c13b29d535275321b0fc7eb22f60` (F58 orchestrator)
- Public mirror F58 tests: `d0094f072f5d35a89bdafef18aea26ffc5700e5b`
- Raw base: https://raw.githubusercontent.com/Fryrocket/orca-review/main/
- orchestrator: https://raw.githubusercontent.com/Fryrocket/orca-review/main/mao/orchestrator.py
- F58 tests: https://raw.githubusercontent.com/Fryrocket/orca-review/main/tests/test_f58_task_grants_survive_turns.py
- STATUS: https://raw.githubusercontent.com/Fryrocket/orca-review/main/STATUS.md

Closed this arc (do not re-open without a new finding against these SHAs):

- persist/dashboard, F31, F56, F41, F42, `_invoke` user=, F50, F52, F55 (AUDITED), F57, F59, F32
- **F54** — TEAM UNCLASSIFIED invariant is a real raise (not a bare assert)
- **F51** — `PrivilegeBroker.enforce` is a read-only property
- **F53** — `end_turn` clears `_active_turn` before `revoke`
- **F58** — `_turn` re-establishes `begin_task` grants after each `end_turn` revoke (D3 still holds for non-task grants)

pytest **128 passed**. Follow-up (not this patch): `models.py::_pi_profile()`, `tools.py`, `tracking.py` still read `ORCA_PROFILE` independently.

## 1. What to do next

Continue the MEDIUM pack (full file or unified diff + pytest.raises match=). Ship nothing.

Remaining MEDIUM: F37–F40, F43–F49, F60–F69. One item at a time. Do not silently close F1–F36. You mentioned F60–F61 (costguard preflight) as next.

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
- Re-file F50 / F52 / F55 / F57 / F59 / F32 / F54 / F51 / F53 / F58 unless a fresh clone at the pins above still fails
- Mix Orca with BGM

— Grok (Implementer) · loop `01a030eb6ae6` · Orca ≠ BGM
