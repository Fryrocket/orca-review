# Orca Review Status — 2026-08-23

**Private SoT:** `Fryrocket/multi-agent-orchestration` @ `15fb3745f6ecaf1f0ddcefa0038daf0c7728ceff` (persist onto guarded blackboard)  
**Prior scheduler pin:** `7dd98527dc9ee5f2466be868b22309fef8d1e8e7`  
**Orca ≠ BGM**

---

## Answered (Claude 2026-08-23)

`mao/memory.py` **does exist on private main**. It is the legacy ungated store (`set` / `author` / `MemoryEntry`). It is **not** the Round-7 board.

The live board is `mao/blackboard.py` (`commit` / `writer` / `BoardEntry`, guard required). `persist.py` and `web_ui/server.py` were still wired to `mao.memory`, which is why the public mirror could not import them (memory.py is not on the review surface) and why the dashboard constructed `Blackboard()` with no guard.

Landed this pass:

- `mao/persist.py` uses `blackboard.Blackboard`; `load_blackboard` requires a pre-constructed guarded board; `save_bus` uses `bus.history()`
- `mao/web_ui/server.py` uses guarded `blackboard.Blackboard`, `cost_guard=UsageTrackerCostGuard`, `bus.history()` / `msg_id`, `publish(sender, content, topic=...)`, `run_sequential(..., human_approved=)`

`mao/memory.py` is left on private main for now (examples still import it). It is not synced to the mirror.

---

## Already landed earlier today (private + mirror)

| ID | Status |
|----|--------|
| R11-F31 | CLOSED — `SENSITIVE_GRANTS` includes WRITE + ORCHESTRATE |
| R11-F56 | CLOSED — `run_sequential` no longer swallows `OrcaError` |
| R11-F41 | CLOSED — `_fire` re-raises `FATAL_ERRORS`, disables job, stops loop |
| R11-F42 | CLOSED — `max_catch_up_sec` re-anchor + monotonic jump detector |
| `_invoke` user= | CLOSED — `model.complete(user=...)` + `ModelResponse` + tool schemas |

---

## pytest (this machine, 2026-08-23)

```
84 passed
ORCA_PROFILE unset at process level (env fixture still sets ORCA_PROFILE=test on some product tests — see F55)
```

Suite: `tests/test_product.py` `tests/test_wiring_round7.py` `tests/test_privileges.py` `tests/test_round6.py` `tests/test_persist_dashboard.py`

---

## Still open

| ID | Status | Summary |
|----|--------|--------|
| R11-F32 | PARTIAL | enforce default fail-closed good; still applies grant when unenforced; status exposes bypass |
| R11-F50 | OPEN | ORCA_PROFILE=dev/test silently disables enforcement |
| R11-F52 | OPEN | string privileges bypass set ops via str-Enum hashing |
| R11-F55 | OPEN | privilege tests may be vacuous if ORCA_PROFILE=test |
| R11-F57 | OPEN | run_sequential still forges human_approved when gate missing |
| R11-F59 | OPEN | string-returning adapters bill $0 forever |

MEDIUM / LOW pack F37–F40, F43–F49, F51, F53, F54, F58, F60–F69 still entered, not silently closed.

---

## Boundaries

Claude edits, ships nothing, holds no credentials.  
Grok lands, pushes, holds the broker.  
Gemini reads public mirror and reports.  
Fry owns roster, human gates, and token rotation.

Raw base: `https://raw.githubusercontent.com/Fryrocket/orca-review/main/`
