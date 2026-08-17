# TO: Claude (Editor)

FROM: Grok (Implementer), via Fry  
RE: Round-6 green — programming channel open  
DATE: 2026-08-16 / 2026-08-17 UTC

## What changed

Public review mirror: **https://github.com/Fryrocket/orca-review**

You can fetch **raw** source (no private auth, no Drive Doc conversion):

- https://raw.githubusercontent.com/Fryrocket/orca-review/main/mao/tools.py
- https://raw.githubusercontent.com/Fryrocket/orca-review/main/mao/roles.py
- https://raw.githubusercontent.com/Fryrocket/orca-review/main/mao/cost_store.py
- https://raw.githubusercontent.com/Fryrocket/orca-review/main/mao/tracking.py
- https://raw.githubusercontent.com/Fryrocket/orca-review/main/mao/errors.py
- https://raw.githubusercontent.com/Fryrocket/orca-review/main/mao/pricing.py
- https://raw.githubusercontent.com/Fryrocket/orca-review/main/mao/scheduler_ntp.py
- https://raw.githubusercontent.com/Fryrocket/orca-review/main/tests/test_round6.py

## Round-6 results

**45 passed.** Every `pytest.raises` carries `match=`. No env mutation outside monkeypatch. Fail-closed invariants held:

- OrcaError hierarchy (never swallowed by RuntimeError/ValueError)
- Sensitive grants require HumanGate from Fry
- Turn isolation + end_turn full revoke (no orphan grants)
- Partial revoke clears stale human_approved flag
- UNCLASSIFIED is a true ungrantable sentinel
- Path audit: positional / **kwargs flatten / custom path_params / *args refused at register / BGM resolved-path / mao/ blocked / allowlist
- Cost: posted vs unposted, construction fails on missing ORCA_REPO_ROOT, clock jump guards, kill switch
- Pricing: normalize + stale-table refuse
- NTP A14: stage= in message, re-check before fire

## Your job

1. Review the raw files + the 45-test suite.
2. **Program the next fixes** if any — full file bodies or unified diffs, plus tests with `match=`.
3. Send the packet to Fry/Grok in chat.

## Grok’s job

Implement your approved patches in the private repo, re-run pytest, re-sync this mirror.

## Fry’s job

Approve scope / HumanGate.

You still ship nothing to production. You **do** write the code that Grok lands.

— Grok
