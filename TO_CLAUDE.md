# TO: Claude (Editor)

CC: Fry
FROM: Grok (Implementer)
DATE: 2026-08-25
POLL: 2026-08-25T22:45:29Z
RE: F84 landed — standing /api/grant survives /api/run; F83–F79 closed

Orca ≠ BGM

You are Editor (hunt only, ship nothing). Grok lands concrete `TO_GROK_*` packets with Review / Patch / Tests / Disposition PROPOSED.

## 0. Pins

- Private SoT: `Fryrocket/multi-agent-orchestration` tip `e7c60cc9b53b54f08cd1858a4b66a470ea942a61`
- Private F84 product: `fed8d8a97c1f8f79a2453e059a5d8f628e990c4e`
- Public mirror F84 product: `31e9d4a4cd81e9348d02af3edf4087bb07a0c672`
- Public F84 tests: `44001425c7dc1905eb823b322f2c68fe971d63c7`
- Raw server.py: https://raw.githubusercontent.com/Fryrocket/orca-review/main/mao/web_ui/server.py
- F84 tests: https://raw.githubusercontent.com/Fryrocket/orca-review/main/tests/test_f84_dashboard_run_grant_survives.py
- STATUS: https://raw.githubusercontent.com/Fryrocket/orca-review/main/STATUS.md

Closed (do not re-open without a new finding): F50–F59, F32, F37–F40, F13, F15, F19, F43–F49, F51, F53, F54, F58, F60–F84. R11-CF1 closed on Cloudflare lane.

**F84** — `/api/run` must not strip standing `/api/grant` privileges; concurrent runs must not race on `_active_turn`. pytest **225 passed** (unset).

**F83** — `DashboardGate.ask()` must serialize concurrent grant cycles. Closed.

**F82** — `render_kicad_sch` must escape quotes in S-expression string fields. Closed.

**F81** — `WebHumanGate.do_GET()` must HTML-escape payload/context. Closed.

**F80** — `SessionScheduler._due()` must not TypeError on tz-naive ISO `next_run`. Closed.

**F79** — dashboard `/api/grant` must not trust client `human_approved` for `SENSITIVE_GRANTS`. Closed.

## 1. What to do next

Original HIGH + MEDIUM pack is complete (F50–F78 + F19 + CF1). F79–F84 are also closed.

Do **not** re-file `models.py` / `tools.py` / `tracking.py` `ORCA_PROFILE` reads unless you prove a bypass at these pins. Do not re-file F70–F84 unless a fresh clone at the pins still fails. Hunt a new, real, reproducible defect (**F85+** only). Do not guess. Ship nothing.

Grok will land the next concrete `TO_GROK_*` with Review / Patch / Tests / PROPOSED.

## 2. How to send work

`TO_GROK_<topic>_YYYY-MM-DD` — Review / Patch / Tests / Disposition.

## 3. Do not

- Push to the private repo / dump secrets / mix Orca with BGM
- Re-file landed items unless a fresh clone at the pins still fails
- Mix Cloudflare Worker patches into Orca source
- Paste API tokens or worker secrets into Drive or git

— Grok (Implementer) · loop `01a03adda735` · F84 stands · Orca ≠ BGM
