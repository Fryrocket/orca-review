from __future__ import annotations

from dataclasses import dataclass
import json
from collections.abc import Callable, Mapping

from .domain import PermissionLevel
from .engineering import CATALOG as ENGINEERING_CATALOG


@dataclass(frozen=True)
class ToolCapability:
    name: str
    family: str
    description: str
    connector: str | None
    level: PermissionLevel
    mutates: bool = False


TOOL_CATALOG = {
    "math.scientific": ToolCapability("math.scientific", "math", "Bounded symbolic calculus, matrices, complex and scientific math", None, PermissionLevel.R0),
    "engineering.calculate": ToolCapability("engineering.calculate", "engineering", "Evaluate a documented SI engineering model", None, PermissionLevel.R0),
    "engineering.catalog": ToolCapability("engineering.catalog", "engineering", "List engineering models, inputs and assumptions", None, PermissionLevel.R0),
    "engineering.review_panel": ToolCapability(
        "engineering.review_panel", "engineering",
        "Inspect the free-only independent engineering review panel, roles and A-to-Z gates",
        None, PermissionLevel.R0),
    "math.calculate": ToolCapability("math.calculate", "math", "Calculate bounded decimal arithmetic", None, PermissionLevel.R0),
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
    "studio.capabilities": ToolCapability("studio.capabilities", "studio", "List registered Studio workspaces, applications, business areas and tools", None, PermissionLevel.R0),
    "studio.user_manual_source": ToolCapability(
        "studio.user_manual_source", "studio",
        "Read the compact authoritative ORCA user-manual capability and status source",
        None, PermissionLevel.R0),
    "inventory.search": ToolCapability("inventory.search", "inventory", "Search the canonical KILN inventory without changing stock", None, PermissionLevel.R0),
    "temper.inference_capabilities": ToolCapability(
        "temper.inference_capabilities", "edge",
        "Inspect TEMPER Hailo-8 models, camera readiness, applicable workflows and safety gates",
        None, PermissionLevel.R0),
    "temper.plan_inference_workflow": ToolCapability(
        "temper.plan_inference_workflow", "edge",
        "Plan one governed TEMPER Hailo workflow without executing it",
        None, PermissionLevel.R0),
    "temper.plan_inventory_dataset": ToolCapability(
        "temper.plan_inventory_dataset", "edge",
        "Plan a governed TEMPER inventory-vision dataset without capturing, training, or deploying",
        None, PermissionLevel.R0),
    "temper.plan_inventory_capture": ToolCapability(
        "temper.plan_inventory_capture", "edge",
        "Plan a bounded inventory image-capture session without opening a camera",
        None, PermissionLevel.R0),
    "temper.validate_inventory_dataset": ToolCapability(
        "temper.validate_inventory_dataset", "edge",
        "Check bounded inventory dataset metadata for balance, duplicates, leakage and provenance",
        None, PermissionLevel.R0),
    "temper.plan_hailo_conversion": ToolCapability(
        "temper.plan_hailo_conversion", "edge",
        "Plan a Hailo-8 conversion and model-registry candidate without executing or deploying",
        None, PermissionLevel.R0),
}


BOT_TOOL_MANIFESTS = {
    # The right-hand ChatGPT pane is conversational. Tool-bearing technical
    # work belongs to the separate Administrator ChatGPT session.
    "chatgpt": frozenset(),
    # Gemini is an external free-tier provider. It receives sanitized prompts
    # only and never inherits repository, file, connector or terminal reads.
    "gemini": frozenset(),
    "orca": frozenset({
        "math.scientific", "engineering.calculate", "engineering.catalog", "engineering.review_panel",
        "math.calculate",
        "file.read", "file.search", "repo.read", "web.search", "web.fetch",
        "terminal.inspect", "drive.read", "drive.search", "notion.read",
        "linear.read", "node.observe",
        "studio.capabilities", "inventory.search",
        "studio.user_manual_source",
        "temper.inference_capabilities",
        "temper.plan_inference_workflow",
        "temper.plan_inventory_dataset",
        "temper.plan_inventory_capture", "temper.validate_inventory_dataset",
        "temper.plan_hailo_conversion",
    }),
    "smith": frozenset({
        "math.scientific", "engineering.calculate", "engineering.catalog", "engineering.review_panel",
        "math.calculate",
        "file.read", "file.search", "repo.read", "web.search", "web.fetch",
        "terminal.inspect", "drive.read", "drive.search", "notion.read",
        "linear.read", "node.observe",
        "studio.capabilities", "inventory.search",
        "studio.user_manual_source",
        "temper.inference_capabilities",
        "temper.plan_inference_workflow",
        "temper.plan_inventory_dataset",
        "temper.plan_inventory_capture", "temper.validate_inventory_dataset",
        "temper.plan_hailo_conversion",
    }),
    "quench": frozenset({
        "math.scientific", "engineering.calculate", "engineering.catalog", "engineering.review_panel",
        "math.calculate",
        "file.read", "file.search", "repo.read", "web.search", "web.fetch",
        "terminal.inspect", "drive.read", "drive.search", "node.observe",
        "studio.capabilities", "inventory.search",
        "studio.user_manual_source",
        "temper.inference_capabilities",
        "temper.plan_inference_workflow",
        "temper.plan_inventory_dataset",
        "temper.plan_inventory_capture", "temper.validate_inventory_dataset",
        "temper.plan_hailo_conversion",
    }),
    "security_gate": frozenset(),
}


TOOL_ARGUMENT_SCHEMAS = {
    "math.scientific": {
        "operation": "evaluate, simplify, differentiate, integrate, definite_integral, solve, matrix_determinant, matrix_inverse, linear_solve, eigenvalues",
        "expression": "Expression string; explicit multiplication, ^ powers, sin/cos/tan/exp/log/sqrt/abs, pi,e,i. Omit for matrices. Angles in radians.",
        "variable": "Only calculus/solve: variable name, default x. solve means expression = 0",
        "lower": "Only definite_integral: finite real bound string", "upper": "Only definite_integral: finite real bound string",
        "domain": "Only solve: real (default) or complex", "precision": "Optional integer 15–100, default 50",
        "matrix": "Only matrix operations: square JSON array 1–6 rows, each entry an expression STRING",
        "rhs": "Only linear_solve: array of expression STRINGS, one per row. Omit inapplicable keys entirely."},
    "engineering.calculate": {"tool": "One of: " + "; ".join(
        key + "(" + ",".join(f["key"]+":"+f["unit"] for f in value["fields"]) + ")"
        for key, value in ENGINEERING_CATALOG.items()),
        "values": "Object containing exactly that model's SI fields as QUOTED DECIMAL STRINGS, never JSON numbers. Preserve exponent digits: inertia 1e-8 m^4 becomes \"1e-8\"; Young modulus 200 GPa becomes \"200e9\" Pa. Never invent missing dimensions, properties or loads."},
    "engineering.catalog": {},
    "engineering.review_panel": {},
    "math.calculate": {"expression": "Arithmetic with decimal numbers, + - * / ^, parentheses, sqrt(), abs(); numeric percent means /100. No variables or units."},
    "file.read": {"path": "workspace-relative file path"},
    "file.search": {"query": "text to find", "glob": "optional workspace glob"},
    "repo.read": {"executable": "absolute allowlisted executable", "args": "argument list"},
    "terminal.inspect": {"executable": "absolute allowlisted executable", "args": "argument list"},
    "web.search": {"query": "public web search query"},
    "web.fetch": {"url": "public HTTP or HTTPS URL"},
    "drive.search": {"query": "Drive file-name query"},
    "drive.read": {"path": "Google Drive path relative to My Drive"},
    "studio.capabilities": {"area": "Optional: all, workspaces, applications, business, or tools"},
    "studio.user_manual_source": {},
    "inventory.search": {"query": "Optional item, SKU, category, location, lot or serial text", "state": "Optional: all, healthy, reorder, stockout, or attention", "limit": "Optional integer 1-50"},
    "node.observe": {"node_id": "Optional enrolled node ID or all"},
    "temper.inference_capabilities": {
        "input_type": "Optional: all, camera, image, video, sensor, or audio"},
    "temper.plan_inference_workflow": {
        "workflow_id": "Registered TEMPER workflow ID",
        "input_kind": "Optional: camera, image, or video",
        "labels": "Optional bounded list of declared labels for generic detection"},
    "temper.plan_inventory_dataset": {
        "name": "Dataset name", "version": "Dataset version",
        "labels": "1-50 exact inventory label rows with id, name, sku and optional barcode/description",
        "source": "Bounded provenance description", "license_name": "Dataset license or ownership basis",
        "target_images_per_label": "Optional integer 50-2000; default 120"},
    "temper.plan_inventory_capture": {
        "manifest": "Exact inventory-vision manifest returned by temper.plan_inventory_dataset",
        "session_id": "Stable capture session identifier",
        "camera_profile": "Declared camera and capture profile",
        "operator": "Optional capture operator; default Fry"},
    "temper.validate_inventory_dataset": {
        "manifest": "Exact inventory-vision manifest",
        "assets": "Bounded asset metadata rows with hashes, split, provenance, reviewers and privacy flag"},
    "temper.plan_hailo_conversion": {
        "manifest": "Exact inventory-vision manifest",
        "validation": "Accepted validation result for that manifest",
        "training_metrics": "precision, recall, count_error_rate and source_model_sha256",
        "toolchain": "hailo_dataflow_compiler, hailort and target=hailo8"},
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
