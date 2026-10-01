import pytest

from orca.vision_dataset import plan_inventory_vision_dataset


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
