# Orca Review Status — 2026-08-22

**Mirror tip:** `260b78c6ee42b05afcd7236252726608fecbd914`  
**Core content pin:** `6d25f3ba48ff663265f82f0ca8cd36d46466aed0` (v0.5.12 Round-7 + R11)

## Closed / Verified

| ID | Status | Pin |
|----|--------|-----|
| R8-F1 | CLOSED | 6d25f3b errors.py hierarchy |
| R8-F3 | CLOSED | 6d25f3b require_ntp_or_refuse(stage=) |
| A14 | VERIFIED (call sites) | 6d25f3b scheduler.py start()+_fire() |
| W8/F12 | CLOSED PENDING MIRROR CONFIRMATION | Gemini independent four-part still required |

Arithmetic: **2 closed** on pinned evidence this pass. W8/F12 pending Gemini.

## New findings entered (Claude pinned read of scheduler.py)

| ID | Sev | Summary |
|----|-----|--------|
| R11-F41 | HIGH | _fire swallows FATAL_ERRORS; job re-arms |
| R11-F42 | HIGH | Clock-jump / backlog storm on Pi 5 |
| R11-F43 | MED | NTP-refused fire still counted + silent |
| R11-F44 | MED | Corrupt next_run permanent silent skip |
| R11-F45 | MED | Non-atomic jobs.json; unguarded load |
| R11-F46 | MED | Zombie-thread after stop() timeout |
| R11-F47 | L/M | timedatectl every fire; no TTL |
| R11-F48 | LOW | list() returns live Job objects |
| R11-F49 | LOW | start() NTP before already-running return |

F37–F40 confirmed LOW (fail-closed).

## BLOCKING (until fixed or dispositioned)

- **R11-F31** SENSITIVE_GRANTS omits WRITE / ORCHESTRATE
- **R11-F32** enforce=False applies grants without sensitive check

F1–F36 not silently closed; not re-arbitrated at 6d25f3b this session except as noted.

## Test file

```
tests/test_round7.py  NOT LANDED
  Superseded by tests/test_wiring_round7.py (8 real-wiring tests).
  Mirrored at 260b78c.
```

## Still open

- pytest post-land (never run this arc for 0.5.12)
- R11-F6/F7/F8/F23 clean-.py cut — Fry go/no-go
- CF items with Fry
- Gemini W8/F12 independent run
- Coverage delta wiring vs prior fakes suite

## Claude orders (active)

1. Pin-read roles.py + orchestrator.py @ 6d25f3b → arbitrate F31/F32
2. Program concrete patches for F41 + F42 (HIGH)
3. Draft patches F43–F46 (MED)
4. Ship nothing
5. Locked response shape (TO/FROM/RE + Review + Patch + Tests + Disposition)

## Gemini

Four-part W8/F12 at 6d25f3b — still yours. Run cold.

## Boundaries

Orca ≠ BGM. Claude edits, ships nothing. Grok lands. Gemini reports. Fry owns gates.
