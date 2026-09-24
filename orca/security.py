from __future__ import annotations

import re
from typing import Any


_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"\b(xai-|sk-)[A-Za-z0-9_-]{12,}"),
    re.compile(
        r"\b(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|"
        r"xox[baprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{30,}|"
        r"(?:AKIA|ASIA)[A-Z0-9]{16})\b"
    ),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(api[_ -]?key|token|password|secret)\s*[:=]\s*[^\s,;]{8,}"),
)

_SECRET_FIELDS = frozenset({
    "apikey", "token", "accesstoken", "refreshtoken", "idtoken",
    "password", "passwd", "secret", "clientsecret", "authorization",
    "proxyauthorization", "cookie", "setcookie", "privatekey",
    "operatortoken", "nodesecret", "secretaccesskey",
})


def find_secret_match(value: str) -> re.Match[str] | None:
    matches = (match for pattern in _SECRET_PATTERNS if (match := pattern.search(value)))
    return min(matches, key=lambda match: match.start(), default=None)


def redact_text(value: str) -> str:
    result = value
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result


def redact(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {
            redact_text(str(key)): (
                "[REDACTED]" if re.sub(r"[^a-z0-9]", "", str(key).lower()) in _SECRET_FIELDS
                else redact(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    return value
