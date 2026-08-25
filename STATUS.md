# Orca Review Status — 2026-08-25

**Private SoT:** `Fryrocket/multi-agent-orchestration` @ `e7c60cc9b53b54f08cd1858a4b66a470ea942a61` (R11-F84)  
**Orca ≠ BGM**

---

## This poll LANDED (2026-08-25)

| Packet | Disposition |
|--------|-------------|
| Claude F84 (dashboard `/api/run` strips standing grants) | **LANDED** — `_run_lock` serializes `/api/run`; `_standing_grants` restored after each run; `/api/revoke` still sticks |

Local pytest **225 passed** with `ORCA_PROFILE` unset (222 + F84×3). F84 tests also green under `ORCA_PROFILE=test`. Pre-existing F79 approve test still fails isolated under `ORCA_PROFILE=test` (not F84). Do not re-file F70–F84.

Claude is Editor. Gemini paused.

---

## Closed this arc

HIGH + MEDIUM original pack complete through F70. New: F71–F84. R11-CF1 is Cloudflare lane, not Orca git.

---

## pytest

```
225 passed
ORCA_PROFILE unset at process level — 225 passed
F84 tests — pass with ORCA_PROFILE unset and ORCA_PROFILE=test
```

---

## Still open

None from the original HIGH + MEDIUM pack. New findings only (F85+).

Raw server.py: https://raw.githubusercontent.com/Fryrocket/orca-review/main/mao/web_ui/server.py
F84 tests: https://raw.githubusercontent.com/Fryrocket/orca-review/main/tests/test_f84_dashboard_run_grant_survives.py
