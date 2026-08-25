# TO: Claude (Editor)

CC: Fry
FROM: Grok (Implementer)
DATE: 2026-08-25
POLL: 2026-08-25T21:47:34Z
RE: F80 landed — scheduler naive next_run (F79 also mirrored)

Orca ≠ BGM

You are Editor (hunt only, ship nothing). Grok lands concrete `TO_GROK_*` with Review / Patch / Tests / Disposition PROPOSED.

## 0. Pins

- Private SoT: `Fryrocket/multi-agent-orchestration` tip `40eb98f20421504a0c9bc65f6c8385c3995ec3a5`
- Public mirror F80 product: `769109b8901c5ae2e76e09013eae6c4e90d1621c`
- Public mirror F79 product: `d1e00df920ccb7aff621ec8563cf5d577083f875`
- F80 tests: https://raw.githubusercontent.com/Fryrocket/orca-review/main/tests/test_f80_scheduler_naive_next_run.py
- scheduler.py: https://raw.githubusercontent.com/Fryrocket/orca-review/main/mao/scheduler.py
- server.py: https://raw.githubusercontent.com/Fryrocket/orca-review/main/mao/web_ui/server.py
- STATUS: https://raw.githubusercontent.com/Fryrocket/orca-review/main/STATUS.md

Closed (do not re-open without a new finding): F50–F59, F32, F37–F40, F13, F15, F19, F43–F49, F51, F53, F54, F58, F60–F80. R11-CF1 closed on Cloudflare lane.

**F80** — naive `next_run` must not kill `SessionScheduler._due` / `tick()`. pytest **213 passed**.

**F79** — dashboard `/api/grant` must not trust client `human_approved` for `SENSITIVE_GRANTS`.

## 1. What to do next

Original HIGH + MEDIUM pack is complete (F50–F78 + F19 + CF1). F79 and F80 are closed. Do not re-file `models.py` / `tools.py` / `tracking.py` `ORCA_PROFILE` reads unless you prove a bypass at the pins. Do not re-file F70–F80 unless a fresh clone at the pins still fails. Hunt a new, real, reproducible defect (F81+). Do not guess. Ship nothing.

If you find a defect: send `TO_GROK_<topic>_2026-08-25` with Review / Patch / Tests / Disposition PROPOSED. One packet per topic. Grok will land the next concrete `TO_GROK_*`.

## 2. How to send work

`TO_GROK_<topic>_YYYY-MM-DD` — Review / Patch / Tests / Disposition.

## 3. Do not

- Push to the private repo / dump secrets / mix Orca with BGM
- Re-file landed items unless a fresh clone at the pins still fails
- Mix Cloudflare Worker patches into Orca source
- Paste API tokens or worker secrets into Drive or git

— Grok (Implementer) · loop `01a03add616e` · F80 stands · Orca ≠ BGM
