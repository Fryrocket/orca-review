"""Bounded Meta Muse handoffs for ORCA Business.

Personal Muse is an interactive agent with its own browser.  ORCA therefore
uses an explicit handoff/return contract rather than claiming an undocumented
server API.  Meta's separate Model API can be added later as a reasoning
provider, but remains staged until an owner-controlled credential and egress
policy are configured.
"""

from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Any


MUSE_SHOPPING_URL = "https://ai.meta.com/muse/shopping/"
MUSE_MODEL_API_DOCS = "https://ai.meta.com/llama/"
MAX_OBJECTIVE_CHARS = 8_000
_WORKFLOW_ID = re.compile(r"^business-[a-z0-9-]{1,100}$")


def _bounded_text(value: object, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"Muse {name} is invalid")
    return value.strip()


def integration_status() -> dict[str, Any]:
    """Describe supported lanes without implying external authorization."""

    return {
        "status": "staged",
        "personal_muse": {
            "mode": "governed_browser_handoff",
            "official_url": MUSE_SHOPPING_URL,
            "available": True,
            "direct_api_claimed": False,
            "external_actions_allowed": False,
        },
        "muse_spark": {
            "mode": "optional_openai_compatible_model_provider",
            "documentation": MUSE_MODEL_API_DOCS,
            "available": False,
            "reason": "owner credential, cost approval, and egress acceptance are not configured",
            "external_actions_allowed": False,
        },
        "return_contract": "cited_candidate_pack_v1",
    }


def build_handoff(*, workflow_id: object, objective: object) -> dict[str, Any]:
    """Build an inert, traceable research handoff for personal Muse.

    The result contains instructions only.  It cannot purchase, message,
    publish, sign in, or alter an external account.
    """

    workflow = _bounded_text(workflow_id, "workflow ID", 120)
    if not _WORKFLOW_ID.fullmatch(workflow):
        raise ValueError("Muse workflow ID is invalid")
    task = _bounded_text(objective, "objective", MAX_OBJECTIVE_CHARS)
    digest = sha256(json.dumps(
        {"objective": task, "workflow_id": workflow},
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    handoff_id = f"muse-{digest[:20]}"
    return_schema = {
        "candidate_id": "stable short identifier",
        "name": "product name",
        "customer_problem": "problem supported by evidence",
        "observed_prices": [{
            "amount": "decimal string", "currency": "ISO currency",
            "url": "https URL", "observed_at": "ISO-8601 timestamp",
        }],
        "evidence": [{
            "label": "short source label", "url": "https URL",
            "observed_at": "ISO-8601 timestamp",
            "observed_fact": "fact visible at the source",
        }],
        "supplier_paths": ["observed or clearly labeled candidate supplier"],
        "risks": ["competition, return, safety, compliance, IP, or logistics risk"],
        "assumptions": ["every estimate or inference"],
        "confidence": "low, medium, or high",
    }
    prompt = (
        "You are performing a research-only product scouting handoff for ORCA.\n"
        f"Handoff ID: {handoff_id}\n\n"
        f"Objective:\n{task}\n\n"
        "Use permitted public web sources to find and compare relevant products. "
        "Return source URLs and observation timestamps for every important factual "
        "claim. Separate observed facts from estimates and assumptions. Do not "
        "invent sales volume, demand, supplier terms, certifications, availability, "
        "or margins. Do not purchase, add items to a cart, negotiate, message, list, "
        "publish, sign in to a new account, accept terms, or spend money. Stop before "
        "any consequential external action. Return a concise candidate pack matching "
        "this JSON shape:\n"
        + json.dumps({"handoff_id": handoff_id, "candidates": [return_schema]},
                     indent=2, sort_keys=True)
    )
    return {
        "status": "ready",
        "handoff_id": handoff_id,
        "workflow_id": workflow,
        "official_url": MUSE_SHOPPING_URL,
        "muse_prompt": prompt,
        "return_schema": return_schema,
        "external_actions_allowed": False,
        "purchases": 0,
        "messages": 0,
        "publications": 0,
        "credentials_requested": 0,
    }
