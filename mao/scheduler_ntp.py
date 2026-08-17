"""A14: refuse to arm scheduler if NTP unsynced; re-check before fire."""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone


class NTPNotSyncedError(RuntimeError):
    pass


def ntp_synchronized() -> bool:
    if not shutil.which("timedatectl"):
        return False
    try:
        p = subprocess.run(
            ["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return p.stdout.strip().lower() in {"yes", "1", "true"}
    except Exception:
        return False


def require_ntp_or_refuse() -> None:
    """Refuse (not warn) when NTP is unsynced. Call at arm AND before each fire."""
    if not ntp_synchronized():
        raise NTPNotSyncedError(
            "NTP not synchronized — refusing scheduler (A14). "
            f"utc_now={datetime.now(timezone.utc).isoformat()}"
        )
