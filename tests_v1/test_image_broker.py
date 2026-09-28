import importlib.util
import base64
import struct
import zlib
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).parents[1] / "deploy" / "kiln" / "orca_image_broker.py"
SPEC = importlib.util.spec_from_file_location("orca_image_broker", MODULE_PATH)
broker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(broker)


def png(width=64, height=64, color=(70, 100, 120)):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress((b'\x00' + bytes(color) * width) * height)) + chunk(b'IEND', b''))


def test_edit_workflows_use_real_source_pixels_and_preserve_unmasked_regions():
    source = base64.b64encode(png()).decode()
    request = broker.validate_edit_request({'prompt': 'a red cube', 'image': source, 'strength': .5})
    workflow = broker.build_workflow(request)
    assert workflow['4']['class_type'] == 'VAEEncode'
    assert workflow['5']['inputs']['denoise'] == .5
    assert workflow['8']['inputs']['image'] == 'orca-edit-source.png [temp]'
    request = broker.validate_edit_request({'prompt': 'a red cube', 'image': source, 'mask': source})
    workflow = broker.build_workflow(request)
    assert workflow['4']['class_type'] == 'VAEEncodeForInpaint'
    assert workflow['11']['class_type'] == 'ImageCompositeMasked'
    assert workflow['11']['inputs']['destination'] == ['8', 0]
    assert workflow['7']['inputs']['images'] == ['11', 0]


@pytest.mark.parametrize('extra', [
    {'strength': float('nan')}, {'strength': True}, {'strength': 0}, {'strength': 1.1},
    {'image': 'http://example.com/image.png'}, {'image': '../secret'}, {'workflow': {}},
    {'mask': base64.b64encode(png(128, 64)).decode()},
    {'image': base64.b64encode(png(1224, 64)).decode()},
    {'image': base64.b64encode(png()[:-1]).decode()},
])
def test_edit_rejects_untrusted_inputs(extra):
    with pytest.raises(ValueError):
        broker.validate_edit_request({'prompt': 'test', 'image': base64.b64encode(png()).decode(), **extra})


def test_png_rejects_broken_crc_and_trailing_data():
    for data in [png() + b'extra', png()[:40] + b'wrong' + png()[45:]]:
        with pytest.raises(ValueError):
            broker.decode_png(base64.b64encode(data).decode())


def test_edit_gateway_routes_only_edit_uploads_with_larger_limit():
    source = (MODULE_PATH.parents[1] / 'orca_studio_gateway.py').read_text()
    assert '18_000_000 if self.path in {' in source
    assert '"/api/images/edit", "/api/videos/animate"' in source
    assert '"/api/images/edit": "/edit"' in source
    assert '"/api/videos/generate": "/video/generate"' in source
    assert '"/api/videos/animate": "/video/animate"' in source


def test_canvas_undo_uses_pixel_snapshots_without_relaxing_content_security():
    source = (MODULE_PATH.parents[2] / 'orca/static/app.js').read_text()
    assert 'image: context.getImageData(0, 0, canvas.width, canvas.height)' in source
    assert 'context.putImageData(previous.image, 0, 0)' in source
    assert 'canvasUndo.length > 5' in source


def test_image_request_defaults_are_bounded_and_workflow_is_sdxl():
    request = broker.validate_request({"prompt": "A copper robot in a green workshop"})
    assert request["width"] == request["height"] == 1024
    assert request["steps"] == 28
    assert request["sampler"] == "dpmpp_2m"
    assert request["scheduler"] == "karras"
    assert 0 <= request["seed"] < 2**53
    workflow = broker.build_workflow(request)
    assert workflow["1"]["inputs"]["ckpt_name"] == "sd_xl_base_1.0.safetensors"
    assert workflow["5"]["inputs"]["latent_image"] == ["4", 0]
    assert workflow["7"]["class_type"] == "SaveImage"


@pytest.mark.parametrize("payload", [
    {}, {"prompt": ""}, {"prompt": "x", "width": 1024, "height": 768},
    {"prompt": "x", "width": 768, "height": 768, "steps": 41},
    {"prompt": "x", "extra": True}, {"prompt": "x", "seed": -1},
    {"prompt": "x", "sampler": "untrusted"}, {"prompt": "x", "cfg": 13},
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


def test_native_sdxl_formats_and_high_quality_sampler_are_bounded():
    request = broker.validate_request({
        "prompt": "product photo", "width": 1216, "height": 832,
        "steps": 36, "cfg": 6.5, "sampler": "dpmpp_sde", "scheduler": "karras",
    })
    workflow = broker.build_workflow(request)
    assert workflow["4"]["inputs"] == {"width": 1216, "height": 832, "batch_size": 1}
    assert workflow["5"]["inputs"]["sampler_name"] == "dpmpp_sde"
    assert workflow["5"]["inputs"]["scheduler"] == "karras"
    assert workflow["5"]["inputs"]["cfg"] == 6.5


def test_video_request_defaults_and_native_wan_workflow_are_bounded():
    request = broker.validate_video_request({"prompt": "A circuit board rotates under moonlight"})
    assert (request["width"], request["height"]) == (832, 480)
    assert request["length"] == 73
    assert request["steps"] == 20
    assert request["fps"] == 24
    assert 0 <= request["seed"] < 2**53
    workflow = broker.build_video_workflow(request)
    assert workflow["1"]["inputs"]["unet_name"] == "wan2.2_ti2v_5B_fp16.safetensors"
    assert workflow["2"]["inputs"]["clip_name"] == "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
    assert workflow["3"]["inputs"]["vae_name"] == "wan2.2_vae.safetensors"
    assert workflow["7"]["class_type"] == "Wan22ImageToVideoLatent"
    assert "start_image" not in workflow["7"]["inputs"]
    assert workflow["8"]["inputs"]["sampler_name"] == "uni_pc"
    assert workflow["10"]["class_type"] == "CreateVideo"
    assert workflow["11"]["class_type"] == "SaveVideo"


def test_video_animation_uses_validated_source_pixels():
    source = base64.b64encode(png(64, 64)).decode()
    request = broker.validate_video_request({
        "prompt": "Slow camera orbit", "image": source,
        "width": 640, "height": 640, "length": 49, "fps": 16,
    }, animate=True)
    workflow = broker.build_video_workflow(request)
    assert workflow["12"]["class_type"] == "LoadImage"
    assert workflow["7"]["inputs"]["start_image"] == ["12", 0]


@pytest.mark.parametrize("payload,animate", [
    ({}, False), ({"prompt": ""}, False),
    ({"prompt": "x", "width": 800, "height": 480}, False),
    ({"prompt": "x", "length": 50}, False),
    ({"prompt": "x", "steps": 31}, False),
    ({"prompt": "x", "fps": 30}, False),
    ({"prompt": "x", "seed": -1}, False),
    ({"prompt": "x", "workflow": {}}, False),
    ({"prompt": "x", "image": base64.b64encode(png()).decode()}, False),
    ({"prompt": "x"}, True),
])
def test_video_request_rejects_unbounded_or_untrusted_inputs(payload, animate):
    with pytest.raises(ValueError):
        broker.validate_video_request(payload, animate=animate)


def test_saved_media_finds_nested_mp4_only():
    entry = {"gifs": [{"filename": "ORCA/video_00001.mp4", "subfolder": "ORCA", "type": "output"}]}
    assert broker._saved_media(entry, ".mp4")["filename"].endswith(".mp4")
    assert broker._saved_media(entry, ".png") is None


def test_video_readiness_uses_running_engine_catalog_not_protected_files(monkeypatch):
    def request(method, path, body=None, **kwargs):
        assert method == "GET"
        names = {
            "/object_info/UNETLoader": broker.VIDEO_MODEL,
            "/object_info/VAELoader": broker.VIDEO_VAE,
            "/object_info/CLIPLoader": broker.VIDEO_ENCODER,
        }
        return {"node": {"input": {"required": {"model": [[names[path]]]}}}}
    monkeypatch.setattr(broker, "comfy_json", request)
    assert broker.video_model_ready() is True

    monkeypatch.setattr(broker, "comfy_json", lambda *args, **kwargs: {})
    assert broker.video_model_ready() is False
