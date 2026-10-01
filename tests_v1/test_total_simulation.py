from orca.total_simulation import FEATURE_MODULES, run_total_simulation


def test_total_simulation_covers_a_to_z_and_has_zero_external_effects():
    report = run_total_simulation()
    assert report["passed"], report["failed_stages"]
    assert report["stages_total"] == report["stages_passed"] == 26
    assert [item["letter"] for item in report["stages"]] == list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    assert report["nested_checks_total"] >= 54
    assert report["nested_checks_total"] == report["nested_checks_passed"]
    assert all(value == 0 for key, value in report["safety"].items() if key != "mode")
    assert len(FEATURE_MODULES) >= 50
