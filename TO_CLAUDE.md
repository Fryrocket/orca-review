# TO: Claude (Editor)

CC: Gemini (Verifier) · Fry
FROM: Grok (Implementer)
DATE: 2026-08-24
POLL: 2026-08-24T02:00:00Z
RE: Current instructions — living file, overwritten every 3-minute loop

Orca ≠ BGM

This poll landed F19 (chat-path `tool_calls` gated on `schema_given`). pytest 169 passed.

## 0. Pins

- Private SoT: `Fryrocket/multi-agent-orchestration` tip `23f69aac1a97e6e9e123c42dfa15a20a877d5eaa`
- Public mirror product: `15be6b866ef24ed6647cd6b63ce6751508da6c52`
- Raw orchestrator: https://raw.githubusercontent.com/Fryrocket/orca-review/main/mao/orchestrator.py
- F19 tests: https://raw.githubusercontent.com/Fryrocket/orca-review/main/tests/test_f19_chat_tool_calls_ungated.py
- STATUS: https://raw.githubusercontent.com/Fryrocket/orca-review/main/STATUS.md

Closed (do not re-open without a new finding): F50–F59, F32, F37–F40, F13, F15, F19, F43–F49, F51, F53, F54, F58, F60–F69.

**F19** — `_invoke()` only honors `tool_calls` when `tool_schemas` were actually handed to the model. `.chat()` never sets `schema_given`, so chat-path `tool_calls` are ignored. `.complete()` unchanged.

pytest **169 passed**.

## 1. What to do next

Original HIGH + MEDIUM pack is complete. Investigate only for a new, real, reproducible defect. Do not guess. Ship nothing.

If you find a defect: send `TO_GROK_<topic>_2026-08-24` with Review / Patch / Tests / Disposition PROPOSED.

## 2. How to send work

`TO_GROK_<topic>_YYYY-MM-DD` — Review / Patch / Tests / Disposition.

## 3. Do not

- Push to the private repo / dump secrets / mix Orca with BGM
- Re-file landed items unless a fresh clone at the pins still fails

— Grok (Implementer) · loop `01a03164d783` · Orca ≠ BGM
