from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .security import redact, redact_text
from .bots import BOT_PROGRAMS
from .tools import ReadOnlyToolBroker, ToolRequest, TOOL_ARGUMENT_SCHEMAS


@dataclass(frozen=True)
class PromptContract:
    bot_id: str
    version: str
    system: str
    required_output_fields: tuple[str, ...] = (
        "summary", "evidence", "uncertainty", "next_gate"
    )


PROMPT_CONTRACTS = {
    bot_id: PromptContract(
        bot_id, program.version, program.system_prompt()
    )
    for bot_id, program in BOT_PROGRAMS.items()
}


class OfflineEvaluator:
    allowed_fields = frozenset({"summary", "evidence", "uncertainty", "next_gate", "tool_requests"})
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
        tool_requests = output.get("tool_requests")
        if tool_requests is not None:
            if (not isinstance(tool_requests, list) or len(tool_requests) > 4
                    or not all(
                        isinstance(item, dict)
                        and set(item) == {"name", "arguments"}
                        and isinstance(item["name"], str)
                        and isinstance(item["arguments"], dict)
                        for item in tool_requests
                    )):
                failures.append("tool_requests must be a bounded list of name/arguments objects")
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


def _decode_contract_output(content: str) -> object:
    """Decode a JSON object, allowing only one otherwise-empty JSON fence."""

    candidate = content.strip()
    if candidate.startswith("```json\n") and candidate.endswith("\n```"):
        candidate = candidate[len("```json\n"):-len("\n```")].strip()
    try:
        return json.loads(
            candidate,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"invalid JSON constant: {value}")),
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError("local model response is not valid JSON") from exc


def _validated_contract_output(bot_id: str, content: object) -> dict:
    if not isinstance(content, str) or len(content) > OfflineEvaluator.max_output_chars:
        raise ValueError("local model response is missing or exceeds the size limit")
    output = _decode_contract_output(content)
    valid, failures = OfflineEvaluator().evaluate(bot_id, output)
    if not valid:
        raise ValueError("local model output failed contract: " + "; ".join(failures))
    if not isinstance(output, dict):
        raise ValueError("local model output must be a JSON object")
    output.pop("tool_requests", None)
    return output


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
        output = _decode_contract_output(raw["response"])
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

    def invoke(self, *, bot_id: str, model: str, prompt: str,
               tool_broker: ReadOnlyToolBroker | None = None) -> dict:
        if bot_id not in PROMPT_CONTRACTS:
            raise PermissionError("unknown bot runtime identity")
        if model not in self.allowed_models:
            raise PermissionError("local model is not allowlisted")
        if not isinstance(prompt, str) or not prompt or len(prompt) > self.max_prompt_chars:
            raise ValueError("prompt is empty or exceeds the local runtime limit")
        if redact_text(prompt) != prompt:
            raise ValueError("prompt contains secret-shaped data")
        contract = PROMPT_CONTRACTS[bot_id]
        if tool_broker is not None:
            available = {
                name: TOOL_ARGUMENT_SCHEMAS[name]
                for name in BOT_PROGRAMS[bot_id].tools
                if name in tool_broker.handlers and name in TOOL_ARGUMENT_SCHEMAS
            }
            if available:
                plan_payload = {
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                contract.system
                                + " Decide which read-only tools are required before answering. "
                                  "When the user explicitly names an available tool or asks to "
                                  "read, search, fetch, or inspect its source, request it. Return "
                                  "only tool_requests; use an empty list when no tool is needed. "
                                  "Available schemas: "
                                + json.dumps(available, sort_keys=True)
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "orca_tool_plan", "strict": True,
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "tool_requests": {
                                        "type": "array", "maxItems": 4,
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "name": {"type": "string", "enum": sorted(available)},
                                                "arguments": {"type": "object"},
                                            },
                                            "required": ["name", "arguments"],
                                            "additionalProperties": False,
                                        },
                                    },
                                },
                                "required": ["tool_requests"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "max_tokens": min(self.max_output_tokens, 512),
                    "temperature": 0,
                    "tools": [],
                }
                requests = None
                planning_unavailable = False
                for attempt in range(2):
                    request_payload = plan_payload
                    if attempt:
                        request_payload = {**plan_payload, "messages": [
                            {
                                "role": "system",
                                "content": (
                                    contract.system
                                    + " Your previous tool plan could not be parsed. Return only "
                                      "one compact JSON object with exactly one field named "
                                      "tool_requests. Its value must be an array of zero to four "
                                      "objects containing exactly name and arguments. Do not use "
                                      "prose, markdown, code fences, comments, or trailing commas. "
                                      "Available schemas: "
                                    + json.dumps(available, sort_keys=True)
                                ),
                            },
                            {"role": "user", "content": prompt},
                        ]}
                    raw_plan = self.transport(
                        self.endpoint, request_payload, self.timeout_seconds)
                    try:
                        plan_content = raw_plan["choices"][0]["message"]["content"]
                    except (KeyError, IndexError, TypeError) as exc:
                        if attempt:
                            planning_unavailable = True
                            break
                        continue
                    try:
                        plan = _decode_contract_output(plan_content)
                    except ValueError as exc:
                        if attempt:
                            planning_unavailable = True
                            break
                        continue
                    candidate = plan.get("tool_requests") if isinstance(plan, dict) else None
                    if (isinstance(candidate, list) and len(candidate) <= 4
                            and all(
                                isinstance(item, dict)
                                and set(item) == {"name", "arguments"}
                                and item["name"] in available
                                and isinstance(item["arguments"], dict)
                                for item in candidate
                            )):
                        requests = candidate
                        break
                    if attempt:
                        planning_unavailable = True
                        break
                if requests is None:
                    requests = []
                if planning_unavailable:
                    prompt += (
                        "\n\nNo tool evidence is available because the read-only tool plan "
                        "could not be validated. Do not claim that any read, search, fetch, "
                        "or inspection occurred; state this limitation when it matters."
                    )
                if requests:
                    results = tool_broker.execute(
                        bot_id=bot_id,
                        requests=[ToolRequest(item["name"], item["arguments"])
                                  for item in requests],
                    )
                    prompt = (
                        prompt + "\n\nVerified read-only tool results:\n"
                        + json.dumps(
                            [{"name": result.name, "output": result.output}
                             for result in results],
                            sort_keys=True, separators=(",", ":"), allow_nan=False,
                        )
                        + "\nUse only verified results for tool-derived claims."
                    )
                    if len(prompt) > self.max_prompt_chars:
                        raise ValueError("tool evidence exceeds the local runtime prompt limit")
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
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "orca_contract",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "summary": {"type": "string", "minLength": 1},
                            "evidence": {
                                "type": "array", "minItems": 1,
                                "maxItems": OfflineEvaluator.max_evidence_items,
                                "items": {"type": "string", "minLength": 1},
                            },
                            "uncertainty": {"type": "string", "minLength": 1},
                            "next_gate": {
                                "type": "string",
                                "enum": sorted(OfflineEvaluator.allowed_next_gates),
                            },
                        },
                        "required": sorted(PROMPT_CONTRACTS[bot_id].required_output_fields),
                        "additionalProperties": False,
                    },
                },
            },
            "max_tokens": self.max_output_tokens,
            "temperature": 0,
            "tools": [],
        }
        first_error = None
        for attempt in range(2):
            request_payload = payload
            if attempt:
                request_payload = {**payload, "messages": [
                    {
                        "role": "system",
                        "content": (
                            contract.system
                            + " Your previous response could not be parsed. Return only one "
                              "compact JSON object—no prose, markdown, code fences, comments, "
                              "or trailing commas—with exactly summary (string), evidence "
                              "(non-empty array of strings), uncertainty (string), and "
                              "next_gate (allowed enum value)."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ]}
            raw = self.transport(self.endpoint, request_payload, self.timeout_seconds)
            try:
                content = raw["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                error = ValueError("local model returned an invalid OpenAI-compatible envelope")
                if attempt:
                    raise error from exc
                first_error = error
                continue
            try:
                return _validated_contract_output(bot_id, content)
            except ValueError as exc:
                if attempt:
                    raise ValueError(
                        "local model response is not valid JSON or failed the contract "
                        "after one automatic retry"
                    ) from exc
                first_error = exc
        raise first_error or ValueError("local model failed the JSON contract")


def bounded_json_transport(endpoint: str, payload: dict, timeout_seconds: int) -> dict:
    """POST one bounded JSON request without forwarding credentials."""

    encoded = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
    if len(encoded) > 128_000:
        raise ValueError("local model request exceeds the size limit")
    request = Request(
        endpoint, data=encoded, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read(1_000_001)
    except (HTTPError, URLError, TimeoutError, OSError):
        raise RuntimeError("local model transport failed") from None
    if len(raw) > 1_000_000:
        raise ValueError("local model response exceeds the transport limit")
    try:
        decoded = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("local model response envelope is not valid JSON") from None
    if not isinstance(decoded, dict):
        raise ValueError("local model response envelope must be an object")
    return decoded


class ModelRuntimeGateway:
    """Explicit allowlist of accepted local services and bot identities."""

    def __init__(self, enabled_services: set[str] | frozenset[str],
                 tool_broker: ReadOnlyToolBroker | None = None) -> None:
        self.enabled_services = frozenset(enabled_services)
        self.tool_broker = tool_broker
        definitions = {
            "forge_deepseek": (
                "http://127.0.0.1:11436/v1/chat/completions",
                "DEEPSEEK-REASONER", frozenset({"orca", "smith"}),
            ),
            "forge_smith": (
                "http://127.0.0.1:11434/v1/chat/completions",
                "SMITH", frozenset({"smith"}),
            ),
            "kiln_quench": (
                "http://127.0.0.1:11435/v1/chat/completions",
                "QUENCH", frozenset({"quench", "security_gate"}),
            ),
        }
        unknown = self.enabled_services - set(definitions)
        if unknown:
            raise ValueError("unknown enabled model service")
        self._definitions = definitions

    def invoke(self, *, service_id: str, bot_id: str, prompt: str) -> dict:
        if service_id not in self.enabled_services:
            raise PermissionError("model service is disabled")
        endpoint, model, allowed_bots = self._definitions[service_id]
        if bot_id not in allowed_bots:
            raise PermissionError("bot identity is not allowed on this model service")
        adapter = SandboxedOpenAIAdapter(
            endpoint=endpoint,
            allowed_models=(model,),
            transport=bounded_json_transport,
            max_output_tokens=1_024 if service_id == "forge_deepseek" else 512,
        )
        return adapter.invoke(
            bot_id=bot_id, model=model, prompt=prompt,
            tool_broker=self.tool_broker,
        )
