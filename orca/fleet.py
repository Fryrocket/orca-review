from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import hmac
import json
import time
import re


@dataclass(frozen=True)
class Heartbeat:
    node_id: str
    timestamp: int
    nonce: int
    state: str
    detail: str = ""

    def canonical(self) -> bytes:
        return json.dumps({
            "detail": self.detail, "node_id": self.node_id, "nonce": self.nonce,
            "state": self.state, "timestamp": self.timestamp,
        }, sort_keys=True, separators=(",", ":")).encode()


def key_fingerprint(key: bytes) -> str:
    if type(key) is not bytes or len(key) < 32:
        raise ValueError("node key must contain at least 32 bytes")
    return sha256(key).hexdigest()


def sign_heartbeat(heartbeat: Heartbeat, key: bytes) -> str:
    return hmac.new(key, heartbeat.canonical(), sha256).hexdigest()


class FleetAuthenticator:
    def __init__(self, enrollments: dict[str, dict], max_clock_skew_seconds: int = 120) -> None:
        if type(max_clock_skew_seconds) is not int or max_clock_skew_seconds <= 0:
            raise ValueError("heartbeat clock skew must be a positive integer")
        self.enrollments = enrollments
        self.max_clock_skew_seconds = max_clock_skew_seconds

    def enroll(self, node_id: str, key: bytes) -> dict:
        fingerprint = key_fingerprint(key)
        existing = self.enrollments.get(node_id)
        if existing and existing["key_fingerprint"] == fingerprint:
            return existing
        record = {"key_fingerprint": fingerprint, "last_nonce": -1,
                  "last_seen_epoch": None,
                  "authenticated": True}
        self.enrollments[node_id] = record
        return record

    def verify(self, heartbeat: Heartbeat, signature: str, key: bytes,
               now: int | None = None) -> int:
        if (not isinstance(heartbeat.node_id, str)
                or type(heartbeat.timestamp) is not int
                or type(heartbeat.nonce) is not int or heartbeat.nonce < 0
                or not isinstance(heartbeat.state, str)
                or not isinstance(heartbeat.detail, str)):
            raise ValueError("heartbeat fields have invalid types")
        if now is not None and type(now) is not int:
            raise ValueError("heartbeat verification time must be an integer")
        record = self.enrollments.get(heartbeat.node_id)
        if not record or record["key_fingerprint"] != key_fingerprint(key):
            raise PermissionError("node is not enrolled with this key")
        if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-f]{64}", signature):
            raise PermissionError("invalid heartbeat signature")
        current = int(time.time()) if now is None else now
        if abs(current - heartbeat.timestamp) > self.max_clock_skew_seconds:
            raise PermissionError("heartbeat timestamp is stale or in the future")
        if heartbeat.nonce <= int(record.get("last_nonce", -1)):
            raise PermissionError("heartbeat replay detected")
        expected = sign_heartbeat(heartbeat, key)
        if not hmac.compare_digest(expected, signature):
            raise PermissionError("invalid heartbeat signature")
        record["last_nonce"] = heartbeat.nonce
        # Freshness is based on the trusted receiver clock, never the client
        # timestamp (which may legally be ahead within the skew window).
        record["last_seen_epoch"] = current
        return current
