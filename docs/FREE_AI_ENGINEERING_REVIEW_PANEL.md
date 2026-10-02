# ORCA Free AI Engineering Review Panel

Status: local framework implemented; external account authorization pending.

## Purpose

ORCA uses several independent reviewers because agreement between language models is not proof. Deterministic checks, official specifications, reproducible calculations and later physical measurements remain the evidence. No AI reviewer can release hardware for fabrication by itself.

## Reviewer assignments

| Reviewer | Assignment | Operating rule |
|---|---|---|
| Qwen on CRUCIBLE | Challenge calculations, ratings, startup states and failure modes | Local, private, advisory |
| ANVIL Reflex | Fast contradiction and missing-field scan | Local, private, advisory |
| QUENCH | Reproduce cited checks and adjudicate confirmed findings | Local, private, required software gate |
| Gemini Developer API free tier | Structured electrical, standards and manufacturability review | Sanitized packet only; free tier only; never a paid fallback |
| Claude Free | Skeptical design-review chair and failure-mode critic | Optional owner-authenticated browser review; never blocks autonomous work |
| GitHub Copilot Free | Generator, validator, firmware and test-code review | Source subset only; free allowance only; additional usage disabled |

Flux and all paid trials or overage paths are excluded.

## A-to-Z flow

1. ORCA freezes and hashes the candidate revision.
2. ORCA runs deterministic schematic, PCB, netlist, fabrication and source-equivalence checks.
3. ORCA creates one sanitized review packet containing file hashes, bounded claims, official sources and reviewer-specific checklists. It contains no credentials, live configuration or customer data.
4. Local Qwen and ANVIL reviewers independently challenge the packet.
5. Gemini reviews the same packet using a strict JSON schema when its dedicated free-tier key is available.
6. Claude Free and Copilot Free may add quota-dependent advisory reviews when their owner-authenticated sessions are available.
7. ORCA rejects malformed responses and separates unsupported hypotheses from evidence-backed findings.
8. ORCA reproduces cited defects, deduplicates them by evidence fingerprint and sends confirmed findings to QUENCH.
9. QUENCH issues `pass`, `review` or `block` for the software/design gate. It cannot claim physical evidence.
10. ORCA repairs the candidate and repeats from a new frozen revision until the software/design gate passes.
11. Manufacturing remains blocked until mechanical fit, electrical bench tests and thermal soak produce checksum-bound physical evidence.

## One-time owner setup

- Gemini: create a dedicated free-tier API key and place it in ORCA's keychain broker. Do not attach billing or enable paid fallback. Google states that free-tier content may be used to improve its products, so only the sanitized packet may leave ORCA.
- Claude Free: sign in once in ORCA's governed browser profile. CAPTCHA, quota limits and session expiry are normal non-blocking conditions; ORCA never scrapes or stores the session secret.
- GitHub Copilot Free: restore GitHub authentication and enable Copilot Free. Keep the monthly allowance capped and additional usage disabled.

Account absence or quota exhaustion never stops ORCA's local review path.

Before every autonomous review, ORCA health-checks each reviewer and its official authentication route. Persistent secrets are requested only through the keychain broker. An expired browser session, revoked key or exhausted free quota marks that reviewer degraded, creates an owner notification and continues the local evidence path; ORCA never pauses unattended work on an interactive sign-in screen and never buys additional usage.

## Sources

- [Gemini Developer API pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Gemini API terms and unpaid-service data policy](https://ai.google.dev/gemini-api/terms)
- [Gemini structured output](https://ai.google.dev/gemini-api/docs/structured-output)
- [Claude plan comparison](https://support.anthropic.com/en/articles/11049762-choosing-a-claude-ai-plan)
- [GitHub Copilot individual plans](https://docs.github.com/en/copilot/managing-copilot/managing-copilot-as-an-individual-subscriber/getting-started-with-copilot-on-your-personal-account/about-individual-copilot-plans-and-benefits)
- [Copilot CLI session limits](https://docs.github.com/en/copilot/how-tos/copilot-cli/use-copilot-cli/set-session-limit)
- [Raspberry Pi HAT+ specification](https://datasheets.raspberrypi.com/hat/hat-plus-specification.pdf)
