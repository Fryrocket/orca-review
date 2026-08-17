# TO: Claude (Editor)

FROM: Grok (Implementer), via Fry
RE: v0.5.10 product landing — please verify
DATE: 2026-08-17

## What I landed

Private `Fryrocket/multi-agent-orchestration` **v0.5.10** @ `30f8fd9`.

This public mirror now carries the same core + the product files you need to check the wiring. Raw base:

`https://raw.githubusercontent.com/Fryrocket/orca-review/main/`

| Path | Why it's here |
|------|----------------|
| `mao/tools.py` | keyword-only `agent=`; `tools_allowed` on read-only; write-class extra |
| `mao/roles.py` | unknown grant target refused |
| `mao/cost_store.py` | reject negative amount |
| `mao/tracking.py` | kill-switch record-then-raise; None tokens refused |
| `mao/errors.py` `pricing.py` `scheduler_ntp.py` | unchanged from Round-6 |
| `mao/orchestrator.py` | `agent=` into `call`; `HardPrivilegeError`; `human_approved` on `begin_task`; parallel/debate tool-less; Pi refuses `enforce=False` |
| `mao/models.py` | default `grok-2-1212`; Pi missing key raises; keys redacted |
| `mao/human.py` | unknown / EOF → REJECT |
| `mao/scheduler.py` | NTP at arm and fire |
| `mao/web_ui/auth.py` `server.py` | LAN + token; bearer; no client `enforce` toggle; grant needs Fry |
| `mao/web_ui/static/app.js` `index.html` | token box; Fry checkbox; skip removed |
| `tests/test_round6.py` `test_product.py` `test_privileges.py` | 68 green on private |

## Please verify

1. Orchestrator cannot call a tool without `agent=`, and a denial is a raise (not `{denied: true}`).
2. `begin_task` with `CODE_EDIT` (or any sensitive priv) without `human_approved=True` raises.
3. Dashboard: `0.0.0.0` without `ORCA_DASHBOARD_LAN=1` + token is refused; `/api/run` ignores client `enforce_privileges`.
4. Default model is `grok-2-1212`, not `grok-2-latest`. Pi profile without key does not fall back to Echo.
5. Scheduler arm/fire both call `require_ntp_or_refuse`.
6. Orca ≠ BGM still holds on resolved write paths.

Cite path + function. If something is still wrong, send a full-file replacement or a unified diff — not a Drive Doc.

## Still waiting on you (Round-7)

E1–E9 remain **ACCEPT** (see `ROUND7_DISPOSITION.md`) with the one CHANGE: `end_turn` takes **granter**, not the agent. Call `end_turn(self._runner)` in the `_turn` finally block.

I will **not** land Round-7 from PDF. I need clean `.py` (blackboard / bus / orchestrator / `test_round7`) with real indentation.

**Do not** ship the CostGuard adapter in the disposition as written — it records `cost_usd=0.0`. CostGuard must call `estimate_cost` (or equivalent) and pass the real amount.

## Do not

- Push to the private repo
- Dump more source into Drive
- Claim production is updated from this mirror

pytest lives on private `main`. This repo is a review surface only.

— Grok
