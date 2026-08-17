# TO: Claude (Editor)

FROM: Grok (Implementer), via Fry  
RE: Your programming channel is open  
DATE: 2026-08-16

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
- https://raw.githubusercontent.com/Fryrocket/orca-review/main/tests/test_round2.py

## Your job (expanded)

1. Review the raw files.
2. **Program the fixes** — full file bodies or unified diffs, plus tests with `match=`.
3. Send the packet to Fry/Grok in chat.

## Grok’s job

Implement your approved patches in the private repo, run pytest, re-sync this mirror.

## Fry’s job

Approve scope.

You still ship nothing to production. You **do** write the code that Grok lands.

— Grok
