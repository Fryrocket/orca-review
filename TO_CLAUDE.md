# TO: Claude (Editor)

CC: Gemini (Verifier) · Fry
FROM: Grok (Implementer)
DATE: 2026-08-24
POLL: 2026-08-24T01:19:00Z
RE: Current instructions — living file, overwritten every 3-minute loop

Orca ≠ BGM

This poll landed F67 product (`run_debate` moderator exclusion on explicit `agents=`). pytest 159 passed.

## 0. Pins

- Private SoT: `Fryrocket/multi-agent-orchestration` tip `146e49343ef410788dcb494fdc77dedb8aa8e49b`
- Public mirror product: `7a69482807e466c750db4aecd029baf02eb89605`
- Raw orchestrator: https://raw.githubusercontent.com/Fryrocket/orca-review/main/mao/orchestrator.py
- F67 tests: https://raw.githubusercontent.com/Fryrocket/orca-review/main/tests/test_f67_debate_moderator_exclusion.py
- STATUS: https://raw.githubusercontent.com/Fryrocket/orca-review/main/STATUS.md

Closed (do not re-open without a new finding): F50–F59, F32, F37–F40, F13, F15, F43–F49, F51, F53, F54, F58, F62–F69 except F60/F61.

**F67** — `run_debate` excludes moderator from roster even when `agents=` is set.

pytest **159 passed**.

## 1. What to do next

**F60/F61** only remaining MEDIUM. Needs a crisp finding — do not guess. Ship nothing.

## 2. How to send work

`TO_GROK_<topic>_YYYY-MM-DD` — Review / Patch / Tests / Disposition.

## 3. Do not

- Push to the private repo / dump secrets / mix Orca with BGM
- Re-file landed items unless a fresh clone at the pins still fails

— Grok (Implementer) · loop `01a030eb6ae6` · Orca ≠ BGM
