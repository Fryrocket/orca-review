from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import re


@dataclass(frozen=True)
class CommandSpec:
    name: str
    executable: str
    args: tuple[str, ...]
    read_only: bool = True


ALLOWED_EXECUTABLES = {
    "/usr/bin/systemctl": frozenset({"is-active", "status", "show"}),
    "/usr/bin/git": frozenset({"status", "rev-parse", "log"}),
    "/usr/bin/df": frozenset({"-h", "-P"}),
}


_UNIT = re.compile(r"^[A-Za-z0-9@_.:-]+$")
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9@_./:=+-]+$")


class ScopedNodeExecutor:
    """Validates a narrow command envelope; execution is intentionally disabled."""

    def __init__(self, transport_allowlist: dict[str, tuple[str, ...]]) -> None:
        self.transport_allowlist = transport_allowlist

    def validate_target(self, node_id: str, address: str) -> None:
        if address not in self.transport_allowlist.get(node_id, ()):
            raise PermissionError("node transport target is not allowlisted")

    def validate_command(self, command: CommandSpec) -> None:
        executable = str(PurePosixPath(command.executable))
        allowed_first_args = ALLOWED_EXECUTABLES.get(executable)
        if allowed_first_args is None or not command.args or command.args[0] not in allowed_first_args:
            raise PermissionError("command is outside the scoped executor allowlist")
        if not command.read_only:
            raise PermissionError("mutating node commands are disabled")
        if len(command.args) > 4 or any(
                len(arg) > 256 or not _SAFE_TOKEN.fullmatch(arg) for arg in command.args):
            raise PermissionError("command arguments are outside the scoped executor grammar")
        operation, rest = command.args[0], command.args[1:]
        if executable == "/usr/bin/systemctl":
            if len(rest) > 1 or any(not _UNIT.fullmatch(arg) for arg in rest):
                raise PermissionError("systemctl arguments are outside the read-only grammar")
        elif executable == "/usr/bin/git":
            allowed = {
                "status": {(), ("--short",), ("--porcelain=v1",)},
                "rev-parse": {("HEAD",), ("--show-toplevel",), ("--is-inside-work-tree",)},
                "log": {(), ("-1",), ("--oneline",)},
            }
            if tuple(rest) not in allowed[operation]:
                raise PermissionError("git arguments are outside the read-only grammar")
        elif executable == "/usr/bin/df":
            if len(rest) > 1 or any(not arg.startswith("/") or ".." in arg.split("/") for arg in rest):
                raise PermissionError("df arguments are outside the read-only grammar")

    def execute(self, node_id: str, address: str, command: CommandSpec) -> None:
        self.validate_target(node_id, address)
        self.validate_command(command)
        raise PermissionError("remote node execution is disabled pending review and approval")
