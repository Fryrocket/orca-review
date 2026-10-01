#!/usr/bin/env python3
"""Independent, deterministic verifier for bounded ORCA evidence envelopes."""

import argparse
import hashlib
import json
import os
import time
from pathlib import Path


MAX_ENVELOPES = 100
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024


def verify_envelope(path, artifact_root):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        claim_id = data.get("claim_id")
        actor = data.get("actor")
        artifacts = data.get("artifacts")
        approvals = data.get("approvals", [])
        if not isinstance(claim_id, str) or not claim_id or not isinstance(actor, str):
            raise ValueError("invalid claim identity")
        if not isinstance(artifacts, list) or not artifacts:
            raise ValueError("artifact evidence missing")
        checks = []
        for artifact in artifacts:
            artifact_path = Path(artifact["path"])
            expected = artifact["sha256"]
            root = Path(artifact_root).resolve()
            resolved = artifact_path.resolve()
            if not artifact_path.is_absolute() or resolved.parent != root or len(expected) != 64:
                raise ValueError("invalid artifact reference")
            stat = resolved.stat()
            if stat.st_size > MAX_ARTIFACT_BYTES:
                raise ValueError("artifact too large")
            actual = hashlib.sha256(resolved.read_bytes()).hexdigest()
            checks.append({"name": artifact_path.name, "sha256_valid": actual == expected})
        if not isinstance(approvals, list):
            raise ValueError("invalid approvals")
        valid = all(check["sha256_valid"] for check in checks)
        return {"claim_id": claim_id, "actor": actor, "valid": valid,
                "artifact_checks": checks, "approval_count": len(approvals)}
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return {"claim_id": path.stem, "valid": False, "error": type(exc).__name__}


def evaluate(inbox, artifact_root=None, now=None):
    now = int(time.time() if now is None else now)
    paths = sorted(Path(inbox).glob("*.json"))[:MAX_ENVELOPES]
    artifact_root = Path(artifact_root) if artifact_root else Path(inbox).parent / "artifacts"
    results = [verify_envelope(path, artifact_root) for path in paths]
    return {
        "schema_version": 1,
        "bot_id": "evidence_auditor",
        "state": "healthy" if all(item["valid"] for item in results) else "degraded",
        "mode": "idle" if not results else "verified",
        "observed_epoch": now,
        "authority": "independent_read_only_verifier",
        "envelope_count": len(results),
        "valid_count": sum(bool(item["valid"]) for item in results),
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inbox", default="/var/lib/orca-evidence-auditor/inbox")
    parser.add_argument("--artifacts", default="/var/lib/orca-evidence-auditor/artifacts")
    parser.add_argument("--output", default="/var/lib/orca-evidence-auditor/status.json")
    args = parser.parse_args()
    report = evaluate(args.inbox, args.artifacts)
    target = Path(args.output)
    target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o640)
    os.replace(temporary, target)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["state"] == "healthy" else 1


if __name__ == "__main__":
    raise SystemExit(main())
