import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).parents[1] / "deploy" / "kiln" / "orca_image_broker.py"
SPEC = importlib.util.spec_from_file_location("orca_image_broker", MODULE_PATH)
broker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(broker)


def test_image_request_defaults_are_bounded_and_workflow_is_sdxl():
    request = broker.validate_request({"prompt": "A copper robot in a green workshop"})
    assert request["width"] == request["height"] == 768
    assert request["steps"] == 20
    assert 0 <= request["seed"] < 2**63
    workflow = broker.build_workflow(request)
    assert workflow["1"]["inputs"]["ckpt_name"] == "sd_xl_base_1.0.safetensors"
    assert workflow["5"]["inputs"]["latent_image"] == ["4", 0]
    assert workflow["7"]["class_type"] == "SaveImage"


@pytest.mark.parametrize("payload", [
    {}, {"prompt": ""}, {"prompt": "x", "width": 1024},
    {"prompt": "x", "width": 768, "height": 768, "steps": 31},
    {"prompt": "x", "extra": True}, {"prompt": "x", "seed": -1},
])
def test_image_request_rejects_unbounded_or_unknown_fields(payload):
    with pytest.raises(ValueError):
        broker.validate_request(payload)
