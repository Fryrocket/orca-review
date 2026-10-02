from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Iterable, Mapping


SUPPORTED_EVIDENCE = frozenset({
    "official_specification", "manufacturer_datasheet", "calculation",
    "simulation", "kicad_erc", "kicad_drc", "netlist_check",
    "source_code", "automated_test", "physical_measurement",
})


@dataclass(frozen=True)
class ReviewerProfile:
    id: str
    name: str
    duty: str
    transport: str
    cost_policy: str
    data_policy: str
    owner_setup: str
    availability_policy: str
    automated: bool
    release_authority: bool = False


REVIEWERS = {
    "qwen_challenger": ReviewerProfile(
        "qwen_challenger", "Qwen on CRUCIBLE",
        "challenge assumptions, calculations, component choices and failure modes",
        "local ORCA model route", "local-only; no usage charge",
        "private local processing", "already installed; runtime acceptance remains governed",
        "service health-checked; no interactive sign-in",
        True),
    "quench": ReviewerProfile(
        "quench", "QUENCH",
        "independent evidence adjudication and final software/design-gate recommendation",
        "local KILN model route", "local-only; no usage charge",
        "private local processing", "already installed",
        "service health-checked; no interactive sign-in",
        True, True),
    "anvil_reflex": ReviewerProfile(
        "anvil_reflex", "ANVIL Reflex",
        "small-model contradiction and missing-field smoke check",
        "local Ollama", "local-only; no usage charge",
        "private local processing", "already installed",
        "local runtime health-checked; no interactive sign-in",
        True),
    "gemini_free": ReviewerProfile(
        "gemini_free", "Gemini Developer API free tier",
        "structured electrical, standards and manufacturability second opinion",
        "official Gemini API with JSON Schema output",
        "free-tier only; billing fallback prohibited",
        "sanitized public engineering packet only; unpaid-service content may be used by Google to improve products",
        "owner creates a dedicated API key and stores it in the ORCA keychain broker",
        "credential-broker preflight; persistent until provider revocation or quota exhaustion",
        True),
    "claude_free": ReviewerProfile(
        "claude_free", "Claude Free",
        "optional adversarial failure-mode and requirements review",
        "owner-authenticated governed browser session",
        "free account only; no API or subscription",
        "sanitized packet only; browser session is never a secret store",
        "owner signs in once; CAPTCHA, quota and session expiry remain non-blocking",
        "session preflight; degrade and notify on expiry because perpetual login is not guaranteed",
        False),
    "copilot_free": ReviewerProfile(
        "copilot_free", "GitHub Copilot Free",
        "generator, validator, firmware and test-code review only",
        "owner-authenticated official GitHub Copilot CLI or GitHub web chat",
        "free allowance only; additional usage disabled",
        "source subset only; no secrets, credentials or live configuration",
        "owner repairs GitHub authentication and enables Copilot Free",
        "official-auth preflight; degrade and notify on expiry or free-quota exhaustion",
        False),
}


REVIEW_STAGES = (
    "freeze and hash the candidate design",
    "build a sanitized evidence packet",
    "run deterministic KiCad, netlist, fabrication and source checks",
    "run local Qwen challenge and ANVIL smoke review",
    "run Gemini structured review when its free key is configured",
    "offer Claude Free and Copilot Free as quota-dependent advisory reviews",
    "validate citations and reproduce every claimed defect",
    "deduplicate findings by evidence fingerprint",
    "send confirmed findings to QUENCH for independent disposition",
    "repair the design and repeat from the frozen candidate",
    "block manufacturing until physical fit, bench and thermal evidence pass",
)


def review_panel_plan() -> dict:
    """Describe ORCA's no-cost review panel without reading any credentials."""

    return {
        "schema": 1,
        "status": "implemented_local_external_auth_pending",
        "free_only": True,
        "paid_fallback": False,
        "excluded": ["Flux AI", "paid API tiers", "consumer-session scraping"],
        "reviewers": [asdict(REVIEWERS[key]) for key in REVIEWERS],
        "stages": list(REVIEW_STAGES),
        "evidence_rule": (
            "An AI statement is advisory until tied to a supported source and reproduced."
        ),
        "supported_evidence": sorted(SUPPORTED_EVIDENCE),
        "manufacturing_release": "always requires physical evidence",
        "autonomy": {
            "required_local_path": ["qwen_challenger", "quench", "anvil_reflex"],
            "external_preflight": True,
            "interactive_prompt_during_run": False,
            "on_auth_or_quota_failure": "mark reviewer degraded, notify owner, continue local evidence path",
            "credential_storage": "ORCA keychain broker; never chat, logs or bot memory",
        },
    }


def reviewer_prompts() -> dict[str, str]:
    common = (
        "Review only the supplied frozen engineering packet. Do not infer tests that are "
        "not present. Return JSON with summary, findings, uncertainty and next_gate. Every "
        "finding must include severity, category, claim, evidence_type, source_reference, "
        "and reproducible_check. Mark unsupported concerns as hypotheses."
    )
    return {
        "qwen_challenger": common + (
            " Challenge calculations, component ratings, startup states, GPIO protection, "
            "single-fault behavior and contradictory assumptions. Do not approve."),
        "quench": common + (
            " Independently reproduce cited checks, reject unsupported findings, and issue "
            "pass, review or block. You may not author the design."),
        "anvil_reflex": common + (
            " Perform a bounded missing-field, mismatch and contradiction scan only."),
        "gemini_free": common + (
            " Focus on official Raspberry Pi HAT+, four-wire PWM fan, component datasheet, "
            "netlist, fabrication and manufacturability requirements."),
        "claude_free": common + (
            " Act as a skeptical design-review chair. Focus on hidden assumptions, failure "
            "modes, test coverage and claims that exceed the evidence."),
        "copilot_free": common + (
            " Review only generator, firmware and validator source. Look for mismatches "
            "between schematic, PCB, BOM, tests and reported acceptance."),
    }


def build_review_packet(*, project_id: str, candidate_files: Mapping[str, str],
                        claims: Iterable[str], public_sources: Iterable[str]) -> dict:
    if not project_id or len(project_id) > 96:
        raise ValueError("project id is invalid")
    if not candidate_files or len(candidate_files) > 64:
        raise ValueError("candidate file count is outside the bounded range")
    claim_list = list(claims)
    source_list = list(public_sources)
    files = []
    for name, content in sorted(candidate_files.items()):
        path = Path(name)
        if path.name != name or path.suffix not in {
                ".md", ".json", ".csv", ".py", ".kicad_sch", ".kicad_pcb", ".rpt"}:
            raise ValueError("review packet contains a disallowed file name")
        if not isinstance(content, str) or len(content.encode()) > 1_000_000:
            raise ValueError("review packet file is not bounded text")
        lowered = content.casefold()
        if any(marker in lowered for marker in (
                "private key", "api_key=", "apikey=", "authorization: bearer",
                "password=", "access_token=", "refresh_token=")):
            raise ValueError("review packet may contain a secret")
        files.append({
            "name": name, "bytes": len(content.encode()),
            "sha256": sha256(content.encode()).hexdigest(),
        })
    if not claim_list or len(claim_list) > 32:
        raise ValueError("review claims are outside the bounded range")
    if not source_list or len(source_list) > 32:
        raise ValueError("review sources are outside the bounded range")
    packet_seed = json.dumps({
        "project_id": project_id, "files": files,
        "claims": claim_list, "sources": source_list,
    }, sort_keys=True, separators=(",", ":"))
    return {
        "schema": 1,
        "project_id": project_id,
        "packet_sha256": sha256(packet_seed.encode()).hexdigest(),
        "privacy": "sanitized engineering evidence; no credentials or live configuration",
        "files": files,
        "claims_to_verify": claim_list,
        "public_sources": source_list,
        "review_prompts": reviewer_prompts(),
        "reviewers": [asdict(REVIEWERS[key]) for key in REVIEWERS],
        "physical_results_claimed": False,
    }


def reconcile_findings(findings: Iterable[Mapping[str, object]]) -> dict:
    """Accept only evidence-backed findings and deterministically deduplicate them."""

    confirmed, hypotheses, rejected = {}, [], []
    for raw in findings:
        required = {"reviewer", "severity", "category", "claim", "evidence_type",
                    "source_reference", "reproducible_check"}
        if not isinstance(raw, Mapping) or not required <= set(raw):
            rejected.append({"reason": "invalid_schema"})
            continue
        row = {key: str(raw[key]).strip() for key in required}
        if any(not value or len(value) > 2_000 for value in row.values()):
            rejected.append({"reason": "invalid_field"})
            continue
        seed = "|".join((row["category"].casefold(), row["claim"].casefold(),
                         row["source_reference"].casefold()))
        row["fingerprint"] = sha256(seed.encode()).hexdigest()
        if row["evidence_type"] not in SUPPORTED_EVIDENCE:
            row["status"] = "hypothesis_unproven"
            hypotheses.append(row)
            continue
        row["status"] = "confirmed_pending_quench_disposition"
        confirmed.setdefault(row["fingerprint"], row)
    return {
        "schema": 1,
        "confirmed": list(confirmed.values()),
        "hypotheses": hypotheses,
        "rejected": rejected,
        "next_gate": "quench_disposition" if confirmed else "none",
        "manufacturing_release": False,
    }
