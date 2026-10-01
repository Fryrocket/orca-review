import hashlib

import pytest

from orca.vision_dataset import (
    plan_hailo_conversion,
    plan_inventory_capture_session,
    plan_inventory_vision_dataset,
    validate_inventory_dataset,
)


def _plan(**overrides):
    values = {
        "name": "QuasarVolt bench inventory v1",
        "version": "1.0.0",
        "labels": [
            {"id": "CAP-100UF", "name": "100 uF capacitor", "sku": "CAP-100",
             "barcode": "QVCAP100"},
            {"id": "PI-HAT-GUARD", "name": "Pi Guardian HAT", "sku": "QVP-HAT-001"},
        ],
        "source": "Owner-captured QuasarVolt bench images",
        "license_name": "QuasarVolt-owned",
    }
    values.update(overrides)
    return plan_inventory_vision_dataset(**values)


def test_dataset_plan_is_deterministic_bounded_and_non_executing():
    first = _plan()
    second = _plan()
    assert first["manifest_sha256"] == second["manifest_sha256"]
    assert first["state"] == "capture_plan_ready"
    assert first["may_capture"] is False
    assert first["may_train"] is False
    assert first["may_deploy"] is False
    assert first["split"] == {"train": 84, "validation": 18, "test": 18}
    assert first["quality_gates"]["unknown_item_behavior"] == "abstain and stage for review"
    assert "automatic stock mutation" in first["prohibited"]


def test_dataset_plan_normalizes_and_sorts_stable_inventory_labels():
    plan = _plan(labels=[
        {"id": "z-part", "name": "Z part", "sku": "z-1"},
        {"id": "a-part", "name": "A part", "sku": "a-1"},
    ])
    assert [row["id"] for row in plan["labels"]] == ["A-PART", "Z-PART"]
    assert plan["labels"][0]["barcode"] == "A-1"


@pytest.mark.parametrize("labels,match", [
    ([{"id": "person", "name": "Person", "sku": "P-1"}], "prohibited"),
    ([{"id": "A", "name": "One", "sku": "S-1"},
      {"id": "A", "name": "Two", "sku": "S-2"}], "unique"),
    ([{"id": "A", "name": "One", "sku": "S-1", "path": "/tmp"}], "unsupported"),
])
def test_dataset_plan_rejects_sensitive_duplicate_or_unbounded_labels(labels, match):
    with pytest.raises(ValueError, match=match):
        _plan(labels=labels)


def test_dataset_plan_rejects_unbounded_image_targets():
    with pytest.raises(ValueError, match="50-2000"):
        _plan(target_images_per_label=10_000)


def _assets(plan):
    rows = []
    counter = 0
    for label in plan["labels"]:
        for split, amount in plan["split"].items():
            for _ in range(amount):
                counter += 1
                identity = f"asset-{counter:04d}"
                rows.append({
                    "id": identity, "label_id": label["id"], "split": split,
                    "sha256": hashlib.sha256(f"content-{identity}".encode()).hexdigest(),
                    "perceptual_hash": hashlib.sha256(f"visual-{identity}".encode()).hexdigest()[:16],
                    "source_hash": hashlib.sha256(f"source-{identity}".encode()).hexdigest(),
                    "camera_profile": "TEMPER USB 1280x720",
                    "reviewers": ["review-a", "review-b"], "has_person": False,
                    "width": 1280, "height": 720,
                })
    return rows


def test_capture_session_planner_balances_scenarios_without_opening_camera():
    plan = _plan(target_images_per_label=51)
    capture = plan_inventory_capture_session(
        manifest=plan, session_id="temper-session-1",
        camera_profile="TEMPER USB 1280x720")
    assert capture["frames_planned"] == 102
    assert sum(row["per_label"] for row in capture["quotas"]) == 51
    assert capture["frames_captured"] == 0
    assert capture["may_open_camera"] is False
    assert capture["may_capture"] is False


def test_dataset_validator_accepts_balanced_isolated_two_pass_metadata():
    plan = _plan(target_images_per_label=50)
    validation = validate_inventory_dataset(manifest=plan, assets=_assets(plan))
    assert validation["state"] == "accepted_for_training"
    assert validation["accepted"] is True
    assert all(validation["checks"].values())
    assert validation["may_train"] is False


def test_dataset_validator_rejects_duplicates_split_leakage_privacy_and_imbalance():
    plan = _plan(target_images_per_label=50)
    assets = _assets(plan)
    assets[0]["sha256"] = assets[1]["sha256"]
    assets[2]["perceptual_hash"] = assets[-2]["perceptual_hash"]
    assets[3]["has_person"] = True
    assets.pop()
    validation = validate_inventory_dataset(manifest=plan, assets=assets)
    codes = {issue["code"] for issue in validation["issues"]}
    assert {"duplicate_content", "split_leakage", "privacy_frame_rejected",
            "dataset_imbalance"} <= codes
    assert validation["state"] == "rejected"


def test_hailo_conversion_registry_plan_requires_accepted_dataset_and_metrics():
    plan = _plan(target_images_per_label=50)
    validation = validate_inventory_dataset(manifest=plan, assets=_assets(plan))
    conversion = plan_hailo_conversion(
        manifest=plan, validation=validation,
        training_metrics={"precision": .97, "recall": .96, "count_error_rate": .01,
                          "source_model_sha256": hashlib.sha256(b"model").hexdigest()},
        toolchain={"hailo_dataflow_compiler": "3.30", "hailort": "4.20",
                   "target": "hailo8"})
    assert conversion["state"] == "conversion_plan_ready"
    assert conversion["quality_gate_passed"] is True
    assert conversion["may_convert"] is False
    assert conversion["may_register"] is False
    assert conversion["may_deploy"] is False
    blocked = plan_hailo_conversion(
        manifest=plan, validation=validation,
        training_metrics={"precision": .5, "recall": .5, "count_error_rate": .5,
                          "source_model_sha256": hashlib.sha256(b"weak").hexdigest()},
        toolchain={"hailo_dataflow_compiler": "3.30", "hailort": "4.20",
                   "target": "hailo8"})
    assert blocked["state"] == "blocked_quality_gate"
