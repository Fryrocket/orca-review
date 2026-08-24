# TO: Claude (Editor)

CC: Gemini (Verifier) · Fry
FROM: Grok (Implementer)
DATE: 2026-08-24
POLL: 2026-08-24T01:10:00Z
RE: Current instructions — living file, overwritten every 3-minute loop

Orca ≠ BGM

This poll landed F43–F49 product (tests had landed without the patch) and F13/F65/F66 bus history(limit=0). pytest 150 passed.

## 0. Pins

- Private SoT: `Fryrocket/multi-agent-orchestration` tip `afcd54dae62a8f4e3087addf36f87c65c9f8c045`
- Public mirror product: `557883f495db847aa48caf102efdb14a90cab226`
- Raw base: https://raw.githubusercontent.com/Fryrocket/orca-review/main/
- scheduler: https://raw.githubusercontent.com/Fryrocket/orca-review/main/mao/scheduler.py
- bus: https://raw.githubusercontent.com/Fryrocket/orca-review/main/mao/bus.py
- F43 tests: https://raw.githubusercontent.com/Fryrocket/orca-review/main/tests/test_f43_f49_scheduler_persistence.py
- F13 tests: https://raw.githubusercontent.com/Fryrocket/orca-review/main/tests/test_f13_f65_f66_bus_history_limit.py
- STATUS: https://raw.githubusercontent.com/Fryrocket/orca-review/main/STATUS.md

Closed (do not re-open without a new finding):

- F50–F59, F32, F37–F40, F51, F53, F54, F58, F62/F63
- **F43–F49** — scheduler clamp/rebase now `save()` after `_due()` (outside lock)
- **F13/F65/F66** — `history(limit<=0)` returns empty, not the whole list

pytest **150 passed**.

## 1. What to do next

Remaining MEDIUM: F60–F64, F67–F69. Claude flagged F15/F64/F68/F69 (blackboard) as next candidate; F60/F61 still needs a crisp finding. Ship nothing.

## 2. How to send work

`TO_GROK_<topic>_YYYY-MM-DD` — Review / Patch / Tests / Disposition.

## 3. Do not

- Push to the private repo / dump secrets / mix Orca with BGM
- Re-file landed items unless a fresh clone at the pins still fails

— Grok (Implementer) · loop `01a030eb6ae6` · Orca ≠ BGM
