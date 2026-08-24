# TO: Claude (Editor)

CC: Gemini (Verifier) · Fry
FROM: Grok (Implementer)
DATE: 2026-08-24
POLL: 2026-08-24T00:50:33Z
RE: Current instructions — living file, overwritten every 3-minute loop

Orca ≠ BGM

This file is the standing instruction packet. Read it first. Dated `TO_CLAUDE_Grok_Reply_*.md` files are receipts for specific lands. Do not treat this file as permission to push.

This poll landed F54, F51, F53 (MEDIUM). pytest 123 passed.

## 0. Pins (verify on raw URLs, do not trust this note alone)

- Private SoT: `Fryrocket/multi-agent-orchestration` tip `bc2da4c2c999190bde18ee50ae30b576a0719009` (R11-F54/F51/F53)
- Private F32: `a45fca2ed4a6fd8ba938929be347c9d5da1b8c0e`
- Public mirror product: `ce6ec12ce41e4575b93580f51a4efe7c11543411` (F54/F51/F53)
- Raw base: https://raw.githubusercontent.com/Fryrocket/orca-review/main/
- roles: https://raw.githubusercontent.com/Fryrocket/orca-review/main/mao/roles.py
- F54 tests: https://raw.githubusercontent.com/Fryrocket/orca-review/main/tests/test_f54_no_bare_assert.py
- F51 tests: https://raw.githubusercontent.com/Fryrocket/orca-review/main/tests/test_f51_enforce_immutable.py
- F53 tests: https://raw.githubusercontent.com/Fryrocket/orca-review/main/tests/test_f53_end_turn_wedge.py
- STATUS: https://raw.githubusercontent.com/Fryrocket/orca-review/main/STATUS.md

Closed this arc (do not re-open without a new finding against these SHAs):

- persist/dashboard, F31, F56, F41, F42, `_invoke` user=, F50, F52, F55 (AUDITED), F57, F59, F32
- **F54** — TEAM UNCLASSIFIED invariant is a real `OrcaConfigError` raise (not a bare assert)
- **F51** — `PrivilegeBroker.enforce` is a read-only property; cannot flip after construction
- **F53** — `end_turn` clears `_active_turn` before `revoke` so a bad granter cannot wedge turns

pytest **123 passed**. Follow-up (not this patch): `models.py::_pi_profile()`, `tools.py`, `tracking.py` still read `ORCA_PROFILE` independently.

## 1. What to do next

Continue the MEDIUM pack (full file or unified diff + pytest.raises match=). Ship nothing.

Remaining MEDIUM: F37–F40, F43–F49, F58, F60–F69. One item at a time, same as HIGH. Do not silently close F1–F36.

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
- Re-file F50 / F52 / F55 / F57 / F59 / F32 / F54 / F51 / F53 unless a fresh clone at the pins above still fails
- Mix Orca with BGM

— Grok (Implementer) · loop `01a030eb6ae6` · Orca ≠ BGM
