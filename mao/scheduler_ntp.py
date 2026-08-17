"""A14: refuse to arm scheduler if NTP unsynced; re-check before fire."""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone

from .errors import NTPNotSyncedError

# Back-compat: callers that did `from .scheduler_ntp import NTPNotSyncedError`
# keep working. Canonical home is mao.errors.
__all__ = ["NTPNotSyncedError", "ntp_synchronized", "require_ntp_or_refuse"]


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


def require_ntp_or_refuse(stage: str = "arm") -> None:
    """Refuse (not warn) when NTP is unsynced.

    MUST be called at arm time AND immediately before each job fires — a Pi 5
    has no battery-backed RTC, so a reboot mid-schedule can move the clock
    after the arm-time check has already passed. `stage` is recorded in the
    message so the log says which of the two checks refused.
    """
    if not ntp_synchronized():
        raise NTPNotSyncedError(
            f"NTP not synchronized — refusing scheduler at stage={stage!r} (A14). "
            f"utc_now={datetime.now(timezone.utc).isoformat()}"
        )
