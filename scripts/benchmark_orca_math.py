#!/usr/bin/env python3
"""Repeatable, sequential, read-only ORCA math and engineering benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import subprocess
import time
from urllib.request import Request, urlopen


ENDPOINT = "http://127.0.0.1:11436/v1/chat/completions"
NUMBER = re.compile(r"(?<![\w.])[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][+-]?\d+)?")


def close_enough(actual: float, expected: float, relative_tolerance: float) -> bool:
    return math.isfinite(actual) and abs(actual - expected) <= max(
        1e-12, abs(expected) * relative_tolerance
    )


def numbers_in_text(text: str) -> list[float]:
    values = []
    for match in NUMBER.finditer(text):
        try:
            value = float(match.group(0).replace(",", ""))
        except ValueError:
            continue
        if math.isfinite(value):
            values.append(value)
    return values


def nearest_rank(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def wilson_interval(successes: int, total: int, z: float = 1.96) -> list[float] | None:
    if total <= 0:
        return None
    proportion = successes / total
    denominator = 1 + z * z / total
    centre = (proportion + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(
        proportion * (1 - proportion) / total + z * z / (4 * total * total)
    ) / denominator
    return [max(0.0, centre - margin), min(1.0, centre + margin)]


def gpu_snapshot() -> dict:
    try:
        run = subprocess.run(
            ["/usr/bin/rocm-smi", "--showuse", "--showmemuse", "--showtemp", "--json"],
            capture_output=True, text=True, timeout=8, check=False,
        )
        return json.loads(run.stdout) if run.returncode == 0 else {"error": "rocm-smi failed"}
    except (OSError, ValueError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return {"error": "GPU telemetry unavailable"}


def direct_model_case(case: dict) -> dict:
    payload = {
        "model": "ORCA-QWEN", "stream": False,
        "messages": [
            {"role": "system", "content": (
                "You are being objectively benchmarked. Work the problem carefully. "
                "Return only the required JSON object. answer must be one finite JSON number."
            )},
            {"role": "user", "content": case["prompt"]},
        ],
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "numeric_benchmark", "strict": True,
            "schema": {"type": "object", "properties": {
                "answer": {"type": "number"}, "method": {"type": "string"}},
                "required": ["answer", "method"], "additionalProperties": False},
        }},
        "chat_template_kwargs": {"enable_thinking": False},
        "temperature": 0, "max_tokens": 256, "tools": [],
    }
    started = time.perf_counter()
    encoded = json.dumps(payload, separators=(",", ":")).encode()
    with urlopen(Request(ENDPOINT, data=encoded, method="POST",
                         headers={"Content-Type": "application/json"}), timeout=90) as response:
        envelope = json.load(response)
    elapsed = time.perf_counter() - started
    decoded = json.loads(envelope["choices"][0]["message"]["content"])
    answer = float(decoded["answer"])
    usage = envelope.get("usage", {})
    completion_tokens = usage.get("completion_tokens")
    return {
        "pass": close_enough(answer, case["expected"], case["relative_tolerance"]),
        "answer": answer,
        "expected": case["expected"],
        "relative_error": abs(answer - case["expected"]) / abs(case["expected"]),
        "latency_s": elapsed,
        "completion_tokens": completion_tokens,
        "completion_tokens_per_elapsed_s": (
            completion_tokens / elapsed if isinstance(completion_tokens, int) else None),
        "method": decoded.get("method", "")[:400],
    }


def tool_path_cases() -> list[dict]:
    from orca.calculator import calculate
    from orca.engineering import engineering_chat_calculate
    from orca.runtime import ModelRuntimeGateway
    from orca.scientific import scientific_calculate
    from orca.tools import ReadOnlyToolBroker

    gateway = ModelRuntimeGateway({"forge_qwen"}, tool_broker=ReadOnlyToolBroker({
        "math.calculate": calculate,
        "math.scientific": scientific_calculate,
        "engineering.calculate": engineering_chat_calculate,
    }))
    cases = [
        {"name": "decimal_chat", "prompt": "0.1+0.2", "expected": 0.3, "rtol": 1e-12},
        {"name": "word_problem_tool", "prompt": (
            "A crate has 37 trays with 48 fasteners each. Inspection rejects 119 fasteners. "
            "How many usable fasteners remain?"), "expected": 1657.0, "rtol": 1e-12},
        {"name": "engineering_led", "prompt": (
            "Calculate an ideal LED series resistor for a 12 V source, 2.2 V LED forward "
            "voltage, and 0.02 A target current."), "expected": 490.0, "rtol": 1e-12},
        {"name": "engineering_beam", "prompt": (
            "Calculate cantilever end deflection for force 120 N, length 0.8 m, Young modulus "
            "200e9 Pa, second moment 1.6e-6 m^4, and c=0.02 m."),
            "expected": 0.000064, "rtol": 1e-6},
    ]
    results = []
    for case in cases:
        started = time.perf_counter()
        try:
            result = gateway.chat(prompt=case["prompt"])
            summary = result.get("result", {}).get("summary", "")
            values = numbers_in_text(summary)
            results.append({
                "name": case["name"],
                "pass": any(close_enough(value, case["expected"], case["rtol"])
                            for value in values),
                "expected": case["expected"],
                "observed_numbers": values[:30],
                "latency_s": time.perf_counter() - started,
                "mode": result.get("mode"),
                "summary": summary[:1200],
            })
        except Exception as error:
            results.append({"name": case["name"], "pass": False,
                            "error": type(error).__name__})
        time.sleep(0.25)
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--repeats", type=int, default=2, choices=range(1, 6))
    parser.add_argument("--cooldown", type=float, default=0.25)
    args = parser.parse_args()
    raw = args.dataset.read_bytes()
    dataset = json.loads(raw)
    before = gpu_snapshot()
    direct_results = []
    for repeat in range(args.repeats):
        for case in dataset["cases"]:
            try:
                result = direct_model_case(case)
            except Exception as error:
                result = {"pass": False, "error": type(error).__name__}
            direct_results.append({"repeat": repeat + 1, "name": case["name"],
                                   "category": case["category"], **result})
            time.sleep(args.cooldown)
    tool_results = []
    for repeat in range(args.repeats):
        tool_results.extend({"repeat": repeat + 1, **result}
                            for result in tool_path_cases())
    after = gpu_snapshot()
    direct_passes = sum(bool(item.get("pass")) for item in direct_results)
    tool_passes = sum(bool(item.get("pass")) for item in tool_results)
    latencies = [item["latency_s"] for item in direct_results if "latency_s" in item]
    token_rates = [item["completion_tokens_per_elapsed_s"] for item in direct_results
                   if item.get("completion_tokens_per_elapsed_s") is not None]
    report = {
        "suite": dataset["suite"], "suite_version": dataset["version"],
        "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        "non_destructive": True, "sequential": True, "repeats": args.repeats,
        "model": "Qwen3.5-35B-A3B-Q4_K_M / ORCA-QWEN",
        "summary": {
            "direct_model": {"passed": direct_passes, "total": len(direct_results),
                "rate": direct_passes / len(direct_results),
                "wilson_95": wilson_interval(direct_passes, len(direct_results))},
            "orca_tool_path": {"passed": tool_passes, "total": len(tool_results),
                "rate": tool_passes / len(tool_results),
                "wilson_95": wilson_interval(tool_passes, len(tool_results))},
            "median_direct_latency_s": statistics.median(latencies) if latencies else None,
            "p95_direct_latency_s": nearest_rank(latencies, 0.95),
            "median_completion_tokens_per_elapsed_s": (
                statistics.median(token_rates) if token_rates else None),
        },
        "direct_model_trials": direct_results,
        "orca_tool_trials": tool_results,
        "gpu_before": before, "gpu_after": after,
    }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
