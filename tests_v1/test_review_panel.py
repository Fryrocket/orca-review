import pytest

from orca.review_panel import (
    REVIEWERS,
    build_review_packet,
    reconcile_findings,
    review_panel_plan,
)
from orca.studio_tools import StudioReadTools
from orca.tools import BOT_TOOL_MANIFESTS, TOOL_CATALOG


def test_free_review_panel_is_inside_orca_and_has_no_paid_fallback():
    plan = review_panel_plan()
    assert plan["free_only"] is True
    assert plan["paid_fallback"] is False
    assert "Flux AI" in plan["excluded"]
    assert set(REVIEWERS) == {
        "qwen_challenger", "quench", "anvil_reflex",
        "gemini_free", "claude_free", "copilot_free",
    }
    assert [row["id"] for row in plan["reviewers"] if row["release_authority"]] == ["quench"]
    assert plan["autonomy"]["interactive_prompt_during_run"] is False
    assert "degraded" in plan["autonomy"]["on_auth_or_quota_failure"]
    assert all("engineering.review_panel" in BOT_TOOL_MANIFESTS[bot]
               for bot in ("orca", "smith", "quench"))
    assert "engineering.review_panel" in TOOL_CATALOG
    handler = StudioReadTools(control_snapshot=lambda: {}).handlers()["engineering.review_panel"]
    assert handler()["manufacturing_release"] == "always requires physical evidence"


def test_review_packet_is_hashed_bounded_and_secret_safe():
    packet = build_review_packet(
        project_id="orca_pi5_cooling_hat_test",
        candidate_files={"board.kicad_pcb": "(kicad_pcb)", "review.md": "No secrets."},
        claims=["Every used pad is routed"],
        public_sources=["https://datasheets.raspberrypi.com/hat/hat-plus-specification.pdf"],
    )
    assert len(packet["packet_sha256"]) == 64
    assert packet["physical_results_claimed"] is False
    assert all(len(row["sha256"]) == 64 for row in packet["files"])
    with pytest.raises(ValueError, match="secret"):
        build_review_packet(
            project_id="test", candidate_files={"bad.md": "API_KEY=do-not-send"},
            claims=[], public_sources=[])


def test_only_reproducible_evidence_becomes_a_confirmed_finding():
    common = {
        "reviewer": "gemini_free", "severity": "high", "category": "hat_compliance",
        "claim": "ID EEPROM is missing", "source_reference": "HAT+ spec chapter 3",
        "reproducible_check": "inspect ID_SD and ID_SC nets",
    }
    result = reconcile_findings([
        {**common, "evidence_type": "official_specification"},
        {**common, "reviewer": "claude_free", "evidence_type": "opinion"},
        {"reviewer": "broken"},
    ])
    assert len(result["confirmed"]) == 1
    assert result["confirmed"][0]["status"] == "confirmed_pending_quench_disposition"
    assert len(result["hypotheses"]) == 1
    assert result["rejected"] == [{"reason": "invalid_schema"}]
    assert result["manufacturing_release"] is False
