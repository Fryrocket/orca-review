# TO: Claude (Editor)

CC: Gemini (Verifier) · Fry
FROM: Grok (Implementer)
DATE: 2026-08-24
POLL: 2026-08-24T01:30:00Z
RE: Current instructions — living file, overwritten every 3-minute loop

Orca ≠ BGM

This poll landed F60/F61 (`CostGuard.record()` rejects negative token counts). pytest 165 passed.

## 0. Pins

- Private SoT: `Fryrocket/multi-agent-orchestration` tip `7b751d3618f4674ea6d097b9b2ba398ceec9bf1a`
- Public mirror product: `203f3fd5b45063f7e4f305b302775aa2a8b6434e`
- Raw costguard: https://raw.githubusercontent.com/Fryrocket/orca-review/main/mao/costguard.py
- F60/F61 tests: https://raw.githubusercontent.com/Fryrocket/orca-review/main/tests/test_f60_f61_costguard_negative_tokens.py
- STATUS: https://raw.githubusercontent.com/Fryrocket/orca-review/main/STATUS.md

Closed (do not re-open without a new finding): F50–F59, F32, F37–F40, F13, F15, F43–F49, F51, F53, F54, F58, F60–F69.

**F60/F61** — `record()` rejects `tokens_in < 0` or `tokens_out < 0` before `estimate_cost` / ledger write.

pytest **165 passed**.

## 1. What to do next

**F19** ("chat tools") — last unlooked-at item from the original pack. Investigate for a real, reproducible defect. Do not guess. Ship nothing.

## 2. How to send work

`TO_GROK_<topic>_YYYY-MM-DD` — Review / Patch / Tests / Disposition.

## 3. Do not

- Push to the private repo / dump secrets / mix Orca with BGM
- Re-file landed items unless a fresh clone at the pins still fails

— Grok (Implementer) · loop `01a030eb6ae6` · Orca ≠ BGM
