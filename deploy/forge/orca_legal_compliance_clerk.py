#!/usr/bin/env python3
"""Deterministic organizer for cited legal/compliance matters; not legal advice."""

import argparse
import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse


ALLOWED_SCHEMES = {"https"}
MAX_MATTERS = 100
MAX_SOURCES = 20


def evaluate(data, now=None):
    now = int(time.time() if now is None else now)
    matters = data.get("matters")
    if not isinstance(matters, list) or not matters:
        raise ValueError("matters missing")
    if len(matters) > MAX_MATTERS:
        raise ValueError("too many matters")
    results = []
    findings = []
    for matter in matters:
        matter_id = matter.get("id")
        title = matter.get("title")
        jurisdiction = matter.get("jurisdiction")
        sources = matter.get("sources")
        checklist = matter.get("checklist", [])
        if not all(isinstance(value, str) and value for value in (matter_id, title, jurisdiction)):
            raise ValueError("invalid matter identity")
        if not isinstance(sources, list) or not sources or len(sources) > MAX_SOURCES:
            raise ValueError("invalid sources")
        source_rows = []
        for source in sources:
            url = source.get("url") if isinstance(source, dict) else None
            label = source.get("label") if isinstance(source, dict) else None
            parsed = urlparse(url or "")
            valid = bool(label) and parsed.scheme in ALLOWED_SCHEMES and bool(parsed.netloc)
            source_rows.append({"label": label, "url": url, "valid": valid})
            if not valid:
                findings.append({"matter_id": matter_id, "kind": "invalid_citation"})
        if not isinstance(checklist, list) or any(not isinstance(item, str) or not item for item in checklist):
            raise ValueError("invalid checklist")
        review_required = matter.get("professional_review_required") is not False
        if not review_required:
            findings.append({"matter_id": matter_id, "kind": "professional_review_not_required"})
        results.append({
            "id": matter_id,
            "title": title,
            "jurisdiction": jurisdiction,
            "citation_count": len(source_rows),
            "citations": source_rows,
            "checklist": checklist,
            "professional_review_required": review_required,
            "status": "needs_review" if review_required else "invalid",
        })
    return {
        "schema_version": 1,
        "bot_id": "legal_compliance_clerk",
        "state": "healthy" if not findings else "degraded",
        "mode": data.get("mode", "approved_matter_pack"),
        "observed_epoch": now,
        "authority": "cited_research_and_checklist_organizer",
        "disclaimer": "not_final_legal_advice",
        "matters": results,
        "findings": findings,
        "signed": False,
        "filed": False,
        "external_contact": False,
    }


def waiting_report(now=None):
    return {
        "schema_version": 1, "bot_id": "legal_compliance_clerk", "state": "healthy",
        "mode": "waiting_for_approved_matter_pack",
        "observed_epoch": int(time.time() if now is None else now),
        "authority": "cited_research_and_checklist_organizer",
        "disclaimer": "not_final_legal_advice", "signed": False, "filed": False,
        "external_contact": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="/var/lib/orca-legal-input/input.json")
    parser.add_argument("--output", default="/var/lib/orca-legal-compliance/status.json")
    args = parser.parse_args()
    try:
        source = Path(args.input)
        report = evaluate(json.loads(source.read_text(encoding="utf-8"))) if source.exists() else waiting_report()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = waiting_report()
        report.update({"state": "degraded", "mode": "invalid_matter_pack", "error": type(exc).__name__})
    target = Path(args.output)
    target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o640)
    os.replace(temporary, target)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["state"] == "healthy" else 1


if __name__ == "__main__":
    raise SystemExit(main())
