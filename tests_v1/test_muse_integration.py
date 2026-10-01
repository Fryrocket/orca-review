import pytest

from orca.muse import build_handoff, integration_status


def test_muse_status_separates_personal_handoff_from_model_api():
    status = integration_status()
    assert status["status"] == "staged"
    assert status["personal_muse"]["mode"] == "governed_browser_handoff"
    assert status["personal_muse"]["direct_api_claimed"] is False
    assert status["muse_spark"]["available"] is False
    assert "credential" in status["muse_spark"]["reason"]
    assert status["return_contract"] == "cited_candidate_pack_v1"


def test_muse_handoff_is_deterministic_cited_and_inert():
    request = {"workflow_id": "business-23-muse-product-scout",
               "objective": "Find evidence-backed electronics products to test."}
    first = build_handoff(**request)
    second = build_handoff(**request)
    assert first == second
    assert first["handoff_id"].startswith("muse-")
    assert first["official_url"].endswith("/muse/shopping/")
    assert "source URLs and observation timestamps" in first["muse_prompt"]
    assert "Do not purchase" in first["muse_prompt"]
    assert first["external_actions_allowed"] is False
    assert first["purchases"] == first["messages"] == first["publications"] == 0
    assert first["credentials_requested"] == 0


@pytest.mark.parametrize("workflow", ["", "../bad", "business bad", "x-23-muse"])
def test_muse_handoff_rejects_invalid_workflow_ids(workflow):
    with pytest.raises(ValueError, match="workflow ID"):
        build_handoff(workflow_id=workflow, objective="research only")


def test_muse_handoff_rejects_empty_or_unbounded_objectives():
    with pytest.raises(ValueError, match="objective"):
        build_handoff(workflow_id="business-23-muse", objective=" ")
    with pytest.raises(ValueError, match="objective"):
        build_handoff(workflow_id="business-23-muse", objective="x" * 8_001)
