# orca-review (PUBLIC)

**Purpose:** Review channel for [Orca](https://github.com/Fryrocket/multi-agent-orchestration) so Claude can read **raw source** without private-repo auth or Drive Doc conversion.

**Orca ≠ BGM.** This mirror holds only review-surface files. No API keys. No secrets. Not a pip-installable package.

Current sync: **v0.5.12** (Round-7 + R11) from private `multi-agent-orchestration` main.

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

**Core (v0.5.12)**

- `mao/__init__.py`
- `mao/orchestrator.py`
- `mao/models.py`
- `mao/tools.py`
- `mao/roles.py`
- `mao/errors.py`
- `mao/costguard.py`
- `mao/cost_store.py`
- `mao/tracking.py`
- `mao/pricing.py`
- `mao/human.py`
- `mao/blackboard.py`
- `mao/bus.py`
- `mao/agent.py`
- `mao/scheduler.py`
- `mao/scheduler_ntp.py`
- `mao/web_ui/auth.py`

**Tests**

- `tests/test_privileges.py`
- `tests/test_product.py`

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
