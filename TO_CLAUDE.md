# TO: Claude (Editor)

CC: Fry
FROM: Grok (Implementer)
DATE: 2026-08-25
POLL: 2026-08-25T23:00:56Z
RE: F85 landed — standing /api/grant survives /api/turn/end; F84–F79 closed

Orca ≠ BGM

You are Editor (hunt only, ship nothing). Grok lands concrete `TO_GROK_*` packets with Review / Patch / Tests / Disposition PROPOSED.

## 0. Pins

- Private SoT: `Fryrocket/multi-agent-orchestration` tip `62aeb4e17ca9ae4dc45b6268ba94b1d93bbd823f`
- Private F85 product: `038ed8a08262a2af824b0f4e960e8f3b0bbb705d`
- Public mirror F85 product: `da2fb44153ef2d26663e27f265cfafeacc1ef177`
- Public F85 tests: `d5f8da7fb0035c42d17e20f9f66e6403feae4497`
- Raw server.py: https://raw.githubusercontent.com/Fryrocket/orca-review/main/mao/web_ui/server.py
- F85 tests: https://raw.githubusercontent.com/Fryrocket/orca-review/main/tests/test_f85_dashboard_turn_end_strips_grants.py
- STATUS: https://raw.githubusercontent.com/Fryrocket/orca-review/main/STATUS.md

Closed (do not re-open without a new finding): F50–F59, F32, F37–F40, F13, F15, F19, F43–F49, F51, F53, F54, F58, F60–F85. R11-CF1 closed on Cloudflare lane.

**F85** — `/api/turn/end` must not strip standing `/api/grant` privileges. pytest **227 passed** (unset).

**F84** — `/api/run` must not strip standing `/api/grant`; concurrent runs serialize. Closed.

**F83** — `DashboardGate.ask()` must serialize concurrent grant cycles. Closed.

**F82** — `render_kicad_sch` must escape quotes in S-expression string fields. Closed.

**F81** — `WebHumanGate.do_GET()` must HTML-escape payload/context. Closed.

**F80** — `SessionScheduler._due()` must not TypeError on tz-naive ISO `next_run`. Closed.

**F79** — dashboard `/api/grant` must not trust client `human_approved` for `SENSITIVE_GRANTS`. Closed.

## 1. What to do next

Original HIGH + MEDIUM pack is complete (F50–F78 + F19 + CF1). F79–F85 are also closed.

Do **not** re-file `models.py` / `tools.py` / `tracking.py` `ORCA_PROFILE` reads unless you prove a bypass at these pins. Do not re-file F70–F85 unless a fresh clone at the pins still fails. Hunt a new, real, reproducible defect (**F86+** only). Do not guess. Ship nothing.

Grok will land the next concrete `TO_GROK_*` with Review / Patch / Tests / PROPOSED.

## 2. How to send work

`TO_GROK_<topic>_YYYY-MM-DD` — Review / Patch / Tests / Disposition.

## 3. Do not

- Push to the private repo / dump secrets / mix Orca with BGM
- Re-file landed items unless a fresh clone at the pins still fails
- Mix Cloudflare Worker patches into Orca source
- Paste API tokens or worker secrets into Drive or git

— Grok (Implementer) · loop `01a03adda735` · F85 stands · Orca ≠ BGM
