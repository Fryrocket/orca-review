"""Dashboard bind + bearer-token checks. Testable without spinning HTTP."""

from __future__ import annotations

import hmac
from ipaddress import ip_address
import os

from mao.errors import OrcaConfigError

_LAN_HOSTS = {"0.0.0.0", "::", "[::]"}


def dashboard_token() -> str:
    return os.environ.get("ORCA_DASHBOARD_TOKEN") or ""


def lan_requested() -> bool:
    return (os.environ.get("ORCA_DASHBOARD_LAN") or "").lower() in {"1", "true", "yes"}


def validate_bind(host: str) -> None:
    """Require the LAN flag and token for every non-loopback bind."""
    if host == "localhost":
        return
    try:
        if ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    if not lan_requested():
        raise OrcaConfigError(
            "LAN bind (0.0.0.0) requires ORCA_DASHBOARD_LAN=1"
        )
    if not dashboard_token():
        raise OrcaConfigError(
            "LAN bind requires ORCA_DASHBOARD_TOKEN"
        )


def authorized(auth_header: str | None) -> bool:
    """If a token is configured, require a matching Bearer header."""
    token = dashboard_token()
    if not token:
        return True
    if not auth_header or not auth_header.startswith("Bearer "):
        return False
    got = auth_header[7:].strip()
    return hmac.compare_digest(got.encode("utf-8"), token.encode("utf-8"))
