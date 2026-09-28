from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Any

from .security import redact_text


MAX_PROMPT = 4_000
_SPACE = re.compile(r"\s+")
_SLUG = re.compile(r"[^a-z0-9]+")


def _name(prompt: str) -> str:
    cleaned = _SPACE.sub(" ", prompt.strip())
    cleaned = re.sub(
        r"^(?:please\s+)?(?:create|build|design|develop|make|plan)\s+(?:an?\s+|the\s+)?",
        "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.rstrip(".!? ")
    return (cleaned[:77].rstrip() + "...") if len(cleaned) > 80 else cleaned


def _slug(value: str) -> str:
    slug = _SLUG.sub("-", value.casefold()).strip("-")[:52]
    return slug or "new-product"


def _track(id: str, name: str, owner: str, purpose: str) -> dict[str, str]:
    return {"id": id, "name": name, "owner": owner, "purpose": purpose}


def build_product_development_plan(prompt: str, inventory: dict | None = None) -> dict[str, Any]:
    """Build a truthful, stage-gated plan for an arbitrary physical product."""

    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT:
        raise ValueError("product brief must contain 1-4000 characters")
    if redact_text(prompt) != prompt:
        raise ValueError("product brief contains secret-shaped data")
    product_name = _name(prompt)
    normalized = prompt.casefold()
    digest = sha256(_SPACE.sub(" ", normalized).strip().encode()).hexdigest()
    product_id = f"qv-product-{_slug(product_name)}-{digest[:8]}"

    electronics = any(word in normalized for word in (
        "electronic", "pcb", "circuit", "sensor", "arduino", "raspberry", "pi hat",
        "motor", "robot", "device", "powered", "battery", "charger", "wireless", "ai",
    ))
    software = electronics or any(word in normalized for word in (
        "software", "firmware", "app", "cloud", "connected", "smart", "ai"))
    mechanical = electronics or any(word in normalized for word in (
        "mechanical", "enclosure", "machine", "feeder", "mount", "tool", "housing"))
    wireless = any(word in normalized for word in (
        "wireless", "wifi", "wi-fi", "bluetooth", "radio", "lte", "cellular"))
    battery = any(word in normalized for word in (
        "battery", "lithium", "rechargeable", "portable", "charger"))
    ai = any(word in normalized for word in (" ai ", "artificial intelligence", "machine learning", "vision"))

    tracks = [
        _track("product", "Product strategy", "ORCA", "Customer problem, value, scope, price, and success metrics"),
        _track("industrial", "Industrial design", "ORCA + Fry", "Usability, appearance, human factors, service access, and packaging"),
        _track("quality", "Quality engineering", "QUENCH", "Requirements traceability, risk, verification, reliability, and release evidence"),
        _track("supply", "Supply and manufacturing", "ORCA", "BOM, sources, cost, process, inspection, yield, and lifecycle"),
    ]
    if electronics:
        tracks.append(_track("electrical", "Electrical and PCB", "ORCA Engineering", "Power, signals, schematic, layout, DFM, test, and component lifecycle"))
    if software:
        tracks.append(_track("firmware", "Firmware and software", "ORCA Engineering", "Architecture, interfaces, versioning, tests, update and recovery"))
    if mechanical:
        tracks.append(_track("mechanical", "Mechanical engineering", "ORCA Engineering", "Loads, tolerance, materials, thermal path, enclosure, and assembly"))
    if wireless:
        tracks.append(_track("rf", "RF and cybersecurity", "ORCA + QUENCH", "Radio performance, coexistence, credentials, update security, and privacy"))
    if battery:
        tracks.append(_track("battery", "Battery safety", "ORCA + qualified review", "Cell selection, protection, charging, thermal risk, transport, and end-of-life"))
    if ai:
        tracks.append(_track("ai", "AI behavior and data", "ORCA + QUENCH", "Model limits, data provenance, evaluation, privacy, fallback, and monitoring"))

    phases = [
        ("discovery", "Discovery", "ready", "Evidence for customer, problem, alternatives, price, and demand"),
        ("requirements", "Requirements", "ready", "Approved, measurable product requirements and acceptance methods"),
        ("architecture", "System architecture", "waiting", "Interfaces, budgets, hazards, tradeoffs, and make/buy decisions reviewed"),
        ("feasibility", "Feasibility", "waiting", "Critical unknowns tested with calculations, experiments, or proof-of-concept builds"),
        ("detailed_design", "Detailed design", "waiting", "Released electrical, mechanical, firmware, BOM, and documentation revisions"),
        ("prototype", "Prototype", "waiting", "Traceable build completed with deviations, inspection, and bring-up evidence"),
        ("verification", "Verification", "waiting", "Every requirement has passing evidence or an approved, documented exception"),
        ("manufacturing", "Manufacturing readiness", "waiting", "DFM/DFT, suppliers, work instructions, QC, pilot yield, and recovery plan approved"),
        ("launch", "Launch readiness", "waiting", "Support, channel, compliance, packaging, service, rollback, and business gates approved"),
        ("lifecycle", "Lifecycle", "waiting", "Field quality, revisions, obsolescence, support, and end-of-life controls active"),
    ]
    phases = [
        {"id": item[0], "name": item[1], "status": item[2], "exit_criteria": item[3],
         "owner": "Fry" if item[0] in {"requirements", "launch"} else "ORCA"}
        for item in phases
    ]

    requirements = [
        {"id": "PRD-001", "category": "Customer", "statement": "Define the target user, job, operating context, and unacceptable outcomes.", "verification": "Interview and evidence review", "status": "open"},
        {"id": "PRD-002", "category": "Performance", "statement": "Set measurable performance, accuracy, capacity, latency, duty-cycle, and lifetime targets.", "verification": "Bench test with recorded limits", "status": "open"},
        {"id": "PRD-003", "category": "Safety", "statement": "Identify hazards, foreseeable misuse, safe states, warnings, and residual risk.", "verification": "Risk review and fault testing", "status": "open"},
        {"id": "PRD-004", "category": "Interfaces", "statement": "Define physical, electrical, data, user, service, and environmental interfaces.", "verification": "Interface inspection and integration test", "status": "open"},
        {"id": "PRD-005", "category": "Manufacturing", "statement": "Set target cost, volume, yield, test time, approved substitutions, traceability, and packaging.", "verification": "Pilot build and costed BOM review", "status": "open"},
        {"id": "PRD-006", "category": "Service", "statement": "Define diagnostics, repair, updates, spares, warranty, support, and end-of-life behavior.", "verification": "Service drill and documentation review", "status": "open"},
    ]
    if electronics:
        requirements.append({"id": "PRD-007", "category": "Electrical", "statement": "Define supply range, peak and idle power, protection, EMC, thermal limits, connectors, and test points.", "verification": "Electrical characterization, ERC/DRC, and pre-compliance test", "status": "open"})
    if software:
        requirements.append({"id": "PRD-008", "category": "Software", "statement": "Define boot, update, recovery, logging, data retention, compatibility, security, and offline behavior.", "verification": "Automated tests, fault injection, and recovery drill", "status": "open"})

    risks = [
        {"id": "RISK-001", "hazard": "Requirements drift", "severity": 7, "occurrence": 6, "detection": 5, "rpn": 210, "control": "Baseline requirements and require traceable change review", "owner": "Fry"},
        {"id": "RISK-002", "hazard": "Unverified supplier or substitute", "severity": 7, "occurrence": 5, "detection": 6, "rpn": 210, "control": "Approved-vendor list, samples, inspection, and change notification", "owner": "ORCA"},
        {"id": "RISK-003", "hazard": "Design passes analysis but fails in use", "severity": 8, "occurrence": 4, "detection": 7, "rpn": 224, "control": "Prototype against worst-case loads and foreseeable misuse", "owner": "QUENCH"},
        {"id": "RISK-004", "hazard": "Manufacturing variation", "severity": 6, "occurrence": 5, "detection": 5, "rpn": 150, "control": "Tolerance analysis, DFM, test fixtures, pilot yield, and control plan", "owner": "ORCA"},
    ]
    if battery:
        risks.append({"id": "RISK-005", "hazard": "Battery thermal event or abusive charging", "severity": 10, "occurrence": 3, "detection": 6, "rpn": 180, "control": "Certified cells, protection, thermal validation, qualified review, and transport controls", "owner": "Qualified reviewer"})
    if wireless or software:
        risks.append({"id": "RISK-006", "hazard": "Unauthorized access or unsafe update", "severity": 8, "occurrence": 4, "detection": 6, "rpn": 192, "control": "Threat model, least privilege, signed updates, rollback, and security testing", "owner": "QUENCH"})

    deliverables = [
        {"id": "DOC-001", "name": "Product charter", "format": "Writer + PDF", "state": "planned", "path": "01-discovery/product-charter"},
        {"id": "DOC-002", "name": "Requirements and trace matrix", "format": "Calc", "state": "planned", "path": "02-requirements/requirements-trace"},
        {"id": "DOC-003", "name": "System architecture", "format": "Draw + PDF", "state": "planned", "path": "03-architecture/system-architecture"},
        {"id": "DOC-004", "name": "Risk register and FMEA", "format": "Calc", "state": "planned", "path": "04-risk/risk-register"},
        {"id": "DOC-005", "name": "Costed BOM and AVL", "format": "Calc", "state": "planned", "path": "05-design/bom-avl"},
        {"id": "DOC-006", "name": "Verification plan and report", "format": "Writer + Calc + PDF", "state": "planned", "path": "07-verification/verification"},
        {"id": "DOC-007", "name": "Manufacturing release package", "format": "Native CAD + PDF + CSV", "state": "planned", "path": "08-manufacturing/release"},
        {"id": "DOC-008", "name": "Launch and lifecycle record", "format": "Writer + Calc", "state": "planned", "path": "09-launch/launch-lifecycle"},
    ]
    if electronics:
        deliverables.extend([
            {"id": "CAD-001", "name": "KiCad schematic", "format": "KiCad", "state": "planned", "path": "05-design/electrical/schematic"},
            {"id": "CAD-002", "name": "PCB layout and fabrication outputs", "format": "KiCad + Gerber", "state": "planned", "path": "05-design/electrical/pcb"},
        ])
    if mechanical:
        deliverables.append({"id": "CAD-003", "name": "Mechanical assembly and drawings", "format": "STEP + drawing PDF", "state": "planned", "path": "05-design/mechanical"})
    if software:
        deliverables.append({"id": "SW-001", "name": "Firmware/software release", "format": "Source + binary + SBOM", "state": "planned", "path": "05-design/software"})

    items = inventory.get("items", []) if isinstance(inventory, dict) else []
    valid_items = [item for item in items if isinstance(item, dict)]
    inventory_state = "available" if isinstance(inventory, dict) else "unavailable"
    plan = {
        "schema": 1,
        "product_id": product_id,
        "product_name": product_name,
        "brief": _SPACE.sub(" ", prompt.strip()),
        "maturity": "concept",
        "release_state": "not_released",
        "tracks": tracks,
        "phases": phases,
        "requirements": requirements,
        "risks": sorted(risks, key=lambda item: item["rpn"], reverse=True),
        "deliverables": deliverables,
        "inventory": {
            "state": inventory_state,
            "items_seen": len(valid_items),
            "matched_items": [],
            "warning": "Inventory was inspected, but no part is allocated until exact specifications and manufacturer part numbers are approved." if inventory_state == "available" else "No inventory source was available; no stock claim was made.",
        },
        "tool_plan": [
            {"name": "ORCA Chat", "purpose": "Coordinate research, calculations, decisions, evidence, and approvals", "state": "available"},
            {"name": "KiCad", "purpose": "Electrical design, PCB layout, checks, fabrication data, and 3D inspection", "state": "planned" if electronics else "not_required"},
            {"name": "LibreOffice", "purpose": "Requirements, BOM, FMEA, reports, diagrams, presentations, and formulas", "state": "available"},
            {"name": "Google Drive", "purpose": "Collaboration artifacts and document register", "state": "connected_record_only"},
            {"name": "Notion", "purpose": "Operating decisions and project context", "state": "connected_record_only"},
            {"name": "QUENCH", "purpose": "Independent design and release review", "state": "required"},
        ],
        "approval_gates": [
            {"gate": "Requirements baseline", "authority": "Fry", "status": "required"},
            {"gate": "Prototype spend or supplier contact", "authority": "Fry", "status": "required"},
            {"gate": "Safety/compliance conclusion", "authority": "Qualified reviewer", "status": "required"},
            {"gate": "Manufacturing release", "authority": "Fry + QUENCH", "status": "required"},
            {"gate": "External publication or launch", "authority": "Fry", "status": "required"},
        ],
        "next_actions": [
            "Validate the customer problem and operating environment with current evidence.",
            "Replace open requirement prompts with measurable limits and acceptance methods.",
            "Identify the three highest-risk unknowns and run the cheapest decisive tests.",
            "Approve the requirements baseline before detailed CAD or purchasing begins.",
        ],
        "legacy_pcb_draft_supported": "dog" in normalized and any(
            word in normalized for word in ("feeder", "feed", "dispens")),
    }
    validate_product_development_plan(plan)
    return plan


def validate_product_development_plan(plan: dict[str, Any]) -> dict[str, Any]:
    required = {
        "schema", "product_id", "product_name", "brief", "maturity", "release_state",
        "tracks", "phases", "requirements", "risks", "deliverables", "inventory",
        "tool_plan", "approval_gates", "next_actions", "legacy_pcb_draft_supported",
    }
    if not isinstance(plan, dict) or set(plan) != required or plan.get("schema") != 1:
        raise ValueError("product development plan has an invalid schema")
    for key, limit in (("product_id", 128), ("product_name", 80), ("brief", MAX_PROMPT)):
        if not isinstance(plan[key], str) or not plan[key] or len(plan[key]) > limit:
            raise ValueError(f"product {key} is invalid")
    if plan["maturity"] != "concept" or plan["release_state"] != "not_released":
        raise ValueError("new product plans must begin as unreleased concepts")
    bounded_lists = {
        "tracks": (4, 12), "phases": (10, 10), "requirements": (6, 20),
        "risks": (4, 20), "deliverables": (8, 20), "tool_plan": (6, 16),
        "approval_gates": (5, 12), "next_actions": (1, 12),
    }
    for key, (minimum, maximum) in bounded_lists.items():
        if not isinstance(plan[key], list) or not minimum <= len(plan[key]) <= maximum:
            raise ValueError(f"product {key} is invalid")
    if type(plan["legacy_pcb_draft_supported"]) is not bool:
        raise ValueError("product capability state is invalid")
    for risk in plan["risks"]:
        if (not isinstance(risk, dict) or set(risk) != {
                "id", "hazard", "severity", "occurrence", "detection", "rpn", "control", "owner"}):
            raise ValueError("product risk is invalid")
        for factor in ("severity", "occurrence", "detection"):
            if type(risk[factor]) is not int or not 1 <= risk[factor] <= 10:
                raise ValueError("product risk score is invalid")
        if risk["rpn"] != risk["severity"] * risk["occurrence"] * risk["detection"]:
            raise ValueError("product risk priority number is invalid")
    encoded = json.dumps(plan, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode()) > 192_000:
        raise ValueError("product development plan exceeds the size limit")
    if redact_text(encoded) != encoded:
        raise ValueError("product development plan contains secret-shaped data")
    return plan
