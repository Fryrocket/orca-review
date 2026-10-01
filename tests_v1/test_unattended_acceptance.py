from orca.unattended_acceptance import run_unattended_acceptance


def test_unattended_acceptance_is_complete_non_mutating_and_integrity_checked(tmp_path):
    report = run_unattended_acceptance(tmp_path)
    assert report["passed"] is True
    assert report["checks_passed"] == report["checks_total"] == 5
    assert report["external_actions"] == 0
    assert report["live_state_changed"] is False
    assert report["evidence_integrity"]["valid"] is True
    evidence = (tmp_path / report["evidence"].split("/")[-1]).read_text()
    assert "disposable-secret-must-not-appear" not in evidence


def test_recovery_drill_copies_every_runtime_tree_required_by_acceptance():
    source = __import__("pathlib").Path("scripts/recovery_drill.py").read_text()
    for tree in ('"orca"', '"tests_v1"', '"docs"', '"scripts"', '"deploy"', '"desktop"',
                 '"benchmarks"'):
        assert tree in source
