# Claude → Grok programming handoff

## Claude (Editor)

1. Read raw files from this repo (not Drive Docs, not private GitHub).
2. **Program the fix** — full file body or clear unified diff.
3. Add/adjust tests with `pytest.raises(..., match=...)`.
4. Send the packet to Fry/Grok chat. Do not claim production is updated.

## Grok (Implementer)

1. Apply approved patches in private `multi-agent-orchestration`.
2. Run `pytest -v`; paste raw stdout.
3. Sync the same files back to **this** public mirror.
4. Reply with SHA + raw URLs.

## Fry

Approves scope. Owns merge. Separates Orca runtime secrets from this mirror (there are none here).
