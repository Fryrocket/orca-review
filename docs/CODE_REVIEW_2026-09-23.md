# ORCA local code review and regression report

Date: 2026-09-23, updated 2026-09-24. Reviewer/implementer: Codex consultant. Scope: the local tree at `/Users/fryrocket/claude-server/orca-rebuild`, including rebuilt `orca/`, retained `mao/`, both web interfaces, scripts, and all tests in `tests/` and `tests_v1/`. This implementation report is not itself independent approval; a separate QUENCH pass subsequently verified exact clean commit `9eb7638dc74f54da11a482a3b175b6a1d824af38` for local code, test, and recovery integrity only.

## Result

**516 tests pass: 273 rebuilt + 243 legacy.** The initial baseline was 332 passing tests. Review added 23 regression cases: the first batch reproduced 17 failures and the second reproduced six additional failures before fixes. Subsequent hardening and recovery work expanded the rebuilt suite further. Those 23 original regression cases are test cases, not 23 distinct vulnerabilities.

No existing set of 266 failing tests was reproduced. STATE's "Orca 266" is a historical deployed-code passing-test count. The origin of the user's "-266" display remains unconfirmed; do not reinterpret a diff counter as a test result.

## Reproduced defects fixed

| Area | Defect and correction | Evidence |
| --- | --- | --- |
| Credential handling | Values under named credential fields could persist when the value did not match a token-shaped regex. Redaction now handles normalized credential field names recursively. | `tests_v1/test_review_regressions.py` |
| Paused work | A pause boundary could prevent creation of a required approval; there was no explicit resume path, and terminal work could be reopened by pause. Approval creation now precedes pause, resume respects every active boundary and approval state, and terminal jobs stay terminal. Console/API expose authenticated Resume. | `tests_v1/test_review_regressions.py` |
| Permission input | Numeric equality admitted floating-point permission levels. Only integer or PermissionLevel input is now accepted. | `tests_v1/test_review_regressions.py` |
| Cloud/cost configuration | Truthy strings could masquerade as boolean approval flags. Configuration now requires real booleans and finite, nonnegative numeric caps. | `tests_v1/test_review_regressions.py` |
| Fleet replay protection | Re-enrolling the same key erased the last heartbeat nonce/time. Same-key enrollment now preserves the record and replay window. | `tests_v1/test_review_regressions.py` |
| Shared database accounting | Separate locks on one SQLite connection allowed a cost operation to join another operation's transaction. Evidence/control and costs now share the connection lock. | `tests_v1/test_review_regressions.py` |
| Read-only bot completion | ORCA/QUENCH R0 work could not complete because review separation always required write-author capability. Action-aware separation permits read-only work while retaining distinct author/reviewer identities and write restrictions. | `tests_v1/test_review_regressions.py` |
| Legacy network binding | Explicit LAN/tailnet hosts escaped checks applied only to wildcard binds. All non-loopback binds now require existing LAN opt-in plus token configuration. | `tests/test_legacy_review_regressions.py` |
| Legacy cost accounting | Derived negative/nonfinite costs and invalid saved ledger values could poison totals. Preflight, final cost, ledger writes, and saved rows now validate bounded numeric meaning. | `tests/test_legacy_review_regressions.py` |
| Legacy event delivery | An empty supplied MessageBus was falsey and silently replaced. The orchestrator now preserves the caller's bus unless it is None. | `tests/test_legacy_review_regressions.py` |
| Legacy recovery | A malformed non-dictionary metadata field could stop restoration. Invalid entries are skipped consistently with the existing recovery behavior. | `tests/test_legacy_review_regressions.py` |
| Legacy human approval gate | Browser requests lacked current-form request binding. The gate is loopback-only and now validates Host, exact routes, bounded bodies, and per-prompt CSRF tokens; prompt handling is serialized and timeout cleanup is improved. | `tests/test_web_gate_request_security.py`; existing HTML-injection tests retained |

## Validation evidence

- `.venv/bin/python -m pytest -q tests tests_v1`: **516 passed in 22.97s** on the 2026-09-24 QUENCH rerun, including extended HTTP Resume authentication and active-boundary checks. An intermediate extension initially expected HTTP 403 for a policy denial; inspection confirmed the existing API contract is 400. The test now verifies both that contract and the denial reason; no production behavior was weakened.
- `.venv/bin/python -m compileall -q orca mao scripts tests_v1 tests`: passed after permission to write bytecode caches was granted.
- `node --check orca/static/app.js`: passed.
- `node --check mao/web_ui/static/app.js`: passed.
- `git diff --check`: passed. This only checks tracked diffs; the test/compilation runs include the untracked rebuild source.
- `.venv/bin/python scripts/recovery_drill.py --report /tmp/quench-recovery-20260924.json`: passed during the 2026-09-24 QUENCH rerun; fresh-directory, no-dependency installation plus **273 passed in 8.45s**, schema v4, with a valid evidence chain.
- The QUENCH recovery report recorded test-database SHA-256 `9f2c033dae76181171ff252e57f90483e0c16967b3f2b151938fbaa01259d77b`.
- Browser connection inventory was empty. Static/HTTP tests and syntax checks do not establish rendered desktop/phone behavior.
- The two-page owner PDF was reopened, text/page-count/bounds checked, and both rendered pages visually inspected. The PDF generator also passed Python compilation.

## Remaining engineering and acceptance work

1. **Independent review:** the first 2026-09-24 QUENCH pass verified the local code, tests, and isolated reconstruction but correctly blocked release because no immutable commit existed. A subsequent pass verified exact clean commit `9eb7638dc74f54da11a482a3b175b6a1d824af38`. Production separation-of-duties acceptance still requires a trusted external verifier and evidence manifest.
2. **Production identity:** the local console's shared operator token is not independent cryptographic identity for each actor. Keep it local; implement reviewed per-identity authentication/authorization before remote or multi-user control.
3. **Fleet transport and lifecycle:** tests use simulated signed heartbeats. Live node readiness, key-rotation health invalidation, transport deployment, reboot/reconnect, and node-specific recovery remain unproven on ANVIL, FORGE, KILN, EMBER, and IRIS.
4. **Real integrations:** injected read adapters, provider action profiles, and a previous advisory connector drill are not production bot integrations. Build provider-specific paths, pagination/error handling, execution receipts, retries, and write gates before enabling them.
5. **Bot execution and quality:** actual autonomous model/tool runtimes remain disabled. Local model quality evaluations, scoped tool runners, cancellation, timeouts, and end-to-end failure handling still need acceptance. Cloud budget remains zero.
6. **Security evidence:** hash chains/state digests detect covered corruption, but are not an external trust anchor against an attacker able to rewrite the whole database. Stronger snapshot/deletion handling, signed provenance, live advisory checking, and real alert delivery remain work.
7. **Release recovery:** the successful drill rebuilds this working tree with synthetic state. It does not restore an approved release, production secrets, or live services. Complete that drill and a concrete rollback plan before cutover.
8. **Legacy boundary:** retained `mao` fixes improve the regression/rollback surface; they do not certify that old stack for new production use. Its pricing table is historical code data, not a verified current provider quote. Do not enable spend using it without revalidation.

## Owner checklist and boundaries

The printable checklist is `output/pdf/ORCA_action_checklist_2026-09-23.pdf`. It identifies only owner input/access/acceptance work. Engineering gaps above remain implementation work, not blanket requests for Fry to approve everything again.

No commit, push, PR, merge, deletion, deployment, secret rotation, external publication, or production change was performed in this review. Existing uncommitted changes and legacy trees were preserved. Previously exposed credentials should be replaced through the approved secret store before production use; their values are never evidence.
