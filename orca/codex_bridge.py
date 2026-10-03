#!/usr/bin/env python3
"""Bounded OpenAI-compatible bridge to the authenticated Codex CLI on KILN.

The bridge deliberately exposes only chat completion shaped requests on loopback.
Codex runs ephemerally, in a read-only sandbox, from an empty workspace. ORCA
continues to own tools, approvals, memory, evidence, and all side effects.
"""

from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Lock


MAX_REQUEST_BYTES = 128_000
MAX_PROMPT_CHARS = 64_000
MAX_OUTPUT_BYTES = 256_000


def _validated_request(payload: object) -> tuple[str, dict]:
    if not isinstance(payload, dict):
        raise ValueError("request must be a JSON object")
    if payload.get("model") != "ORCA-CODEX":
        raise PermissionError("model is not allowlisted")
    if payload.get("stream") is not False:
        raise ValueError("streaming is not supported")
    messages = payload.get("messages")
    if not isinstance(messages, list) or not 1 <= len(messages) <= 24:
        raise ValueError("messages must contain 1-24 entries")
    rendered = []
    total = 0
    for item in messages:
        if (not isinstance(item, dict) or set(item) != {"role", "content"}
                or item["role"] not in {"system", "user", "assistant"}
                or not isinstance(item["content"], str)):
            raise ValueError("messages have an invalid schema")
        total += len(item["content"])
        if total > MAX_PROMPT_CHARS:
            raise ValueError("messages exceed the prompt limit")
        rendered.append(f"<{item['role']}>\n{item['content']}\n</{item['role']}>")
    response_format = payload.get("response_format")
    if (not isinstance(response_format, dict)
            or response_format.get("type") != "json_schema"
            or not isinstance(response_format.get("json_schema"), dict)
            or not isinstance(response_format["json_schema"].get("schema"), dict)):
        raise ValueError("a JSON response schema is required")
    schema = response_format["json_schema"]["schema"]
    encoded_schema = json.dumps(schema, separators=(",", ":"), allow_nan=False)
    if len(encoded_schema) > 32_000:
        raise ValueError("response schema exceeds the limit")
    prompt = (
        "You are an authenticated OpenAI Codex reasoning provider. Follow the identity "
        "and mission declared by the supplied system message. Work only from "
        "the conversation below. Do not inspect files, run shell commands, browse, "
        "or perform external actions in this provider process. The calling application "
        "separately owns tools, memory, approvals, and execution. Never claim a tool, "
        "test, deployment, file read, or external "
        "action occurred unless an ORCA message explicitly supplies verified evidence "
        "of it. When no verified tool evidence is supplied, describe the evidence as "
        "conversation-only and state that no tools were executed. Return only one JSON "
        "object matching the supplied output "
        "schema. Conversation roles follow.\n\n" + "\n\n".join(rendered)
    )
    return prompt, schema


def run_codex(*, codex: str, workspace: Path, prompt: str, schema: dict,
              timeout_seconds: int) -> str:
    workspace.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="orca-codex-") as temporary:
        temporary_path = Path(temporary)
        schema_path = temporary_path / "schema.json"
        output_path = temporary_path / "answer.json"
        schema_path.write_text(json.dumps(schema, allow_nan=False), encoding="utf-8")
        command = [
            codex, "exec", "--ephemeral", "--ignore-user-config",
            "--skip-git-repo-check", "--sandbox", "read-only",
            "--color", "never", "--cd", str(workspace),
            "--output-schema", str(schema_path),
            "--output-last-message", str(output_path), "-",
        ]
        try:
            completed = subprocess.run(
                command, input=prompt, text=True, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, timeout=timeout_seconds, check=False,
                env={**os.environ, "NO_COLOR": "1"},
            )
        except (OSError, subprocess.TimeoutExpired):
            raise RuntimeError("Codex execution is unavailable") from None
        if completed.returncode != 0 or not output_path.is_file():
            # Record only Codex's bounded diagnostic stream. The prompt and
            # model output are never written to the service journal.
            diagnostic = (completed.stderr or "")[-4_000:].strip()
            if diagnostic:
                print(f"Codex bridge execution diagnostic: {diagnostic}", file=sys.stderr,
                      flush=True)
            raise RuntimeError("Codex execution failed")
        raw = output_path.read_bytes()
        if not raw or len(raw) > MAX_OUTPUT_BYTES:
            raise ValueError("Codex output is missing or exceeds the limit")
        try:
            decoded = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("Codex output is not valid JSON") from None
        if not isinstance(decoded, dict):
            raise ValueError("Codex output must be a JSON object")
        return json.dumps(decoded, separators=(",", ":"), allow_nan=False)


class CodexBridgeServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], *, codex: str, workspace: Path,
                 timeout_seconds: int = 300):
        if address[0] not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Codex bridge must bind to loopback")
        self.codex = codex
        self.workspace = workspace
        self.timeout_seconds = timeout_seconds
        self.execution_lock = Lock()
        super().__init__(address, CodexBridgeHandler)


class CodexBridgeHandler(BaseHTTPRequestHandler):
    server: CodexBridgeServer

    def log_message(self, format: str, *args) -> None:
        return

    def _json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path != "/health":
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        self._json({"status": "healthy", "provider": "Codex on KILN",
                    "execution": "ephemeral-read-only"})

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        if self.headers.get_content_type() != "application/json":
            self._json({"error": "content type must be application/json"},
                       HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_REQUEST_BYTES:
                raise ValueError("request body exceeds the limit")
            payload = json.loads(self.rfile.read(length))
            prompt, schema = _validated_request(payload)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        except PermissionError as exc:
            self._json({"error": str(exc)}, HTTPStatus.FORBIDDEN)
            return
        if not self.server.execution_lock.acquire(blocking=False):
            self._json({"error": "Codex is already handling another ORCA turn"},
                       HTTPStatus.SERVICE_UNAVAILABLE)
            return
        try:
            content = run_codex(
                codex=self.server.codex, workspace=self.server.workspace,
                prompt=prompt, schema=schema,
                timeout_seconds=self.server.timeout_seconds,
            )
        except (RuntimeError, ValueError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_GATEWAY)
            return
        finally:
            self.server.execution_lock.release()
        self._json({"id": "orca-codex", "object": "chat.completion",
                    "model": "ORCA-CODEX", "choices": [{"index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop"}]})


def main() -> None:
    parser = argparse.ArgumentParser(description="ORCA Codex bridge for KILN")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=11437)
    parser.add_argument("--codex", default="/home/fryrocket/.npm-global/bin/codex")
    parser.add_argument("--workspace", default="/var/lib/orca-codex/workspace")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    if not 30 <= args.timeout <= 900:
        parser.error("timeout must be 30-900 seconds")
    CodexBridgeServer(
        (args.host, args.port), codex=args.codex,
        workspace=Path(args.workspace), timeout_seconds=args.timeout,
    ).serve_forever()


if __name__ == "__main__":
    main()
