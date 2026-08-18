# orca-review (PUBLIC)

**Purpose:** Review channel for [Orca](https://github.com/Fryrocket/multi-agent-orchestration) so Claude can read **raw source** without private-repo auth or Drive Doc conversion.

**Orca ≠ BGM.** This mirror holds only review-surface files. No API keys. No secrets. Not a pip-installable package.

Current sync: **v0.5.10** matching private `c3ee067920b4adda15a9e77331e9c8f4add20b24` (reconciled 2026-08-18; Claude F1–F9 already landed in private).

## Roles

| Role | Who | Does |
|------|-----|------|
| **Editor** | Claude | Reads raw files here, writes proposals / patches / tests |
| **Implementer** | Grok | Applies approved changes in private `multi-agent-orchestration` |
| **Owner** | Fry | Approves scope and merges |

## Workflow (locked)

1. **Grok** syncs the files under review into this public repo (raw `.py`, real indentation).
2. **Claude** reviews via raw URLs or clone — cites path + function / line intent.
3. **Claude programs the fix** as concrete patch text or full file replacement (not vague asks only).
4. Fry approves (or adjusts).
5. **Grok implements** in the private repo, runs `pytest -v`, syncs this mirror again.

Claude does **not** push to private repos and does **not** ship production. Editor proposes + codes; Implementer lands.

## Raw file URLs (always prefer these)

Base: `https://raw.githubusercontent.com/Fryrocket/orca-review/main/`

**Core**

- `mao/tools.py`
- `mao/roles.py`
- `mao/cost_store.py`
- `mao/tracking.py`
- `mao/errors.py`
- `mao/pricing.py`
- `mao/scheduler_ntp.py`

**Product wiring (v0.5.10)**

- `mao/orchestrator.py`
- `mao/models.py`
- `mao/human.py`
- `mao/scheduler.py`
- `mao/web_ui/auth.py`
- `mao/web_ui/server.py`
- `mao/web_ui/static/app.js`
- `mao/web_ui/static/index.html`

**Tests**

- `tests/test_round6.py`
- `tests/test_product.py`
- `tests/test_privileges.py`

**Handoff**

- `TO_CLAUDE.md`
- `STATUS.md`
- `ROUND7_DISPOSITION.md` (accepted, not landed — needs clean `.py`)

## For Claude — how to send work to Grok

Reply in this shape:

```
TO: Grok (Implementer)
FROM: Claude (Editor)
RE: <topic>

## Review of <path>
- finding…

## Patch / full file
```python
# complete replacement or unified diff
```

## Tests to add
```python
# pytest
```

## Disposition
DONE / DEFERRED / REJECTED per item
```

Grok will implement only what Fry green-lights.
