"""Model adapters — abstract interface + concrete implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, List, Optional
import os
import json
import re

from .errors import OrcaConfigError
from .pricing import DEFAULT_MODEL


def _env(*names: str, default: str = "") -> str:
    for n in names:
        v = os.getenv(n)
        if v:
            return v
    return default


def _pi_profile() -> bool:
    return (os.environ.get("ORCA_PROFILE") or "").lower() in {"pi5", "pi", "power"}


def _redact(text: str) -> str:
    return re.sub(r"(sk-|xai-|Bearer )\S+", r"\1[REDACTED]", str(text))


@dataclass
class ModelResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    raw: Any = None
    tool_calls: List[dict] = field(default_factory=list)


class ModelAdapter(ABC):
    name: str = "base"

    @abstractmethod
    def complete(
        self,
        system: str,
        user: str,
        tools: Optional[List[dict]] = None,
        **kwargs,
    ) -> ModelResponse:
        ...


class EchoModel(ModelAdapter):
    """Deterministic local model for testing — no API calls."""

    name = "echo"

    def complete(
        self,
        system: str,
        user: str,
        tools: Optional[List[dict]] = None,
        **kwargs,
    ) -> ModelResponse:
        text = f"[{self.name}] {user[:200]}"
        tool_calls = []
        if tools:
            for t in tools:
                tname = t.get("name") or t.get("function", {}).get("name")
                if tname and tname in user:
                    tool_calls.append({"name": tname, "arguments": {"text": user}})
                    text = f"[echo] calling tool {tname}"
                    break
        return ModelResponse(
            text=text,
            input_tokens=max(1, len(user) // 4),
            output_tokens=max(1, len(text) // 4),
            tool_calls=tool_calls,
        )


class OpenAICompatibleModel(ModelAdapter):
    """OpenAI / xAI / any OpenAI-compatible endpoint."""

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.model = model or _env("ORCA_MODEL", "MAO_MODEL", default=DEFAULT_MODEL)
        self.api_key = api_key or _env("ORCA_API_KEY", "MAO_API_KEY")
        self.base_url = (
            base_url or _env("ORCA_BASE_URL", "MAO_BASE_URL", default="https://api.x.ai/v1")
        ).rstrip("/")
        self.name = self.model

    def complete(
        self,
        system: str,
        user: str,
        tools: Optional[List[dict]] = None,
        **kwargs,
    ) -> ModelResponse:
        if not self.api_key:
            if _pi_profile():
                raise OrcaConfigError(
                    "PI5 profile requires ORCA_API_KEY — silent Echo is forbidden"
                )
            return EchoModel().complete(system, user, tools=tools, **kwargs)

        try:
            import urllib.request

            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
            payload: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": kwargs.get("temperature", 0.4),
            }
            if tools:
                payload["tools"] = [
                    {
                        "type": "function",
                        "function": {
                            "name": t["name"],
                            "description": t.get("description", ""),
                            "parameters": {
                                "type": "object",
                                "properties": t.get("parameters", {}),
                            },
                        },
                    }
                    for t in tools
                ]
                payload["tool_choice"] = "auto"

            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=90) as resp:
                body = json.loads(resp.read().decode())

            choice = body["choices"][0]["message"]
            text = choice.get("content") or ""
            tool_calls = []
            for tc in choice.get("tool_calls") or []:
                fn = tc.get("function", {})
                args = fn.get("arguments", "{}")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {"raw": args}
                tool_calls.append({"name": fn.get("name"), "arguments": args})

            usage = body.get("usage", {})
            return ModelResponse(
                text=text,
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                raw=body,
                tool_calls=tool_calls,
            )
        except OrcaConfigError:
            raise
        except Exception as e:
            raise OrcaConfigError(f"model transport error: {_redact(e)}") from e


def get_default_model() -> ModelAdapter:
    key = _env("ORCA_API_KEY", "MAO_API_KEY")
    if _pi_profile() and not key:
        raise OrcaConfigError(
            "PI5 profile requires ORCA_API_KEY — silent Echo is forbidden"
        )
    if key:
        return OpenAICompatibleModel()
    return EchoModel()
