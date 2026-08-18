# Review mirror status

- Repo: https://github.com/Fryrocket/orca-review (public)
- Private implementer: [Fryrocket/multi-agent-orchestration](https://github.com/Fryrocket/multi-agent-orchestration) **v0.5.10** @ `c3ee067920b4adda15a9e77331e9c8f4add20b24`
- **2026-08-18** — Claude LITE findings (F1–F10) reviewed by Grok. All code findings F1–F9 already present in private tree (errors hierarchy, stage= on require_ntp_or_refuse, negative cost refused, tools_allowed gate on read-only, target validation on grant, VAR_POSITIONAL rejected at register, price table staleness + normalize). F2 remains deliberate (agent/bus/memory not on mirror). F10 closed by this update (single canonical SHA).

## What is on this mirror (review surface, not a full install)

Core: `mao/tools.py` `roles.py` `cost_store.py` `tracking.py` `errors.py` `pricing.py` `scheduler_ntp.py`

Product wiring: `mao/orchestrator.py` `models.py` `human.py` `scheduler.py` `web_ui/auth.py` `web_ui/server.py` `web_ui/static/{app.js,index.html}`

Tests (source for review): `tests/test_round6.py` `test_product.py` `test_privileges.py`

This repo is **not** pip-installable. Missing `agent.py` / `bus.py` / `memory.py` on purpose. Run pytest in the private repo.

## pytest (private `main` @ `c3ee067`)

Prior claim at `30f8fd9`: `tests/test_round6.py` + `tests/test_product.py` + `tests/test_privileges.py` → **68 passed**. Re-run recommended after any further change; current tree already contains the defensive code Claude’s F1–F9 described.

## Landed (items 1–6 + F1–F9)

- `ToolRegistry.call(*, agent=)` keyword-only; orchestrator passes `agent=`; hard denials raise `HardPrivilegeError`
- `begin_task(..., human_approved=)` required for sensitive grants
- Dashboard: LAN bind needs `ORCA_DASHBOARD_LAN=1` + `ORCA_DASHBOARD_TOKEN`; bearer via `hmac.compare_digest`; client cannot toggle `enforce_privileges`; grants need Fry checkbox; gate timeout fail-closed; skip removed
- Models: `ORCA_MODEL` default `grok-2-1212`; Pi missing key → `OrcaConfigError` (no silent Echo)
- Scheduler `require_ntp_or_refuse(stage=arm|fire)`; fire failure → `refused_ntp`
- Kill-switch records then raises; negative ledger amounts refused; `tools_allowed` on read-only
- Full `OrcaError` hierarchy (closes prior N4 swallow path)
- Price table freshness check + model normalization
- PrivilegeBroker.grant validates target ∈ TEAM
- register rejects VAR_POSITIONAL write tools

## Still not landed

Round-7 orchestrator / bus / blackboard rewrite (E1–E9 **ACCEPT** in `ROUND7_DISPOSITION.md`; needs clean `.py`, not PDF). CostGuard must bill real `estimate_cost`, never `cost_usd=0.0`. Do not land the disposition adapter as written.

Drive `orca/` is paper trail only. Stale INDEX / duplicate source dumps cleaned 2026-08-17. SoT is this repo + private `main`. Do not dump more `.py` into Drive.

Orca ≠ BGM.
