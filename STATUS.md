# Review mirror status

- Repo: https://github.com/Fryrocket/orca-review (public)
- Private implementer: [Fryrocket/multi-agent-orchestration](https://github.com/Fryrocket/multi-agent-orchestration) **v0.5.10** @ `30f8fd9`
- **2026-08-17 v0.5.10 landed.** Review-mirror core is now the product path. This public repo is re-synced so Claude can verify raw source.

## What is on this mirror (review surface, not a full install)

Core: `mao/tools.py` `roles.py` `cost_store.py` `tracking.py` `errors.py` `pricing.py` `scheduler_ntp.py`

Product wiring: `mao/orchestrator.py` `models.py` `human.py` `scheduler.py` `web_ui/auth.py` `web_ui/server.py` `web_ui/static/{app.js,index.html}`

Tests (source for review): `tests/test_round6.py` `test_product.py` `test_privileges.py`

This repo is **not** pip-installable. Missing `agent.py` / `bus.py` / `memory.py` on purpose. Run pytest in the private repo.

## pytest (private `main` @ `30f8fd9`)

`tests/test_round6.py` + `tests/test_product.py` + `tests/test_privileges.py` → **68 passed**

## Landed (items 1–6)

- `ToolRegistry.call(*, agent=)` keyword-only; orchestrator passes `agent=`; hard denials raise `HardPrivilegeError`
- `begin_task(..., human_approved=)` required for sensitive grants
- Dashboard: LAN bind needs `ORCA_DASHBOARD_LAN=1` + `ORCA_DASHBOARD_TOKEN`; bearer via `hmac.compare_digest`; client cannot toggle `enforce_privileges`; grants need Fry checkbox; gate timeout fail-closed; skip removed
- Models: `ORCA_MODEL` default `grok-2-1212`; Pi missing key → `OrcaConfigError` (no silent Echo)
- Scheduler `require_ntp_or_refuse(stage=arm|fire)`; fire failure → `refused_ntp`
- Kill-switch records then raises; negative ledger amounts refused; `tools_allowed` on read-only

## Still not landed

Round-7 orchestrator / bus / blackboard rewrite (E1–E9 **ACCEPT** in `ROUND7_DISPOSITION.md`; needs clean `.py`, not PDF). CostGuard must bill real `estimate_cost`, never `cost_usd=0.0`. Do not land the disposition adapter as written.

Drive `orca/` INDEX still stale (0.4.0). Do not dump more source into Drive. Confirm with Fry before any Drive cleanup.

Orca ≠ BGM.
