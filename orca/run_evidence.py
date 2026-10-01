from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


_SENSITIVE_KEYS = frozenset({
    "authorization", "cookie", "password", "secret", "token", "api_key",
    "access_key", "private_key", "credential_value",
})


def _redact(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if str(key).casefold() in _SENSITIVE_KEYS else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()


class EvidenceRunLog:
    """Append-only, hash-chained evidence for a bounded acceptance run."""

    def __init__(self, path: Path, *, run_id: str) -> None:
        self.path = Path(path)
        self.run_id = run_id
        self.sequence = 0
        self.previous_sha256 = "0" * 64
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("x", encoding="utf-8")

    def append(self, kind: str, payload: dict) -> dict:
        if not kind or not isinstance(payload, dict):
            raise ValueError("evidence event requires a kind and object payload")
        self.sequence += 1
        event = {
            "schema": "orca.acceptance-evidence.v1",
            "run_id": self.run_id,
            "sequence": self.sequence,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "payload": _redact(payload),
            "previous_sha256": self.previous_sha256,
        }
        event["event_sha256"] = hashlib.sha256(_canonical(event)).hexdigest()
        self._handle.write(json.dumps(event, sort_keys=True) + "\n")
        self._handle.flush()
        self.previous_sha256 = event["event_sha256"]
        return event

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> "EvidenceRunLog":
        return self

    def __exit__(self, *_args) -> None:
        self.close()


def verify_run_log(path: Path) -> dict:
    previous = "0" * 64
    events = 0
    run_id = None
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        claimed = event.pop("event_sha256")
        actual = hashlib.sha256(_canonical(event)).hexdigest()
        if claimed != actual or event.get("previous_sha256") != previous:
            return {"valid": False, "events": events, "run_id": run_id}
        if run_id is None:
            run_id = event.get("run_id")
        if event.get("run_id") != run_id or event.get("sequence") != events + 1:
            return {"valid": False, "events": events, "run_id": run_id}
        previous = claimed
        events += 1
    return {"valid": events > 0, "events": events, "run_id": run_id,
            "head_sha256": previous}
