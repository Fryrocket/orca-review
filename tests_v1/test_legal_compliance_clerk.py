import sys
from pathlib import Path

repository = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repository / "deploy" / "forge"))
from orca_legal_compliance_clerk import evaluate, waiting_report


def valid_pack():
    return {"matters": [{
        "id": "matter-1", "title": "Synthetic marketplace review", "jurisdiction": "US",
        "sources": [{"label": "Official rule", "url": "https://example.gov/rule"}],
        "checklist": ["Confirm product category", "Request professional review"],
        "professional_review_required": True,
    }]}


def test_cited_pack_requires_professional_review_and_never_acts():
    report = evaluate(valid_pack(), now=1000)
    assert report["state"] == "healthy"
    assert report["disclaimer"] == "not_final_legal_advice"
    assert report["matters"][0]["status"] == "needs_review"
    assert report["signed"] is False and report["filed"] is False
    assert report["external_contact"] is False


def test_invalid_citation_and_missing_review_fail_closed():
    pack = valid_pack()
    pack["matters"][0]["sources"][0]["url"] = "http://invalid.example/rule"
    pack["matters"][0]["professional_review_required"] = False
    report = evaluate(pack, now=1000)
    assert report["state"] == "degraded"
    assert len(report["findings"]) == 2


def test_waiting_mode_is_truthful():
    report = waiting_report(now=1000)
    assert report["mode"] == "waiting_for_approved_matter_pack"
    assert report["state"] == "healthy"
