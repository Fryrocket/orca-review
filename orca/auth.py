from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import hmac
import json
import os
from pathlib import Path
import stat

from .registry import AGENTS


class IdentityAuthenticationError(Exception):
    """The request did not prove a configured ORCA identity."""


class IdentityAuthorizationError(Exception):
    """The authenticated identity attempted to act as another identity."""


class IdentityTokenAuthenticator:
    """In-memory identity tokens stored only as SHA-256 digests.

    Tokens are bootstrap credentials for the loopback control plane.  They are
    deliberately not persisted to control state, evidence, logs, or snapshots.
    """

    def __init__(self, credentials: Mapping[str, str]) -> None:
        if not isinstance(credentials, Mapping) or not credentials:
            raise ValueError("identity tokens must be a non-empty mapping")
        digests: dict[str, bytes] = {}
        seen: set[bytes] = set()
        for identity, token in credentials.items():
            if not isinstance(identity, str) or identity not in AGENTS:
                raise ValueError("identity tokens require registered identities")
            if not isinstance(token, str) or not 32 <= len(token) <= 512:
                raise ValueError("identity tokens must contain 32-512 characters")
            digest = sha256(token.encode("utf-8")).digest()
            if digest in seen:
                raise ValueError("identity tokens must be unique per identity")
            seen.add(digest)
            digests[identity] = digest
        self._digests = digests
        self._dummy_digest = sha256(b"orca-unconfigured-identity").digest()

    @property
    def identities(self) -> frozenset[str]:
        return frozenset(self._digests)

    def authenticate(self, identity: str, token: str) -> str:
        candidate = sha256(token.encode("utf-8")).digest() if isinstance(token, str) else b""
        expected = self._digests.get(identity, self._dummy_digest)
        valid = (
            isinstance(identity, str)
            and identity in self._digests
            and isinstance(token, str)
            and hmac.compare_digest(expected, candidate)
        )
        if not valid:
            raise IdentityAuthenticationError("identity authentication required")
        return identity


def load_identity_authenticator(path: str | Path) -> IdentityTokenAuthenticator:
    """Load and immediately digest credentials from an owner-only JSON file."""

    token_path = Path(path)
    try:
        metadata = token_path.lstat()
    except OSError as exc:
        raise ValueError("identity token file is unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("identity token file must be a regular non-symlink file")
    if metadata.st_size <= 0 or metadata.st_size > 65_536:
        raise ValueError("identity token file must contain 1-65536 bytes")
    if os.name == "posix" and metadata.st_mode & 0o077:
        raise ValueError("identity token file must not be accessible by group or others")
    if os.name == "posix" and metadata.st_uid != os.geteuid():
        raise ValueError("identity token file must be owned by the current user")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(token_path, flags)
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            opened = os.fstat(handle.fileno())
            if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
                raise ValueError("identity token file changed while opening")
            payload = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("identity token file must contain a JSON object") from exc
    if not isinstance(payload, dict):
        raise ValueError("identity token file must contain a JSON object")
    return IdentityTokenAuthenticator(payload)
