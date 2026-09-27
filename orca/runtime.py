from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import json
from urllib.parse import urlparse

from .security import redact, redact_text


@dataclass(frozen=True)
class PromptContract:
    bot_id: str
    version: str
    system: str
    required_output_fields: tuple[str, ...] = (
        "summary", "evidence", "uncertainty", "next_gate"
    )


PROMPT_CONTRACTS = {
    "orca": PromptContract("orca", "1.0.0", "Route work; enforce policy and lane boundaries; never impersonate Fry."),
    "smith": PromptContract("smith", "1.0.0", "Implement only scoped work; report tests, rollback, and unresolved risk."),
    "quench": PromptContract("quench", "1.0.0", "Review independently; require evidence; never approve your own implementation."),
    "security_gate": PromptContract(
        "security_gate", "1.0.0",
        "Report security findings with redacted evidence, severity and remediation; never author, approve, deploy or reveal secrets."),
}


class OfflineEvaluator:
    allowed_fields = frozenset({"summary", "evidence", "uncertainty", "next_gate"})
    allowed_next_gates = frozenset({
        "none", "review", "quench_review", "fry_approval", "incident",
        "blocked", "block_and_escalate",
    })
    max_output_chars = 64_000
    max_evidence_items = 50

    def evaluate(self, bot_id: str, output: Any) -> tuple[bool, tuple[str, ...]]:
        contract = PROMPT_CONTRACTS[bot_id]
        failures: list[str] = []
        if not isinstance(output, dict):
            return False, ("output must be an object",)
        unexpected = sorted(set(output) - self.allowed_fields)
        if unexpected:
            failures.append("unexpected output fields: " + ", ".join(unexpected))
        for field in contract.required_output_fields:
            if field not in output or output[field] in (None, "", []):
                failures.append(f"missing required field: {field}")
        if "summary" in output and not isinstance(output["summary"], str):
            failures.append("summary must be text")
        if "uncertainty" in output and not isinstance(output["uncertainty"], str):
            failures.append("uncertainty must be text")
        evidence = output.get("evidence")
        if evidence not in (None, []) and (
                not isinstance(evidence, list)
                or not all(isinstance(item, str) and item.strip() for item in evidence)):
            failures.append("evidence must be a list of non-empty text items")
        elif isinstance(evidence, list) and len(evidence) > self.max_evidence_items:
            failures.append("evidence exceeds the item limit")
        next_gate = output.get("next_gate")
        if next_gate not in (None, "") and (
                not isinstance(next_gate, str) or next_gate not in self.allowed_next_gates):
            failures.append("next_gate is not an allowed control-plane gate")
        try:
            encoded = json.dumps(
                output, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError):
            failures.append("output must be JSON serializable")
        else:
            if len(encoded) > self.max_output_chars:
                failures.append("output exceeds the size limit")
        if redact(output) != output:
            failures.append("output contains secret-shaped data")
        return not failures, tuple(failures)


class DisabledRuntime:
    """Fail-closed placeholder until a reviewed local adapter is configured."""

    def invoke(self, bot_id: str, prompt: str) -> dict:
        raise PermissionError(f"bot runtime is disabled: {bot_id}")


class SandboxedLocalAdapter:
    """Bounded loopback-only model adapter with no tool or cloud path."""

    def __init__(self, *, endpoint: str, allowed_models: tuple[str, ...], transport,
                 timeout_seconds: int = 60, max_prompt_chars: int = 12_000,
                 max_output_tokens: int = 4_096) -> None:
        parsed = urlparse(endpoint)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("local model endpoint must be loopback HTTP")
        if (parsed.path != "/api/generate" or parsed.username or parsed.password
                or parsed.query or parsed.fragment):
            raise ValueError("local model endpoint must use /api/generate")
        if (not allowed_models
                or any(not isinstance(model, str) or not model.strip() or len(model) > 200
                       or redact_text(model) != model for model in allowed_models)):
            raise ValueError("at least one local model must be allowlisted")
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 300:
            raise ValueError("local model timeout must be 1-300 seconds")
        if type(max_prompt_chars) is not int or not 1 <= max_prompt_chars <= 64_000:
            raise ValueError("local model prompt bound must be 1-64000 characters")
        if type(max_output_tokens) is not int or not 1 <= max_output_tokens <= 32_768:
            raise ValueError("local model output bound must be 1-32768 tokens")
        self.endpoint = endpoint
        self.allowed_models = frozenset(allowed_models)
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self.max_prompt_chars = max_prompt_chars
        self.max_output_tokens = max_output_tokens

    def invoke(self, *, bot_id: str, model: str, prompt: str) -> dict:
        if bot_id not in PROMPT_CONTRACTS:
            raise PermissionError("unknown bot runtime identity")
        if model not in self.allowed_models:
            raise PermissionError("local model is not allowlisted")
        if not isinstance(prompt, str) or not prompt or len(prompt) > self.max_prompt_chars:
            raise ValueError("prompt is empty or exceeds the local runtime limit")
        if redact_text(prompt) != prompt:
            raise ValueError("prompt contains secret-shaped data")
        payload = {
            "model": model,
            "system": PROMPT_CONTRACTS[bot_id].system,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"num_predict": self.max_output_tokens},
        }
        raw = self.transport(self.endpoint, payload, self.timeout_seconds)
        if not isinstance(raw, dict) or not isinstance(raw.get("response"), str):
            raise ValueError("local model returned an invalid envelope")
        if len(raw["response"]) > OfflineEvaluator.max_output_chars:
            raise ValueError("local model response exceeds the size limit")
        try:
            output = json.loads(
                raw["response"],
                parse_constant=lambda value: (_ for _ in ()).throw(
                    ValueError(f"invalid JSON constant: {value}")),
            )
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError("local model response is not valid JSON") from exc
        valid, failures = OfflineEvaluator().evaluate(bot_id, output)
        if not valid:
            raise ValueError("local model output failed contract: " + "; ".join(failures))
        return output


class SandboxedOpenAIAdapter:
    """Bounded loopback adapter for local llama.cpp OpenAI-compatible services.

    Remote workers must be projected onto loopback through an independently
    authenticated tunnel. Direct LAN or tailnet model endpoints remain denied.
    """

    def __init__(self, *, endpoint: str, allowed_models: tuple[str, ...], transport,
                 timeout_seconds: int = 300, max_prompt_chars: int = 24_000,
                 max_output_tokens: int = 4_096) -> None:
        parsed = urlparse(endpoint)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("local OpenAI-compatible endpoint must be loopback HTTP")
        if (parsed.path != "/v1/chat/completions" or parsed.username or parsed.password
                or parsed.query or parsed.fragment):
            raise ValueError("local OpenAI-compatible endpoint must use /v1/chat/completions")
        if (not allowed_models
                or any(not isinstance(model, str) or not model.strip() or len(model) > 200
                       or redact_text(model) != model for model in allowed_models)):
            raise ValueError("at least one local model must be allowlisted")
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 900:
            raise ValueError("local model timeout must be 1-900 seconds")
        if type(max_prompt_chars) is not int or not 1 <= max_prompt_chars <= 64_000:
            raise ValueError("local model prompt bound must be 1-64000 characters")
        if type(max_output_tokens) is not int or not 1 <= max_output_tokens <= 32_768:
            raise ValueError("local model output bound must be 1-32768 tokens")
        self.endpoint = endpoint
        self.allowed_models = frozenset(allowed_models)
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self.max_prompt_chars = max_prompt_chars
        self.max_output_tokens = max_output_tokens

    def invoke(self, *, bot_id: str, model: str, prompt: str) -> dict:
        if bot_id not in PROMPT_CONTRACTS:
            raise PermissionError("unknown bot runtime identity")
        if model not in self.allowed_models:
            raise PermissionError("local model is not allowlisted")
        if not isinstance(prompt, str) or not prompt or len(prompt) > self.max_prompt_chars:
            raise ValueError("prompt is empty or exceeds the local runtime limit")
        if redact_text(prompt) != prompt:
            raise ValueError("prompt contains secret-shaped data")
        contract = PROMPT_CONTRACTS[bot_id]
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        contract.system
                        + " Return one JSON object with exactly summary, evidence, "
                          "uncertainty, and next_gate."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "response_format": {"type": "json_object"},
            "max_tokens": self.max_output_tokens,
            "tools": [],
        }
        raw = self.transport(self.endpoint, payload, self.timeout_seconds)
        try:
            content = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("local model returned an invalid OpenAI-compatible envelope") from exc
        if not isinstance(content, str) or len(content) > OfflineEvaluator.max_output_chars:
            raise ValueError("local model response is missing or exceeds the size limit")
        try:
            output = json.loads(
                content,
                parse_constant=lambda value: (_ for _ in ()).throw(
                    ValueError(f"invalid JSON constant: {value}")),
            )
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError("local model response is not valid JSON") from exc
        valid, failures = OfflineEvaluator().evaluate(bot_id, output)
        if not valid:
            raise ValueError("local model output failed contract: " + "; ".join(failures))
        return output
