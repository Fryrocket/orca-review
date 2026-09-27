import pytest

from orca.crucible import (
    CrucibleAcceptance,
    current_crucible_acceptance,
    evaluate_crucible_acceptance,
    load_crucible_acceptance,
)


def test_crucible_is_blocked_without_model_runtime_and_acceptance_evidence():
    report = evaluate_crucible_acceptance()
    assert report["status"] == "blocked"
    assert report["activation_ready"] is False
    assert report["runtime_enabled"] is False
    assert "model_identity" in report["missing"]
    assert "independent_quench_review" in report["missing"]
    assert "fry_activation_decision" in report["missing"]


def test_complete_acceptance_is_recordable_but_never_auto_enables_runtime():
    digest = "a" * 64
    report = evaluate_crucible_acceptance(CrucibleAcceptance(
        model_id="accepted-local-model",
        model_sha256=digest,
        runtime_id="accepted-rocm-server",
        runtime_sha256=digest,
        loopback_only=True,
        tool_calls_disabled=True,
        bounded_context=True,
        post_reboot_model_test=True,
        sustained_load_test=True,
        orca_responsiveness_test=True,
        rollback_test=True,
        quench_review_id="quench-review-1",
        fry_activation_id="fry-decision-1",
    ))
    assert report["status"] == "accepted_not_enabled"
    assert report["activation_ready"] is True
    assert report["missing"] == []
    assert report["runtime_enabled"] is False


def test_digest_and_schema_validation_fail_closed():
    report = evaluate_crucible_acceptance({"model_sha256": "ABC"})
    assert report["checks"]["model_sha256"] is False
    with pytest.raises(ValueError, match="unknown CRUCIBLE evidence fields"):
        evaluate_crucible_acceptance({"enable_runtime": True})


def test_acceptance_file_is_bounded_and_fails_closed(monkeypatch, tmp_path):
    evidence = tmp_path / "acceptance.json"
    evidence.write_text('{"model_id":"accepted"}')
    monkeypatch.setenv("ORCA_CRUCIBLE_ACCEPTANCE_FILE", str(evidence))
    assert load_crucible_acceptance().model_id == "accepted"
    assert current_crucible_acceptance()["activation_ready"] is False

    evidence.write_text('{"enable_runtime":true}')
    report = current_crucible_acceptance()
    assert report["status"] == "blocked"
    assert "unreadable or invalid" in report["note"]

    evidence.unlink()
    evidence.symlink_to(tmp_path / "missing")
    assert current_crucible_acceptance()["activation_ready"] is False
