# ORCA independent security gate — threat model and acceptance criteria

Date: 2026-09-23
Status: Local advisory prototype; not deployed or enforcement-enabled

## Boundary

The independent security gate examines text artifacts supplied by an already
registered ORCA identity. It is deterministic and tool-free: it does not read
repositories, call connectors, invoke a model, run code, install dependencies,
approve work, merge, deploy, spend, publish, or expose credentials.

The gate is separate from QUENCH. It reports security findings for ORCA and
QUENCH to evaluate; it cannot complete a technical review or decide an R2/R3
approval. Its `block_and_escalate` disposition is advisory until Fry explicitly
approves a separately reviewed enforcement design.

## Protected assets and threat assumptions

- Secret values and credential metadata must not appear in reports or evidence.
- Source, configuration, container, network, and infrastructure artifacts must
  not silently acquire high-risk defaults.
- Author, reviewer, approver, and deployer separation must remain intact.
- Findings and disposition must be reproducible and persisted in the evidence
  chain without storing complete submitted artifacts. Schema-v2 state digests
  bind persisted security records to a referenced evidence head.
- Dependency and supply-chain trust is in scope. The scanner detects unsafe
  supplied manifests/configuration, but package advisory lookup, cryptographic
  lock/signature verification, and live provenance validation remain future work.
- The scanner input is untrusted text. It is data, never executable instruction.

## Deterministic checks in prototype v2

| Check | Severity | Advisory disposition |
| --- | --- | --- |
| Secret-shaped value | S3 | Block and escalate |
| Privileged container mode | S2 | Block and escalate |
| Disabled TLS verification | S2 | Block and escalate |
| `chmod 777` | S2 | Block and escalate |
| Download piped directly to a shell | S2 | Block and escalate |
| Remote Docker `ADD` | S2 | Block and escalate |
| Mutable CI action branch reference | S2 | Block and escalate |
| Workflow `write-all` permissions | S2 | Block and escalate |
| Explicitly disabled branch protection | S2 | Block and escalate |
| Empty/disabled required status checks | S2 | Block and escalate |
| Wildcard network bind | S1 | Review |
| Container `:latest` tag | S1 | Review |
| Unpinned Python requirement | S1 | Review |
| Dependency manifest without supplied same-directory lockfile | S1 | Review |

Evidence excerpts are bounded and redacted before persistence. Findings contain
a stable SHA-256 fingerprint, severity, summary, and remediation guidance.

## Acceptance criteria

1. Unknown authors and lanes fail closed; the gate cannot review its own work.
2. No finding, report, event, or snapshot contains a detected secret value.
3. Any S2 or S3 finding recommends `block_and_escalate`; S1 recommends
   `review`; a clean scan returns `pass`.
4. The security-gate identity has no author, review, approval, tool, model,
   merge, or deployment authority.
5. Reports survive a local control-plane restart and the evidence hash chain
   remains valid.
6. Automated tests cover detection, redaction, authority boundaries, and
   persistence.
7. Scans accept at most 64 artifacts, 256,000 UTF-8 bytes per artifact, and
   1,000,000 bytes total. Artifact names are capped at 240 characters, and
   NUL-containing names or content fail closed.
8. QUENCH or Fry may adjudicate a finding independently. A Fry-only exception
   is record-only, time-bounded, requires a current confirmed QUENCH review,
   never changes job state, and is prohibited for S3.

## False positives and break-glass

- Findings are immutable evidence; a later adjudication does not erase them.
- `confirmed` and `false_positive` reviews require QUENCH or Fry, an evidence
  note, and an identity different from the report author.
- S2 record-only exceptions expire within 60 minutes; S1 exceptions expire
  within 24 hours. Only Fry may record one after a confirmed QUENCH review.
- S3 findings cannot receive an exception. No exception enables a tool,
  connector write, merge, deployment, job transition, or enforcement bypass.

## Gates before enforcement or deployment

- Define repository and infrastructure scope for each lane.
- Add reviewed package-advisory lookup, cryptographic lock/signature validation,
  and live repository/provenance verification without weakening the local checks.
- Independently review and adversarially test the implemented adjudication and
  record-only break-glass policy.
- Define issue/status-check and alert routing without enabling connector writes.
- Complete adversarial evaluation and independent QUENCH review.
- Obtain explicit Fry approval for any blocking enforcement, connector write,
  deployment, credential access, or production integration.
