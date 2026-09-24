from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable
from urllib.parse import unquote, urljoin, urlparse

from .security import redact, redact_text


class ReadTransportError(RuntimeError):
    """A connector transport failed without exposing provider error detail."""


class ReadResponseError(ValueError):
    """A connector returned data outside the bounded JSON response envelope."""


@dataclass
class _ResponseBudget:
    remaining_bytes: int
    remaining_items: int

    def consume(self, *, byte_count: int = 0, item_count: int = 1) -> None:
        self.remaining_bytes -= byte_count
        self.remaining_items -= item_count
        if self.remaining_bytes < 0:
            raise ReadResponseError("connector response exceeds the byte limit")
        if self.remaining_items < 0:
            raise ReadResponseError("connector response exceeds the item limit")


_TRANSPORT_EXCEPTION = object()


@dataclass(frozen=True)
class ReadRequest:
    connector: str
    base_url: str
    path: str


class ReadOnlyAdapter:
    """Provider-neutral read adapter with injected transport for testability.

    The limits below apply to the materialized JSON-like value returned by the
    transport.  An injected transport must independently bound wire bytes,
    decompression, and parser allocation before it returns; this adapter cannot
    undo resources already consumed while producing the Python object.
    """

    DEFAULT_MAX_RESPONSE_BYTES = 2_000_000
    DEFAULT_MAX_RESPONSE_ITEMS = 20_000
    DEFAULT_MAX_RESPONSE_DEPTH = 24

    def __init__(self, connector: str, allowed_origins: tuple[str, ...],
                 transport: Callable[[str, str], object],
                 allowed_path_prefixes: tuple[str, ...] = ("/",), *,
                 max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
                 max_response_items: int = DEFAULT_MAX_RESPONSE_ITEMS,
                 max_response_depth: int = DEFAULT_MAX_RESPONSE_DEPTH) -> None:
        if not callable(transport):
            raise TypeError("connector transport must be callable")
        if type(max_response_bytes) is not int or not 1 <= max_response_bytes <= 16_000_000:
            raise ValueError("connector response byte limit is invalid")
        if type(max_response_items) is not int or not 1 <= max_response_items <= 100_000:
            raise ValueError("connector response item limit is invalid")
        if type(max_response_depth) is not int or not 1 <= max_response_depth <= 64:
            raise ValueError("connector response depth limit is invalid")
        self.connector = connector
        self.allowed_origins = allowed_origins
        self.transport = transport
        self.allowed_path_prefixes = allowed_path_prefixes
        self.max_response_bytes = max_response_bytes
        self.max_response_items = max_response_items
        self.max_response_depth = max_response_depth

    def read(self, request: ReadRequest) -> object:
        if request.connector != self.connector:
            raise PermissionError("connector identity mismatch")
        parsed_path = urlparse(request.path)
        canonical_path = unquote(parsed_path.path)
        if (not request.path.startswith("/") or request.path.startswith("//")
                or parsed_path.scheme or parsed_path.netloc or parsed_path.query
                or parsed_path.fragment or unquote(canonical_path) != canonical_path
                or "\\" in canonical_path or "\x00" in canonical_path
                or any(segment in {".", ".."} for segment in canonical_path.split("/"))):
            raise PermissionError("connector path is not canonical")
        parsed_base = urlparse(request.base_url)
        if (parsed_base.username or parsed_base.password or parsed_base.query or parsed_base.fragment
                or parsed_base.path not in {"", "/"}):
            raise PermissionError("connector base URL is not canonical")
        origin = f"{parsed_base.scheme}://{parsed_base.netloc}"
        if origin not in self.allowed_origins:
            raise PermissionError("connector origin is not allowlisted")
        if not any(
                canonical_path.startswith(prefix) if prefix.endswith("/")
                else canonical_path == prefix or canonical_path.startswith(prefix + "/")
                for prefix in self.allowed_path_prefixes):
            raise PermissionError("connector path is outside the provider profile")
        url = urljoin(request.base_url.rstrip("/") + "/", request.path.lstrip("/"))
        final = urlparse(url)
        if f"{final.scheme}://{final.netloc}" != origin:
            raise PermissionError("connector URL escaped its allowlisted origin")
        try:
            response = self.transport("GET", url)
        except Exception:
            # Provider exceptions commonly contain response bodies, request
            # headers, or URLs. Leave the exception scope before raising so
            # none of it remains reachable through __cause__ or __context__.
            response = _TRANSPORT_EXCEPTION
        if response is _TRANSPORT_EXCEPTION:
            raise ReadTransportError("connector read transport failed") from None
        budget = _ResponseBudget(self.max_response_bytes, self.max_response_items)
        return _bounded_redact(
            response,
            budget=budget,
            depth=0,
            max_depth=self.max_response_depth,
            ancestors=set(),
        )


def _bounded_redact(
    value: object,
    *,
    budget: _ResponseBudget,
    depth: int,
    max_depth: int,
    ancestors: set[int],
) -> object:
    """Copy and redact a JSON-like provider response under strict limits."""

    if depth > max_depth:
        raise ReadResponseError("connector response exceeds the depth limit")
    if value is None or isinstance(value, bool):
        budget.consume(byte_count=4 if value is None or value is True else 5)
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        bit_length = abs(value).bit_length()
        digit_upper_bound = (
            1 if bit_length == 0
            else ((bit_length - 1) * 30_103) // 100_000 + 1
        )
        byte_upper_bound = digit_upper_bound + (1 if value < 0 else 0)
        if byte_upper_bound > budget.remaining_bytes:
            raise ReadResponseError("connector response exceeds the byte limit")
        try:
            rendered = str(value)
        except (ValueError, MemoryError):
            raise ReadResponseError(
                "connector response integer cannot be safely encoded") from None
        budget.consume(byte_count=len(rendered))
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ReadResponseError("connector response contains a non-finite number")
        budget.consume(byte_count=len(repr(value)))
        return value
    if isinstance(value, str):
        # Check character count first so a hostile transport cannot force a
        # disproportionately large temporary UTF-8 allocation.
        if len(value) > budget.remaining_bytes:
            raise ReadResponseError("connector response exceeds the byte limit")
        encoded_size = len(value.encode("utf-8"))
        budget.consume(byte_count=encoded_size)
        return redact_text(value)
    if not isinstance(value, (dict, list, tuple)):
        raise ReadResponseError("connector response must contain only JSON-compatible data")

    identity = id(value)
    if identity in ancestors:
        raise ReadResponseError("connector response contains a cycle")
    minimum_items = len(value) + 1
    if isinstance(value, dict):
        minimum_items += len(value)
    if minimum_items > budget.remaining_items:
        raise ReadResponseError("connector response exceeds the item limit")
    ancestors.add(identity)
    try:
        budget.consume()
        if isinstance(value, dict):
            copied: dict[str, object] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ReadResponseError("connector response object keys must be strings")
                safe_key = _bounded_redact(
                    key, budget=budget, depth=depth + 1,
                    max_depth=max_depth, ancestors=ancestors)
                # Determine field sensitivity before traversing its value.  Use
                # the canonical field-name policy without recursively redacting
                # the unbounded provider value ahead of the response budget.
                field_probe = redact({key: None})
                field_is_secret = next(iter(field_probe.values())) == "[REDACTED]"
                if safe_key in copied:
                    raise ReadResponseError(
                        "connector response keys collide after redaction")
                safe_item = _bounded_redact(
                    item, budget=budget, depth=depth + 1,
                    max_depth=max_depth, ancestors=ancestors)
                if field_is_secret:
                    # Count the replacement as well as validating/bounding the
                    # original value.  This is deliberately conservative.
                    budget.consume(byte_count=len("[REDACTED]"), item_count=0)
                    safe_item = "[REDACTED]"
                copied[safe_key] = safe_item
            return copied
        copied_items = [
            _bounded_redact(
                item, budget=budget, depth=depth + 1,
                max_depth=max_depth, ancestors=ancestors)
            for item in value
        ]
        return tuple(copied_items) if isinstance(value, tuple) else copied_items
    finally:
        ancestors.remove(identity)


@dataclass(frozen=True)
class ProviderProfile:
    connector: str
    origins: tuple[str, ...]
    path_prefixes: tuple[str, ...]


PROVIDER_PROFILES = {
    "notion": ProviderProfile("notion", ("https://api.notion.com",), ("/v1/",)),
    "linear": ProviderProfile("linear", ("https://api.linear.app",), ("/graphql",)),
    "github": ProviderProfile("github", ("https://api.github.com",), ("/repos/", "/users/")),
    "gitea": ProviderProfile("gitea", ("http://192.168.7.30:3000",), ("/api/v1/",)),
    "drive": ProviderProfile("drive", ("https://www.googleapis.com",), ("/drive/v3/",)),
    "slack": ProviderProfile("slack", ("https://slack.com",), ("/api/",)),
    "cloudflare": ProviderProfile("cloudflare", ("https://api.cloudflare.com",), ("/client/v4/",)),
}


def provider_adapter(connector: str, transport: Callable[[str, str], object]) -> ReadOnlyAdapter:
    try:
        profile = PROVIDER_PROFILES[connector]
    except KeyError as exc:
        raise PermissionError(f"no provider profile for connector: {connector}") from exc
    return ReadOnlyAdapter(profile.connector, profile.origins, transport, profile.path_prefixes)
