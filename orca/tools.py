from __future__ import annotations

from dataclasses import dataclass
import json
from collections.abc import Callable, Mapping

from .domain import PermissionLevel


@dataclass(frozen=True)
class ToolCapability:
    name: str
    family: str
    description: str
    connector: str | None
    level: PermissionLevel
    mutates: bool = False


TOOL_CATALOG = {
    "file.read": ToolCapability("file.read", "files", "Read a bounded workspace file", None, PermissionLevel.R0),
    "file.search": ToolCapability("file.search", "files", "Search bounded workspace paths", None, PermissionLevel.R0),
    "repo.read": ToolCapability("repo.read", "files", "Inspect repository state and history", "gitea", PermissionLevel.R0),
    "web.search": ToolCapability("web.search", "web", "Search public web sources", None, PermissionLevel.R0),
    "web.fetch": ToolCapability("web.fetch", "web", "Fetch one allowlisted public resource", None, PermissionLevel.R0),
    "terminal.inspect": ToolCapability("terminal.inspect", "terminal", "Run an allowlisted read-only inspection", None, PermissionLevel.R0),
    "drive.read": ToolCapability("drive.read", "drive", "Read a Drive file", "drive", PermissionLevel.R0),
    "drive.search": ToolCapability("drive.search", "drive", "Search Drive metadata and content", "drive", PermissionLevel.R0),
    "notion.read": ToolCapability("notion.read", "knowledge", "Read approved Notion context", "notion", PermissionLevel.R0),
    "linear.read": ToolCapability("linear.read", "work", "Read approved Linear work items", "linear", PermissionLevel.R0),
    "node.observe": ToolCapability("node.observe", "fleet", "Observe enrolled node health", None, PermissionLevel.R0),
}


BOT_TOOL_MANIFESTS = {
    "orca": frozenset({
        "file.read", "file.search", "repo.read", "web.search", "web.fetch",
        "terminal.inspect", "drive.read", "drive.search", "notion.read",
        "linear.read", "node.observe",
    }),
    "smith": frozenset({
        "file.read", "file.search", "repo.read", "web.search", "web.fetch",
        "terminal.inspect", "drive.read", "drive.search", "notion.read",
        "linear.read", "node.observe",
    }),
    "quench": frozenset({
        "file.read", "file.search", "repo.read", "web.search", "web.fetch",
        "terminal.inspect", "drive.read", "drive.search", "node.observe",
    }),
    "security_gate": frozenset(),
}


TOOL_ARGUMENT_SCHEMAS = {
    "file.read": {"path": "workspace-relative file path"},
    "file.search": {"query": "text to find", "glob": "optional workspace glob"},
    "repo.read": {"executable": "absolute allowlisted executable", "args": "argument list"},
    "terminal.inspect": {"executable": "absolute allowlisted executable", "args": "argument list"},
    "web.search": {"query": "public web search query"},
    "web.fetch": {"url": "public HTTP or HTTPS URL"},
    "drive.search": {"query": "Drive file-name query"},
    "drive.read": {"path": "Google Drive path relative to My Drive"},
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


@dataclass(frozen=True)
class ToolRequest:
    name: str
    arguments: Mapping[str, object]


@dataclass(frozen=True)
class ToolResult:
    name: str
    output: object


class ReadOnlyToolBroker:
    """Executes bounded R0 calls through explicit, injected handlers."""

    max_calls = 4
    max_arguments_bytes = 8_192
    max_result_bytes = 32_768

    def __init__(self, handlers: Mapping[str, Callable[..., object]]) -> None:
        self.handlers = dict(handlers)

    def execute(self, *, bot_id: str, requests: list[ToolRequest]) -> list[ToolResult]:
        if not requests or len(requests) > self.max_calls:
            raise ValueError("tool request count is outside the bounded range")
        results = []
        authorizer = ToolAuthorizer()
        for request in requests:
            capability = authorizer.authorize(
                bot_id=bot_id, tool_name=request.name,
                approved_level=PermissionLevel.R0,
            )
            if capability.mutates:
                raise PermissionError("read-only broker refuses mutating tools")
            if not isinstance(request.arguments, Mapping) or not all(
                    isinstance(key, str) for key in request.arguments):
                raise ValueError("tool arguments must be an object with text keys")
            encoded_arguments = json.dumps(
                request.arguments, sort_keys=True, separators=(",", ":"), allow_nan=False)
            if len(encoded_arguments.encode()) > self.max_arguments_bytes:
                raise ValueError("tool arguments exceed the bounded envelope")
            handler = self.handlers.get(request.name)
            if handler is None:
                raise PermissionError(f"tool handler is unavailable: {request.name}")
            try:
                output = handler(**dict(request.arguments))
            except FileNotFoundError:
                output = {"status": "unavailable", "error": "Requested file was not found; no file content was read."}
            encoded_output = json.dumps(
                output, sort_keys=True, separators=(",", ":"), allow_nan=False)
            if len(encoded_output.encode()) > self.max_result_bytes:
                raise ValueError("tool result exceeds the bounded envelope")
            results.append(ToolResult(request.name, output))
        return results
