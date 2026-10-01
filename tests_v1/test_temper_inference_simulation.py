from orca.temper_inference_simulation import run_temper_inference_simulation


def test_temper_inference_simulation_is_complete_and_non_executing():
    report = run_temper_inference_simulation()
    assert report["passed"]
    assert report["checks_total"] == report["checks_passed"] == 13
    assert report["details"]["datasets_written"] == 0
    assert report["details"]["models_trained"] == 0
    assert report["details"]["external_actions"] == 0
    assert report["details"]["jobs_enqueued"] == 0
    assert report["details"]["frames_captured"] == 0
    assert report["details"]["models_converted"] == 0
    assert report["details"]["models_deployed"] == 0
    assert len(report["details"]["dataset_sha256"]) == 64
    assert len(report["details"]["registry_record_sha256"]) == 64
