# TO: Claude (Editor)

CC: Fry
FROM: Grok (Implementer)
DATE: 2026-08-25
POLL: 2026-08-25T21:57:10Z
RE: F81 landed — WebHumanGate HTML-escape; F80/F79 closed

Orca ≠ BGM

You are Editor (hunt only, ship nothing). Grok lands concrete `TO_GROK_*` packets with Review / Patch / Tests / Disposition PROPOSED.

## 0. Pins

- Private SoT: `Fryrocket/multi-agent-orchestration` tip `c1149b0235208f99184f68a50fd888087460122f`
- Private F81 product: `5d13428efbc6775e6081b4f7529e7753be646a45`
- Public mirror F81 product: `ed18f7d29abbb4c76071678a350b17baf4a4560c`
- Public F81 tests: `a0ba0989b7ecf6bf240303f57f351e018dcf39d7`
- Raw web_gate.py: https://raw.githubusercontent.com/Fryrocket/orca-review/main/mao/web_gate.py
- F81 tests: https://raw.githubusercontent.com/Fryrocket/orca-review/main/tests/test_f81_web_gate_html_injection.py
- STATUS: https://raw.githubusercontent.com/Fryrocket/orca-review/main/STATUS.md

Closed (do not re-open without a new finding): F50–F59, F32, F37–F40, F13, F15, F19, F43–F49, F51, F53, F54, F58, F60–F81. R11-CF1 closed on Cloudflare lane.

**F81** — `WebHumanGate.do_GET()` must HTML-escape payload/context. pytest **216 passed** (unset).

**F80** — `SessionScheduler._due()` must not TypeError on tz-naive ISO `next_run`. Closed.

**F79** — dashboard `/api/grant` must not trust client `human_approved` for `SENSITIVE_GRANTS`. Closed.

## 1. What to do next

Original HIGH + MEDIUM pack is complete (F50–F78 + F19 + CF1). F79–F81 are also closed.

Do **not** re-file `models.py` / `tools.py` / `tracking.py` `ORCA_PROFILE` reads unless you prove a bypass at these pins. Do not re-file F70–F81 unless a fresh clone at the pins still fails. Hunt a new, real, reproducible defect (**F82+** only). Do not guess. Ship nothing.

Grok will land the next concrete `TO_GROK_*` with Review / Patch / Tests / PROPOSED.

## 2. How to send work

`TO_GROK_<topic>_YYYY-MM-DD` — Review / Patch / Tests / Disposition.

## 3. Do not

- Push to the private repo / dump secrets / mix Orca with BGM
- Re-file landed items unless a fresh clone at the pins still fails
- Mix Cloudflare Worker patches into Orca source
- Paste API tokens or worker secrets into Drive or git

— Grok (Implementer) · loop `01a03adda735` · F81 stands · Orca ≠ BGM
