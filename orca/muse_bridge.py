#!/usr/bin/env python3
"""Bounded loopback bridge from ORCA to Meta Model API's Muse Spark."""

from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PROVIDER_URL = "https://api.meta.ai/v1/chat/completions"
ALLOWED_PROVIDER_MODELS = frozenset({
    "muse-spark-1.3", "muse-spark-1.3-contributor",
})
INTERNAL_MODEL = "ORCA-MUSE-SPARK"
MAX_REQUEST_BYTES = 128_000
MAX_RESPONSE_BYTES = 1_000_000


def _read_key(path: Path) -> str:
    key = path.read_text(encoding="utf-8").strip()
    if not 20 <= len(key) <= 512 or any(character.isspace() for character in key):
        raise ValueError("Muse credential is invalid")
    return key


def _validated_payload(payload: object, provider_model: str) -> bytes:
    if provider_model not in ALLOWED_PROVIDER_MODELS:
        raise ValueError("Muse provider model is not allowlisted")
    if not isinstance(payload, dict):
        raise ValueError("request must be a JSON object")
    if payload.get("model") != INTERNAL_MODEL:
        raise PermissionError("model is not allowlisted")
    if payload.get("stream") is not False:
        raise ValueError("streaming is not supported")
    messages = payload.get("messages")
    if not isinstance(messages, list) or not 1 <= len(messages) <= 24:
        raise ValueError("messages must contain 1-24 entries")
    total = 0
    for message in messages:
        if (not isinstance(message, dict) or message.get("role") not in
                {"system", "developer", "user", "assistant", "tool"}
                or not isinstance(message.get("content"), str)):
            raise ValueError("messages have an invalid schema")
        total += len(message["content"])
    if total > 64_000:
        raise ValueError("messages exceed the prompt limit")
    forwarded = dict(payload)
    forwarded["model"] = provider_model
    forwarded["stream"] = False
    forwarded["max_tokens"] = min(int(forwarded.get("max_tokens", 2048)), 2048)
    forwarded["reasoning_effort"] = "low"
    raw = json.dumps(forwarded, separators=(",", ":"), allow_nan=False).encode()
    if len(raw) > MAX_REQUEST_BYTES:
        raise ValueError("request body exceeds the limit")
    return raw


def _provider_call(payload: bytes, key: str, timeout_seconds: int) -> bytes:
    request = Request(PROVIDER_URL, data=payload, method="POST", headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": "ORCA-Muse-Spark-Bridge/1",
    })
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        if exc.code == HTTPStatus.TOO_MANY_REQUESTS:
            raise RuntimeError("Muse quota is temporarily exhausted") from None
        raise RuntimeError("Muse provider rejected the request") from None
    except (URLError, TimeoutError, OSError):
        raise RuntimeError("Muse provider is unavailable") from None
    if not raw or len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("Muse response is missing or exceeds the limit")
    try:
        decoded = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("Muse response is not valid JSON") from None
    if not isinstance(decoded, dict) or not isinstance(decoded.get("choices"), list):
        raise ValueError("Muse response has an invalid envelope")
    return json.dumps(decoded, separators=(",", ":"), allow_nan=False).encode()


class MuseBridgeServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], *, key_file: Path,
                 provider_model: str, timeout_seconds: int = 120):
        if address[0] not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Muse bridge must bind to loopback")
        if provider_model not in ALLOWED_PROVIDER_MODELS:
            raise ValueError("Muse provider model is not allowlisted")
        self.api_key = _read_key(key_file)
        self.provider_model = provider_model
        self.timeout_seconds = timeout_seconds
        self.execution_lock = Lock()
        super().__init__(address, MuseBridgeHandler)


class MuseBridgeHandler(BaseHTTPRequestHandler):
    server: MuseBridgeServer

    def log_message(self, format: str, *args) -> None:
        return

    def _send(self, payload: bytes, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, payload: object, status: int = 200) -> None:
        self._send(json.dumps(payload, separators=(",", ":")).encode(), status)

    def do_GET(self) -> None:
        if self.path != "/health":
            return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        self._json({"status": "healthy", "provider": "Meta Model API",
                    "model": self.server.provider_model})

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        if self.headers.get_content_type() != "application/json":
            return self._json({"error": "content type must be application/json"},
                              HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_REQUEST_BYTES:
                raise ValueError("request body exceeds the limit")
            payload = _validated_payload(
                json.loads(self.rfile.read(length)), self.server.provider_model)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except PermissionError as exc:
            return self._json({"error": str(exc)}, HTTPStatus.FORBIDDEN)
        if not self.server.execution_lock.acquire(blocking=False):
            return self._json({"error": "Muse is already handling another ORCA turn"},
                              HTTPStatus.SERVICE_UNAVAILABLE)
        try:
            result = _provider_call(payload, self.server.api_key,
                                    self.server.timeout_seconds)
        except (RuntimeError, ValueError) as exc:
            return self._json({"error": str(exc)}, HTTPStatus.BAD_GATEWAY)
        finally:
            self.server.execution_lock.release()
        self._send(result)


def main() -> None:
    parser = argparse.ArgumentParser(description="ORCA Muse Spark bridge")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=11439)
    parser.add_argument("--key-file", default="/run/credentials/orca-muse-spark.service/api-key")
    parser.add_argument("--provider-model", choices=sorted(ALLOWED_PROVIDER_MODELS),
                        required=True)
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    if not 10 <= args.timeout <= 300:
        parser.error("timeout must be 10-300 seconds")
    MuseBridgeServer((args.host, args.port), key_file=Path(args.key_file),
                     provider_model=args.provider_model,
                     timeout_seconds=args.timeout).serve_forever()


if __name__ == "__main__":
    main()
