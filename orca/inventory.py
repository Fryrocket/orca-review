from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
import subprocess

from .security import redact


class InventoryReadError(RuntimeError):
    """The bounded inventory read could not be completed."""


class InventoryProvider:
    """Read the canonical KILN inventory through one fixed SSH command.

    The provider accepts no caller-controlled command text and exposes no write
    action. Its key and known-hosts files live in ORCA's protected state path.
    """

    def __init__(
        self,
        *,
        key_file: str | Path,
        known_hosts_file: str | Path,
        host: str = "192.168.4.28",
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        timeout_seconds: int = 12,
    ) -> None:
        if host != "192.168.4.28":
            raise ValueError("inventory provider host is not allowlisted")
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 30:
            raise ValueError("inventory timeout must be 1-30 seconds")
        self.key_file = str(key_file)
        self.known_hosts_file = str(known_hosts_file)
        self.host = host
        self.runner = runner
        self.timeout_seconds = timeout_seconds

    def _command(self, action: str) -> list[str]:
        if action not in {"catalog", "list"}:
            raise ValueError("inventory action is not allowlisted")
        return [
            "/usr/bin/ssh",
            "-i", self.key_file,
            "-o", "IdentitiesOnly=yes",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=6",
            "-o", "StrictHostKeyChecking=yes",
            "-o", f"UserKnownHostsFile={self.known_hosts_file}",
            f"fryrocket@{self.host}",
            "/usr/bin/python3",
            "/home/fryrocket/inventory-backend/inventory_cli.py",
            action,
        ]

    def _read_action(self, action: str) -> dict:
        try:
            completed = self.runner(
                self._command(action),
                capture_output=True,
                check=False,
                timeout=self.timeout_seconds,
                env={"PATH": "/usr/bin:/bin"},
            )
        except (OSError, subprocess.SubprocessError):
            raise InventoryReadError("inventory transport failed") from None
        if completed.returncode != 0:
            raise InventoryReadError("inventory source rejected the read")
        raw = completed.stdout
        if not isinstance(raw, bytes) or len(raw) > 1_000_000:
            raise InventoryReadError("inventory response exceeds the size limit")
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise InventoryReadError("inventory response is not valid JSON") from None
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise InventoryReadError("inventory response is not successful")
        return redact(payload)

    def snapshot(self) -> dict:
        catalog = self._read_action("catalog")
        listing = self._read_action("list")
        items = listing.get("items")
        if not isinstance(items, list) or len(items) > 10_000:
            raise InventoryReadError("inventory item list is invalid")
        for key in ("locations", "categories", "units"):
            if not isinstance(catalog.get(key), list):
                raise InventoryReadError("inventory catalog is invalid")
        return {
            "ok": True,
            "source": "KILN canonical bench inventory",
            "read_only": True,
            "items": items,
            "locations": catalog["locations"],
            "categories": catalog["categories"],
            "units": catalog["units"],
        }
