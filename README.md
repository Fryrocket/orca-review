# ORCA rebuild workspace

The new policy-first implementation lives in [`orca/`](orca/) with its specification in [`docs/REBUILD_SPEC.md`](docs/REBUILD_SPEC.md). The historical `mao/` package remains temporarily as a rollback and regression-reference surface; it is not the architecture of the rebuilt control plane.

Run the new tests:

```sh
python -m pytest tests_v1
```

Run the retained legacy regressions together with the rebuilt suite:

```sh
python -m pytest tests tests_v1
```

Run the local operator console:

```sh
python -m orca --host 127.0.0.1 --port 8787 --database orca-events.db
```

For identity-bound mutations, provide an owner-only JSON credential file from
the host secret system and select the matching identity in the console:

```sh
chmod 600 /path/to/orca-identities.json
ORCA_IDENTITY_TOKEN_FILE=/path/to/orca-identities.json python -m orca \
  --host 127.0.0.1 --port 8787 --database orca-events.db
```

The file is a JSON object mapping registered identity IDs (`fry`, `orca`,
`smith`, `quench`, or `security_gate`) to unique 32–512 character bootstrap
tokens. Token values are held in memory as digests and are never written to
ORCA state or evidence. The older `ORCA_OPERATOR_TOKEN` mode remains available
for loopback-only compatibility, but is bound to Fry, requires the same
idempotency/revision envelope, and cannot be combined with identity mode.

The console binds to loopback, rejects non-local Host headers, requires a 32–512-character runtime token before POST mutations are enabled, validates bounded JSON objects, and emits restrictive browser security headers. Integrity failures make state and health unavailable. Connector writes are disabled. Push, merge, deployment, remote execution, publication, spend, deletion, secrets, cutover, and production impact are Fry-only R3. No secret belongs in the database, UI, logs, repository, Drive, Notion, or Linear.

The Fleet view inventories ANVIL, FORGE, KILN, EMBER and IRIS. Fry-only key-fingerprint enrollment, signed heartbeat freshness/nonces, inter-process nonce locking, replay defense, key-rotation invalidation, stale-contact pause, and scoped transport/command validation are implemented and tested for every node. Node-targeted work fails closed while health is unproven. This is control-plane state only: remote execution is disabled and live node health remains unproven until authenticated probes and independent review occur.

The local build also includes an advisory-only deterministic security gate with
secret, configuration, dependency, provenance, and supplied repository-control
checks; append-only/hash-chained evidence; schema-v4 state/evidence integrity and
receipt-set omission detection with cross-connection snapshot reads; persistent incident and retention state; a
zero-spend budget; per-identity loopback authentication with actor binding;
atomic idempotency receipts and expected-revision mutation guards; bounded
connector responses; one canonical, redacted notification outbox with durable
pre-provider attempt reservations, explicit unconfirmed outcomes, and unlocked
sequential injected transports; secure
restart-safe heartbeat nonces; an explicit offline maintenance ticker; a
read-only structural preflight that cannot authenticate local evidence or grant
release readiness; and an isolated no-dependency recovery
drill. Browser mutations reuse the exact same envelope once after uncertain
transport failure. The rebuilt suite passes 273 tests and the combined
legacy-plus-rebuild corpus passes 516. Bot model/tool runtimes, live notification
delivery, connector writes, live advisory/signature lookup, autonomous scheduling,
and autonomous enforcement remain disabled.

The September 23 code review added 23 regression cases and fixed the reproduced defects, including approval-preserving resume, credential-field redaction, heartbeat replay protection, strict cost/configuration validation, and legacy approval-form request protection. See [`docs/CODE_REVIEW_2026-09-23.md`](docs/CODE_REVIEW_2026-09-23.md) for evidence and remaining limits. These are local checks, not independent review or production acceptance.

---

# Legacy orca-review (PUBLIC)

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
