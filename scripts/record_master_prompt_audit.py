#!/usr/bin/env python3
"""Append one immutable result and refresh campaign aggregates safely."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def atomic_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def append(path: Path, payload: dict) -> None:
    encoded = (json.dumps(payload, sort_keys=True) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--prompt-id", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--outcome", choices=("passed", "failed", "blocked"), required=True)
    parser.add_argument("--failure-category", default=None)
    parser.add_argument("--cause", required=True)
    parser.add_argument("--last-action", default=None)
    args = parser.parse_args()
    root = args.campaign.resolve()
    prompts = {row["prompt_id"]: row for row in
               (json.loads(line) for line in (root / "prompts.jsonl").read_text().splitlines())}
    if args.prompt_id not in prompts:
        raise SystemExit("prompt id is not in the frozen corpus")
    results_path = root / "results.jsonl"
    prior = [json.loads(line) for line in results_path.read_text().splitlines() if line]
    if any(row.get("prompt_id") == args.prompt_id for row in prior):
        raise SystemExit("prompt already has an immutable result")
    category = prompts[args.prompt_id]["category"]
    failure = args.failure_category if args.outcome != "passed" else None
    if args.outcome != "passed" and not failure:
        raise SystemExit("failure category is required for a non-pass")
    result = {
        "prompt_id": args.prompt_id, "category": category,
        "session_id": args.session_id, "outcome": args.outcome,
        "failure_category": failure, "cause": args.cause[:1200],
        "last_completed_action": args.last_action, "completed_at": now(),
    }
    result["result_sha256"] = hashlib.sha256(
        json.dumps(result, sort_keys=True).encode()).hexdigest()
    append(results_path, result)
    if args.outcome != "passed":
        append(root / "failures.jsonl", result)
    rows = prior + [result]
    by_category, by_failure = {}, {}
    for row in rows:
        by_category[row["category"]] = by_category.get(row["category"], 0) + 1
        if row.get("failure_category"):
            key = row["failure_category"]
            by_failure[key] = by_failure.get(key, 0) + 1
    attempted = len(rows)
    completed = {row["prompt_id"] for row in rows}
    next_id = next((f"{number:05d}" for number in range(1, 10001)
                    if f"{number:05d}" not in completed), None)
    summary = {
        "campaign": "campaign-10000-v1",
        "corpus_sha256": hashlib.sha256((root / "prompts.jsonl").read_bytes()).hexdigest(),
        "total_planned": 10_000, "attempted": attempted,
        "passed": sum(row["outcome"] == "passed" for row in rows),
        "failed": sum(row["outcome"] == "failed" for row in rows),
        "blocked": sum(row["outcome"] == "blocked" for row in rows),
        "remaining": 10_000 - attempted, "by_category": by_category,
        "by_failure_category": by_failure, "updated_at": now(),
    }
    atomic_json(root / "summary.json", summary)
    checkpoint = json.loads((root / "checkpoint.json").read_text())
    checkpoint.update({"next_prompt_id": next_id, "attempted": attempted,
                       "completed": next_id is None, "updated_at": now()})
    atomic_json(root / "checkpoint.json", checkpoint)
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
