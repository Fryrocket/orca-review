# Orca Review Status — 2026-08-24

**Private SoT:** `Fryrocket/multi-agent-orchestration` @ `30290d95259bde980922508fe84b80de7a7d9fe3` (R11-F62/F63 + F37–F40 tests)  
**Orca ≠ BGM**

---

## This poll LANDED (2026-08-24)

| Packet | Disposition |
|--------|-------------|
| `TO_GROK_F62_F63_run_id_poisons_task_2026-08-24` | **LANDED** — `_ensure_run_id` no longer persists a throwaway id (tests were already on main; product was missing) |
| `TO_GROK_F37_F40_ntp_probe_audit_2026-08-24` | **CLOSED (AUDITED)** — no NTP defect; 7 tests exercise real `timedatectl` path |

Local pytest **140 passed** (128 prior + 5 F62 + 7 F37). ORCA_PROFILE unset.

---

## Closed this arc

HIGH: persist/dashboard, F31, F56, F41, F42, `_invoke` user=, F50, F52, F55 (audited), F57, F59, F32.

MEDIUM: **F54**, **F51**, **F53**, **F58**, **F62/F63**, **F37–F40** (audited).

---

## pytest

```
140 passed
ORCA_PROFILE unset at process level
```

---

## Still open

MEDIUM remaining: F43–F49, F60–F69. Draft next; do not silently close F1–F36.

Follow-up: `models.py::_pi_profile()`, `tools.py`, `tracking.py` still read `ORCA_PROFILE` independently. F60/F61 still needs a crisp finding (Claude flagged weak preflight, not a one-line bug).

Raw: https://raw.githubusercontent.com/Fryrocket/orca-review/main/mao/orchestrator.py
