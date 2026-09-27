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


def test_crucible_failure_releases_models_without_changing_services(monkeypatch):
    monkeypatch.setattr(broker, "MANAGED_ENGINE", False)
    def forbidden(*args, **kwargs):
        raise AssertionError("CRUCIBLE must not stop or start inference services")
    monkeypatch.setattr(broker.subprocess, "run", forbidden)
    monkeypatch.setattr(broker, "wait_for_comfy", lambda *_: None)
    calls = []
    def request(method, path, body=None, **kwargs):
        calls.append((method, path, body))
        if path == "/prompt":
            raise RuntimeError("test generation failure")
        return {}
    monkeypatch.setattr(broker, "comfy_json", request)
    with pytest.raises(RuntimeError, match="test generation failure"):
        broker.generate_image(broker.validate_request({"prompt": "test"}))
    assert calls[-1] == ("POST", "/free", {"unload_models": True, "free_memory": True})


def test_comfy_free_accepts_empty_success_body(monkeypatch):
    class Response:
        status = 200
        def read(self):
            return b""
    class Connection:
        def __init__(self, *args, **kwargs): pass
        def request(self, *args, **kwargs): pass
        def getresponse(self): return Response()
        def close(self): pass
    monkeypatch.setattr(broker, "HTTPConnection", Connection)
    assert broker.comfy_json("POST", "/free", {"free_memory": True}) == {}
    with pytest.raises(ValueError):
        broker.comfy_json("GET", "/history/example")
