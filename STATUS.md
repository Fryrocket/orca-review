# Orca Review Status — 2026-08-25

**Private SoT:** `Fryrocket/multi-agent-orchestration` @ `62aeb4e17ca9ae4dc45b6268ba94b1d93bbd823f` (R11-F85)  
**Orca ≠ BGM**

---

## This poll LANDED (2026-08-25)

| Packet | Disposition |
|--------|-------------|
| Claude F85 (`/api/turn/end` strips standing grants) | **LANDED** — `_restore_standing_grants()` after `end_turn()`; `/api/turn/start` and `/api/turn/end` serialize on `_run_lock` |

Local pytest **227 passed** with `ORCA_PROFILE` unset (225 + F85×2). F85 tests also green under `ORCA_PROFILE=test`. Pre-existing F79 approve test still fails isolated under `ORCA_PROFILE=test` (not F85). Do not re-file F70–F85.

Claude is Editor. Gemini paused.

---

## Closed this arc

HIGH + MEDIUM original pack complete through F70. New: F71–F85. R11-CF1 is Cloudflare lane, not Orca git.

---

## pytest

```
227 passed
ORCA_PROFILE unset at process level — 227 passed
F85 tests — pass with ORCA_PROFILE unset and ORCA_PROFILE=test
```

---

## Still open

None from the original HIGH + MEDIUM pack. New findings only (F86+).

Raw server.py: https://raw.githubusercontent.com/Fryrocket/orca-review/main/mao/web_ui/server.py
F85 tests: https://raw.githubusercontent.com/Fryrocket/orca-review/main/tests/test_f85_dashboard_turn_end_strips_grants.py
