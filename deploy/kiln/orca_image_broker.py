#!/usr/bin/env python3
"""Loopback-only, one-job-at-a-time SDXL broker for KILN Studio."""

from __future__ import annotations

import argparse
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import random
import subprocess
import threading
import time
from urllib.parse import urlencode


COMFY_HOST = "127.0.0.1"
COMFY_PORT = 8188
CHECKPOINT = "sd_xl_base_1.0.safetensors"
MAX_BODY_BYTES = 16_384
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
    return {
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
                    "worker": IMAGE_WORKER}, 200)

    def do_POST(self) -> None:
        if self.path != "/generate":
            self._json({"error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY_BYTES:
                raise ValueError("image request body is empty or too large")
            request = validate_request(json.loads(self.rfile.read(length)))
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
