from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping


@dataclass(frozen=True)
class CrucibleAcceptance:
    """Evidence required before CRUCIBLE may enter an ORCA model route.

    Satisfying this structure never starts a process, changes the fleet
    registry, or grants model-invocation authority.
    """

    model_id: str = ""
    model_sha256: str = ""
    runtime_id: str = ""
    runtime_sha256: str = ""
    loopback_only: bool = False
    tool_calls_disabled: bool = False
    bounded_context: bool = False
    post_reboot_model_test: bool = False
    sustained_load_test: bool = False
    orca_responsiveness_test: bool = False
    rollback_test: bool = False
    quench_review_id: str = ""
    fry_activation_id: str = ""


def _valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def evaluate_crucible_acceptance(
    evidence: CrucibleAcceptance | Mapping[str, object] | None = None,
) -> dict:
    """Return a deterministic, fail-closed CRUCIBLE activation diagnostic."""

    if evidence is None:
        acceptance = CrucibleAcceptance()
    elif isinstance(evidence, CrucibleAcceptance):
        acceptance = evidence
    else:
        allowed = set(CrucibleAcceptance.__dataclass_fields__)
        unknown = sorted(set(evidence) - allowed)
        if unknown:
            raise ValueError(f"unknown CRUCIBLE evidence fields: {', '.join(unknown)}")
        acceptance = CrucibleAcceptance(**dict(evidence))

    checks = {
        "model_identity": bool(acceptance.model_id),
        "model_sha256": _valid_sha256(acceptance.model_sha256),
        "runtime_identity": bool(acceptance.runtime_id),
        "runtime_sha256": _valid_sha256(acceptance.runtime_sha256),
        "loopback_only": acceptance.loopback_only is True,
        "tool_calls_disabled": acceptance.tool_calls_disabled is True,
        "bounded_context": acceptance.bounded_context is True,
        "post_reboot_model_test": acceptance.post_reboot_model_test is True,
        "sustained_load_test": acceptance.sustained_load_test is True,
        "orca_responsiveness_test": acceptance.orca_responsiveness_test is True,
        "rollback_test": acceptance.rollback_test is True,
        "independent_quench_review": bool(acceptance.quench_review_id),
        "fry_activation_decision": bool(acceptance.fry_activation_id),
    }
    missing = [name for name, passed in checks.items() if not passed]
    ready = not missing
    return {
        "status": "accepted_not_enabled" if ready else "blocked",
        "activation_ready": ready,
        "runtime_enabled": False,
        "checks": checks,
        "missing": missing,
        "evidence": asdict(acceptance),
        "note": (
            "Acceptance evidence never enables CRUCIBLE automatically; ORCA "
            "model invocation remains a separate controlled action."
        ),
    }
