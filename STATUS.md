# Orca Review Status — 2026-08-22 (night close)

**Core content pin:** `6d25f3ba48ff663265f82f0ca8cd36d46466aed0` (v0.5.12 Round-7 + R11)  
**Mirror tip:** update after this commit on main  
**Source:** Claude full R11 verification pass on 8 pinned files @ 6d25f3b

Files read this pass: errors.py, scheduler_ntp.py, scheduler.py, roles.py, orchestrator.py, costguard.py, bus.py, blackboard.py  
Not yet read in channel: agent.py, human.py, tools.py, pricing.py, tracking.py

---

## 19 fixes CONFIRMED REAL in landed source (not taken on trust)

F1 gate-before-mutation · F2 end_task + _task_grants · F3 FATAL_ERRORS re-raise in _invoke · F4 AgentToolProxy no run_id · F5 billed float round-trip · F9 preflight no swallow pricing · F10 negative cost reachable · F11 reset_run all modes · F12 bus snapshot outside lock · F16 _ensure_run_id reuse · F17 turn does not span yield · F18 parallel/debate refuse tools · F20 actual_rounds in prompt · F22 clear _active_run_id · F24 runner must be GROK · F25 no forge human_approved · F26 end_task empty raises · F27 re-entry refused · F28/F29 BaseException cleanup · F30 track grants before grant  
Plus: cost_guard required · Blackboard guard required · partial-revoke drops human_approved flag

---

## BLOCKING

| ID | Status | Summary |
|----|--------|--------|
| **R11-F31** | CONFIRMED OPEN | SENSITIVE_GRANTS omits WRITE + ORCHESTRATE; grant path bypasses human gate for board writes |
| **R11-F56** | NEW BLOCKING | run_sequential `except OrcaError: continue` undoes _invoke FATAL_ERRORS re-raise under on_step_error=continue |
| **R11-F32** | PARTIAL | enforce default fail-closed good; pi5 refusal good; still applies grant when unenforced; status exposes bypass |

---

## HIGH (selected)

| ID | Summary |
|----|--------|
| R11-F41 | scheduler._fire swallows FATAL_ERRORS; job re-arms |
| R11-F42 | Pi 5 clock-jump / backlog storm |
| R11-F50 | ORCA_PROFILE=dev on Pi silently disables enforcement |
| R11-F52 | string privileges bypass set ops via str-Enum hashing |
| R11-F55 | privilege tests may be vacuous if ORCA_PROFILE=test |
| R11-F57 | run_sequential still forges human_approved when gate missing |
| R11-F59 | string-returning adapters bill $0 forever |

---

## MEDIUM / LOW (entered)

F37–F40 (ntp probe) · F43–F49 (scheduler behaviour) · F51 enforce mutable · F53 end_turn wedge · F54 assert -O · F58 _turn blanket revoke vs task grants · F60–F61 costguard preflight · F6/F7 ceiling/derives · F13/F65/F66 bus · F15/F64/F68/F69 blackboard · F62–F63 run_id / end_task · F19 chat tools · F67 debate slice · **F50–F69 full set filed by Claude 2026-08-22**

F1–F36 not silently closed. F31 BLOCKING. F32 PARTIAL. F56 BLOCKING.

---

## Verified / closed (prior)

| ID | Status |
|----|--------|
| R8-F1 | CLOSED @ 6d25f3b |
| R8-F3 | CLOSED @ 6d25f3b |
| A14 call sites | VERIFIED @ 6d25f3b |
| W8/F12 | CLOSED PENDING Gemini independent four-part |

---

## Tests

```
tests/test_round7.py  NOT LANDED
  Superseded by tests/test_wiring_round7.py (real-wiring)
```

Wiring suite names (8):
- test_real_estimate_cost_returns_nonzero_for_known_model
- test_real_estimate_cost_raises_on_unknown_model
- test_usage_tracker_cost_guard_with_real_estimator
- test_record_passes_exact_tracking_signature
- test_record_never_relies_on_default_cost_usd
- test_blackboard_with_real_broker_raises_for_non_granted_writer
- test_blackboard_real_broker_denied_write_does_not_mutate
- test_blackboard_requires_explicit_guard

Coverage delta vs any 63-behaviour fakes suite: **not established**.

---

## Still open (honest)

- pytest post-land — never run for 0.5.12 this arc; report count **and** ORCA_PROFILE (see F55)
- R11-F6/F7/F8/F23 clean-.py cut (+ fold F56/F57) — Fry go/no-go
- CF: token exposure incident 2026-08-22 — revoke; no secrets in channel
- Gemini W8/F12 independent run
- Unread surface: agent.py, human.py, tools.py, pricing.py, tracking.py

---

## Claude orders (active, night close)

1. ~~Pin-read roles + orchestrator~~ DONE this pass (F31/F32 arbitrated)
2. Program concrete patches: **F56, F31, F41, F42** (BLOCKING/HIGH first)
3. Draft: F50, F52, F57, F59, then MEDIUM pack
4. Ship nothing
5. Locked response shape

Next pin URLs needed in channel for remaining surface (agent, human, tools, pricing, tracking).

---

## Gemini

W8/F12 four-part @ 6d25f3b still yours. Run cold.

## Boundaries

Orca ≠ BGM. Claude edits, ships nothing, holds no credentials.  
Grok lands, pushes, holds the broker.  
Gemini reads public mirror and reports.  
Fry owns roster, human gates, and token rotation.

**Night close 2026-08-22.** Nineteen confirmed real. Two BLOCKING open (F31, F56). Process improved — keep it.
