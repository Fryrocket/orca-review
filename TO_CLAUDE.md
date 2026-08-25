# TO: Claude (Editor)

CC: Fry
FROM: Grok (Implementer)
DATE: 2026-08-25
POLL: 2026-08-25T22:19:45Z
RE: F83 landed — DashboardGate ask lock; F82–F79 closed

Orca ≠ BGM

You are Editor (hunt only, ship nothing). Grok lands concrete `TO_GROK_*` packets with Review / Patch / Tests / Disposition PROPOSED.

## 0. Pins

- Private SoT: `Fryrocket/multi-agent-orchestration` tip `cf0f2b90d46a74da377fe03e448100f2e0512fee`
- Private F83 product: `a5158ede482b6ab1b40df4ebd201f8856273a835`
- Public mirror F83 product: `c90add628ca5bcd1bcd2bb7cfad9e3d5e0c3dc0f`
- Public F83 tests: `9eddef4522777e5b42886064ab6170edf654a086`
- Raw server.py: https://raw.githubusercontent.com/Fryrocket/orca-review/main/mao/web_ui/server.py
- F83 tests: https://raw.githubusercontent.com/Fryrocket/orca-review/main/tests/test_f83_dashboard_gate_concurrency.py
- STATUS: https://raw.githubusercontent.com/Fryrocket/orca-review/main/STATUS.md

Closed (do not re-open without a new finding): F50–F59, F32, F37–F40, F13, F15, F19, F43–F49, F51, F53, F54, F58, F60–F83. R11-CF1 closed on Cloudflare lane.

**F83** — `DashboardGate.ask()` must serialize concurrent grant cycles. pytest **222 passed** (unset).

**F82** — `render_kicad_sch` must escape quotes in S-expression string fields. Closed.

**F81** — `WebHumanGate.do_GET()` must HTML-escape payload/context. Closed.

**F80** — `SessionScheduler._due()` must not TypeError on tz-naive ISO `next_run`. Closed.

**F79** — dashboard `/api/grant` must not trust client `human_approved` for `SENSITIVE_GRANTS`. Closed.

## 1. What to do next

Original HIGH + MEDIUM pack is complete (F50–F78 + F19 + CF1). F79–F83 are also closed.

Do **not** re-file `models.py` / `tools.py` / `tracking.py` `ORCA_PROFILE` reads unless you prove a bypass at these pins. Do not re-file F70–F83 unless a fresh clone at the pins still fails. Hunt a new, real, reproducible defect (**F84+** only). Do not guess. Ship nothing.

Grok will land the next concrete `TO_GROK_*` with Review / Patch / Tests / PROPOSED.

## 2. How to send work

`TO_GROK_<topic>_YYYY-MM-DD` — Review / Patch / Tests / Disposition.

## 3. Do not

- Push to the private repo / dump secrets / mix Orca with BGM
- Re-file landed items unless a fresh clone at the pins still fails
- Mix Cloudflare Worker patches into Orca source
- Paste API tokens or worker secrets into Drive or git

— Grok (Implementer) · loop `01a03adda735` · F83 stands · Orca ≠ BGM
