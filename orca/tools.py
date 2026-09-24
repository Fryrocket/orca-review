from __future__ import annotations

from dataclasses import dataclass

from .domain import PermissionLevel


@dataclass(frozen=True)
class ToolCapability:
    name: str
    connector: str | None
    level: PermissionLevel
    mutates: bool = False


TOOL_CATALOG = {
    "repo.read": ToolCapability("repo.read", "gitea", PermissionLevel.R0),
    "drive.read": ToolCapability("drive.read", "drive", PermissionLevel.R0),
    "notion.read": ToolCapability("notion.read", "notion", PermissionLevel.R0),
    "linear.read": ToolCapability("linear.read", "linear", PermissionLevel.R0),
    "node.observe": ToolCapability("node.observe", None, PermissionLevel.R0),
}


BOT_TOOL_MANIFESTS = {
    "orca": frozenset(),
    "smith": frozenset(),
    "quench": frozenset(),
    "security_gate": frozenset(),
}


class ToolAuthorizer:
    def authorize(self, *, bot_id: str, tool_name: str, approved_level: PermissionLevel) -> ToolCapability:
        if tool_name not in TOOL_CATALOG:
            raise PermissionError(f"unknown tool denied: {tool_name}")
        if tool_name not in BOT_TOOL_MANIFESTS.get(bot_id, frozenset()):
            raise PermissionError(f"tool not granted to bot: {bot_id}/{tool_name}")
        capability = TOOL_CATALOG[tool_name]
        if capability.level > approved_level:
            raise PermissionError("tool exceeds approved job level")
        return capability
