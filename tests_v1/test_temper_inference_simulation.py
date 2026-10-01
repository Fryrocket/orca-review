from orca.temper_inference_simulation import run_temper_inference_simulation


def test_temper_inference_simulation_is_complete_and_non_executing():
    report = run_temper_inference_simulation()
    assert report["passed"]
    assert report["checks_total"] == report["checks_passed"] == 6
    assert report["details"] == {
        "external_actions": 0, "jobs_enqueued": 0, "frames_captured": 0}
