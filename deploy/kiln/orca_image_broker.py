#!/usr/bin/env python3
"""Loopback-only, one-job-at-a-time SDXL broker for KILN Studio."""

from __future__ import annotations

import argparse
import base64
import binascii
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import random
import math
import struct
import zlib
import subprocess
import threading
import time
from urllib.parse import urlencode


COMFY_HOST = "127.0.0.1"
COMFY_PORT = 8188
CHECKPOINT = "sd_xl_base_1.0.safetensors"
MAX_BODY_BYTES = 16_384
MAX_EDIT_BODY_BYTES = 8_000_000
JOB_LOCK = threading.Lock()
MANAGED_ENGINE = os.environ.get("ORCA_IMAGE_MANAGED_ENGINE", "1") == "1"
IMAGE_WORKER = os.environ.get("ORCA_IMAGE_WORKER", "KILN")


def validate_request(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) - {
            "prompt", "negative_prompt", "width", "height", "steps", "seed"}:
        raise ValueError("image request has an invalid schema")
    prompt = value.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 1_500:
        raise ValueError("prompt must contain 1-1500 characters")
    negative = value.get(
        "negative_prompt",
        "text, watermark, logo, low quality, blurry, distorted, malformed",
    )
    if not isinstance(negative, str) or len(negative) > 1_000:
        raise ValueError("negative_prompt must contain at most 1000 characters")
    width = value.get("width", 768)
    height = value.get("height", 768)
    if (type(width) is not int or type(height) is not int
            or width not in {512, 640, 768} or height not in {512, 640, 768}
            or width * height > 589_824):
        raise ValueError("dimensions must be 512, 640, or 768 and at most 768x768")
    steps = value.get("steps", 20)
    if type(steps) is not int or not 1 <= steps <= 30:
        raise ValueError("steps must be an integer from 1 to 30")
    seed = value.get("seed")
    if seed is None:
        seed = random.SystemRandom().randrange(0, 2**63)
    if type(seed) is not int or not 0 <= seed < 2**63:
        raise ValueError("seed must be an integer from 0 through 2^63-1")
    return {
        "prompt": prompt.strip(), "negative_prompt": negative.strip(),
        "width": width, "height": height, "steps": steps, "seed": seed,
    }


def build_workflow(request: dict[str, object]) -> dict[str, object]:
    workflow = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {
            "ckpt_name": CHECKPOINT}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {
            "text": request["prompt"], "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {
            "text": request["negative_prompt"], "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {
            "width": request["width"], "height": request["height"], "batch_size": 1}},
        "5": {"class_type": "KSampler", "inputs": {
            "seed": request["seed"], "steps": request["steps"], "cfg": 7.0,
            "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0,
            "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0],
            "latent_image": ["4", 0]}},
        "6": {"class_type": "VAEDecode", "inputs": {
            "samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {
            "filename_prefix": "ORCA/KILN", "images": ["6", 0]}},
    }
    if "image_bytes" in request:
        workflow["8"] = {"class_type": "LoadImage", "inputs": {"image": "orca-edit-source.png [temp]"}}
        workflow["4"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["8", 0], "vae": ["1", 2]}}
        workflow["5"]["inputs"]["denoise"] = request["strength"]
        if "mask_bytes" in request:
            workflow["9"] = {"class_type": "LoadImage", "inputs": {"image": "orca-edit-mask.png [temp]"}}
            workflow["10"] = {"class_type": "ImageToMask", "inputs": {"image": ["9", 0], "channel": "red"}}
            workflow["4"] = {"class_type": "VAEEncodeForInpaint", "inputs": {
                "pixels": ["8", 0], "vae": ["1", 2], "mask": ["10", 0], "grow_mask_by": 6}}
            # Composite onto the original so unselected pixels stay unchanged.
            workflow["11"] = {"class_type": "ImageCompositeMasked", "inputs": {
                "destination": ["8", 0], "source": ["6", 0], "mask": ["10", 0],
                "x": 0, "y": 0, "resize_source": False}}
            workflow["7"]["inputs"]["images"] = ["11", 0]
    return workflow


def decode_png(value):
    """Accept only bounded, single-frame 8-bit RGB/RGBA PNGs; strip metadata."""
    if not isinstance(value, str) or len(value) > 4_000_000:
        raise ValueError("image must be a bounded base64 PNG")
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("invalid image encoding") from None
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("image must be PNG")
    offset, compressed, kept, dimensions = 8, bytearray(), [], None
    ended = False
    while offset + 12 <= len(raw):
        size = struct.unpack(">I", raw[offset:offset+4])[0]
        kind = raw[offset+4:offset+8]
        end = offset + size + 12
        if end > len(raw):
            raise ValueError("truncated PNG")
        data = raw[offset+8:end-4]
        if zlib.crc32(kind + data) & 0xffffffff != struct.unpack(">I", raw[end-4:end])[0]:
            raise ValueError("invalid PNG checksum")
        if kind == b"IHDR":
            if offset != 8 or size != 13:
                raise ValueError("invalid PNG header")
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", data)
            if (not 64 <= width <= 768 or not 64 <= height <= 768 or width % 8 or height % 8
                    or depth != 8 or color not in (2, 6) or compression or filtering or interlace):
                raise ValueError("PNG must be RGB/RGBA, 64-768 pixels, with dimensions divisible by 8")
            dimensions = (width, height)
            expected = (width * (3 if color == 2 else 4) + 1) * height
        elif kind == b"IDAT" and dimensions:
            compressed.extend(data)
        elif kind == b"IEND" and size == 0:
            ended = True
        elif kind == b"acTL" or kind[:1].isupper():
            raise ValueError("unsupported PNG format")
        if kind in (b"IHDR", b"IDAT", b"IEND"):
            kept.append(raw[offset:end])
        offset = end
        if ended:
            break
    if not dimensions or not ended or offset != len(raw):
        raise ValueError("incomplete PNG")
    try:
        decoder = zlib.decompressobj()
        pixels = decoder.decompress(bytes(compressed), expected + 1)
        if len(pixels) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError("invalid PNG pixel data")
    except zlib.error:
        raise ValueError("invalid PNG compression") from None
    return b"\x89PNG\r\n\x1a\n" + b"".join(kept), dimensions


def validate_edit_request(value):
    if not isinstance(value, dict) or set(value) - {
            "prompt", "negative_prompt", "steps", "seed", "image", "mask", "strength"}:
        raise ValueError("edit request has an invalid schema")
    request = validate_request({k: v for k, v in value.items()
                                if k in {"prompt", "negative_prompt", "steps", "seed"}})
    strength = value.get("strength", .65)
    if type(strength) not in (float, int) or not math.isfinite(strength) or not .1 <= strength <= 1:
        raise ValueError("edit strength must be between 0.1 and 1")
    request["strength"] = strength
    request["image_bytes"], dimensions = decode_png(value.get("image"))
    request["width"], request["height"] = dimensions
    if "mask" in value:
        request["mask_bytes"], mask_dimensions = decode_png(value["mask"])
        if dimensions != mask_dimensions:
            raise ValueError("mask must match image dimensions")
    return request


def upload_edit_image(content, filename):
    # Names are broker-owned constants, never user-supplied paths.
    boundary = "orca-image-upload-boundary"
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="type"\r\n\r\ntemp\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{filename}"\r\n'
            'Content-Type: image/png\r\n\r\n').encode() + content + f'\r\n--{boundary}--\r\n'.encode()
    connection = HTTPConnection(COMFY_HOST, COMFY_PORT, timeout=20)
    try:
        connection.request("POST", "/upload/image", body=body,
                           headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        response = connection.getresponse()
        result = json.loads(response.read())
        if response.status != 200 or result.get("name") != filename or result.get("type") != "temp":
            raise RuntimeError("local image upload failed")
    finally:
        connection.close()


def comfy_json(method: str, path: str, body: object | None = None, timeout: int = 15):
    connection = HTTPConnection(COMFY_HOST, COMFY_PORT, timeout=timeout)
    payload = None if body is None else json.dumps(body).encode()
    headers = {} if payload is None else {"Content-Type": "application/json"}
    try:
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        data = response.read()
        if response.status >= 400:
            raise RuntimeError(f"ComfyUI returned HTTP {response.status}")
        if not data and path == "/free":
            return {}
        return json.loads(data)
    finally:
        connection.close()


def wait_for_comfy(deadline: float) -> None:
    while time.monotonic() < deadline:
        try:
            comfy_json("GET", "/system_stats", timeout=3)
            return
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
            time.sleep(1)
    raise TimeoutError(f"{IMAGE_WORKER} image engine did not become ready")


def generate_image(request: dict[str, object]) -> tuple[bytes, str]:
    try:
        if MANAGED_ENGINE:
            subprocess.run(
                ["/usr/bin/systemctl", "start", "orca-comfyui.service"],
                check=True, timeout=150)
        wait_for_comfy(time.monotonic() + 120)
        if "image_bytes" in request:
            upload_edit_image(request["image_bytes"], "orca-edit-source.png")
        if "mask_bytes" in request:
            upload_edit_image(request["mask_bytes"], "orca-edit-mask.png")
        queued = comfy_json("POST", "/prompt", {
            "prompt": build_workflow(request), "client_id": "orca-kiln-studio"}, timeout=15)
        prompt_id = queued.get("prompt_id")
        if not isinstance(prompt_id, str):
            raise RuntimeError("ComfyUI did not return a prompt id")
        deadline = time.monotonic() + 300
        image = None
        while time.monotonic() < deadline:
            history = comfy_json("GET", f"/history/{prompt_id}", timeout=10)
            entry = history.get(prompt_id, {})
            images = entry.get("outputs", {}).get("7", {}).get("images", [])
            if images:
                image = images[0]
                break
            status = entry.get("status", {})
            if status.get("status_str") == "error":
                raise RuntimeError("ComfyUI reported an image-generation error")
            time.sleep(1)
        if not image:
            raise TimeoutError(f"{IMAGE_WORKER} image generation timed out")
        query = urlencode({
            "filename": image["filename"], "subfolder": image.get("subfolder", ""),
            "type": image.get("type", "output")})
        connection = HTTPConnection(COMFY_HOST, COMFY_PORT, timeout=30)
        try:
            connection.request("GET", f"/view?{query}")
            response = connection.getresponse()
            content = response.read()
            if response.status != 200 or not content:
                raise RuntimeError("ComfyUI image retrieval failed")
            return content, prompt_id
        finally:
            connection.close()
    finally:
        if MANAGED_ENGINE:
            subprocess.run(
                ["/usr/bin/systemctl", "stop", "orca-comfyui.service"],
                check=False, timeout=60)
            subprocess.run(
                ["/usr/bin/systemctl", "start", "quench-inference.service"],
                check=False, timeout=180)
        else:
            comfy_json("POST", "/free", {"unload_models": True, "free_memory": True})


class ImageBroker(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        return

    def _json(self, payload: dict[str, object], status: int) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path != "/health":
            self._json({"error": "not found"}, 404)
            return
        self._json({"status": "healthy", "engine": "ComfyUI", "model": CHECKPOINT,
                    "capabilities": ["generate", "image_to_image", "masked_edit"],
                    "worker": IMAGE_WORKER}, 200)

    def do_POST(self) -> None:
        if self.path not in {"/generate", "/edit"}:
            self._json({"error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            limit = MAX_EDIT_BODY_BYTES if self.path == "/edit" else MAX_BODY_BYTES
            if not 0 < length <= limit:
                raise ValueError("image request body is empty or too large")
            validator = validate_edit_request if self.path == "/edit" else validate_request
            request = validator(json.loads(self.rfile.read(length)))
        except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, 400)
            return
        if not JOB_LOCK.acquire(blocking=False):
            self._json({"error": f"{IMAGE_WORKER} is already generating an image"}, 409)
            return
        try:
            content, prompt_id = generate_image(request)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("X-ORCA-Image-Seed", str(request["seed"]))
            self.send_header("X-ORCA-Image-Worker", IMAGE_WORKER)
            self.send_header("X-ORCA-Comfy-Prompt", prompt_id)
            self.end_headers()
            self.wfile.write(content)
        except (OSError, RuntimeError, TimeoutError, subprocess.SubprocessError) as exc:
            self._json({"error": str(exc)}, 502)
        finally:
            JOB_LOCK.release()


def main() -> None:
    parser = argparse.ArgumentParser(description="KILN Studio image generation broker")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8790)
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), ImageBroker).serve_forever()


if __name__ == "__main__":
    main()
