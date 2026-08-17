"""Tool registry — single choke point; signature-bound path checks."""

from __future__ import annotations

import inspect
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .errors import HardPrivilegeError
from .roles import Privilege, TEAM

KNOWN_WRITE_CLASS: Dict[str, Optional[Privilege]] = {
    "write_file": Privilege.CODE_EDIT,
    "write_design": Privilege.HARDWARE_DESIGN,
    "kicad_note": Privilege.HARDWARE_DESIGN,
    "kicad_gen": Privilege.HARDWARE_DESIGN,
    "bom_update": Privilege.HARDWARE_DESIGN,
    "drc_checklist": Privilege.HARDWARE_DESIGN,
    "flash_note": Privilege.FIRMWARE_EDIT,
    "pinout_check": Privilege.FIRMWARE_EDIT,
    "read_file": None,
    "search_code": None,
    "run_tests": None,
    "part_search": None,
}

WRITE_ALLOWLIST = {"runs", "orca-out", "examples"}  # not docs/, not mao/

DEFAULT_PATH_PARAMS = (
    "path", "output_dir", "out_dir", "output_csv",
    "file", "filename", "dest", "target", "filepath", "out",
)


def require_repo_root() -> Path:
    env = os.environ.get("ORCA_REPO_ROOT") or os.environ.get("MAO_REPO_ROOT")
    if not env:
        raise HardPrivilegeError(
            "ORCA_REPO_ROOT is required (absolute path). Refusing cwd fallback."
        )
    root = Path(env).resolve()
    if not root.is_dir():
        raise HardPrivilegeError(f"ORCA_REPO_ROOT is not a directory: {root}")
    return root


@dataclass
class Tool:
    name: str
    description: str
    func: Callable[..., Any]
    parameters: dict = field(default_factory=dict)
    write_class: Optional[Privilege] = None
    is_read_only: bool = False
    path_params: tuple = DEFAULT_PATH_PARAMS


class ToolRegistry:
    def __init__(self, broker=None, repo_root_path: Optional[Path] = None):
        self._tools: Dict[str, Tool] = {}
        self.broker = broker
        if repo_root_path is not None:
            self.repo_root = Path(repo_root_path).resolve()
        else:
            try:
                self.repo_root = require_repo_root()
            except HardPrivilegeError:
                profile = (os.environ.get("ORCA_PROFILE") or "").lower()
                if profile in {"dev", "test", "local"}:
                    self.repo_root = Path.cwd().resolve()
                else:
                    raise

    @staticmethod
    def _audit_signature(tool: Tool) -> None:
        """A write-class tool must have an inspectable signature with no *args.

        `bind()` collapses *args into a single tuple under one name, so its
        elements can never be matched against path_params. Rather than guess
        which positional extras are paths, refuse the tool at registration —
        a registration-time refusal is loud, a call-time gap is silent.
        """
        try:
            sig = inspect.signature(tool.func)
        except (TypeError, ValueError) as e:
            raise ValueError(
                f"{tool.name}: write-class tool has no inspectable signature "
                f"({e}); path arguments cannot be audited"
            ) from e
        for p in sig.parameters.values():
            if p.kind is inspect.Parameter.VAR_POSITIONAL:
                raise ValueError(
                    f"{tool.name}: write-class tool may not declare *{p.name} — "
                    "variadic positionals cannot be path-audited; use named parameters"
                )

    def register(self, tool: Tool) -> None:
        if tool.is_read_only and tool.write_class is not None:
            raise ValueError(
                f"{tool.name}: is_read_only=True conflicts with write_class={tool.write_class}"
            )
        if tool.write_class is None and not tool.is_read_only:
            tool.write_class = Privilege.UNCLASSIFIED
        if tool.write_class is not None:
            self._audit_signature(tool)
        self._tools[tool.name] = tool

    def register_function(
        self,
        name: str,
        description: str,
        func: Callable,
        parameters: Optional[dict] = None,
        write_class: Optional[Privilege] = None,
        is_read_only: bool = False,
        path_params: Optional[tuple] = None,
    ) -> None:
        if write_class is None and not is_read_only:
            if name in KNOWN_WRITE_CLASS:
                hint = KNOWN_WRITE_CLASS[name]
                if hint is None:
                    is_read_only = True
                else:
                    write_class = hint
            else:
                write_class = Privilege.UNCLASSIFIED
        self.register(
            Tool(
                name, description, func, parameters or {}, write_class, is_read_only,
                tuple(path_params) if path_params else DEFAULT_PATH_PARAMS,
            )
        )

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(name)
        return self._tools[name]

    def list(self):
        return list(self._tools.keys())

    def _resolve_safe(self, raw: str) -> Path:
        p = Path(raw)
        try:
            resolved = (self.repo_root / p).resolve() if not p.is_absolute() else p.resolve()
        except Exception as e:
            raise HardPrivilegeError(f"path resolve failed: {raw}: {e}") from e
        return resolved

    @staticmethod
    def _flatten(sig: inspect.Signature, bound_arguments: dict) -> dict:
        """Lift **kwargs contents up one level so named path params inside a
        variadic keyword bag are still visible to the allowlist."""
        out: Dict[str, Any] = {}
        for pname, pval in bound_arguments.items():
            kind = sig.parameters[pname].kind
            if kind is inspect.Parameter.VAR_KEYWORD and isinstance(pval, dict):
                out.update(pval)
            else:
                out[pname] = pval
        return out

    def _check_write_paths(self, arguments: dict, path_params: tuple) -> None:
        candidates = []
        for k in path_params:
            if k in arguments and arguments[k] is not None:
                val = arguments[k]
                if isinstance(val, (list, tuple, set)):
                    candidates.extend(str(v) for v in val if v is not None)
                else:
                    candidates.append(str(val))
        for raw in candidates:
            resolved = self._resolve_safe(raw)
            try:
                rel = resolved.relative_to(self.repo_root)
            except ValueError:
                # Outside the repo. Name the BGM case explicitly — same denial,
                # clearer log line. Checked on the RESOLVED path so that
                # ../../bgm/x is caught, and NOT on the raw string, so that an
                # in-repo runs/bgm/notes.md is no longer a false positive.
                if "bgm" in [x.lower() for x in resolved.parts]:
                    raise HardPrivilegeError(
                        f"BGM path blocked: {raw} -> {resolved}"
                    ) from None
                raise HardPrivilegeError(
                    f"path outside repo root: {raw} -> {resolved}"
                ) from None
            parts = rel.parts
            if not parts:
                raise HardPrivilegeError(f"empty path: {raw}")
            top = parts[0]
            if top == "mao":
                raise HardPrivilegeError(
                    "writes into mao/ forbidden — use orca-out/patches/ for Fry to apply"
                )
            if top not in WRITE_ALLOWLIST:
                raise HardPrivilegeError(
                    f"path {raw!r} top={top!r} outside write allowlist {sorted(WRITE_ALLOWLIST)}"
                )

    def call(self, name: str, *args, agent: str, **kwargs) -> Any:
        """agent is REQUIRED — no ambient identity race."""
        tool = self.get(name)
        if not agent:
            raise HardPrivilegeError(f"agent= is required for tool {name!r}")
        duty = TEAM.get(agent)
        if duty is None:
            raise HardPrivilegeError(f"unknown agent {agent!r}")
        # Read-only catalog: tools_allowed is the only gate (writes use privilege).
        if tool.write_class is None:
            if "*" not in duty.tools_allowed and name not in duty.tools_allowed:
                raise HardPrivilegeError(
                    f"{agent} tools_allowed does not include {name!r}"
                )
        if tool.write_class is not None:
            if self.broker is None:
                raise HardPrivilegeError(
                    f"write-class tool {name!r} needs broker (priv={tool.write_class.value})"
                )
            if not agent:
                raise HardPrivilegeError(f"agent= is required for write-class tool {name!r}")
            try:
                self.broker.require(agent, tool.write_class)
                self.broker.require_turn(agent)
            except PermissionError as e:
                raise HardPrivilegeError(str(e)) from e
            try:
                sig = inspect.signature(tool.func)
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
                arguments = self._flatten(sig, dict(bound.arguments))
            except TypeError as e:
                raise HardPrivilegeError(f"cannot bind args for {name!r}: {e}") from e
            self._check_write_paths(arguments, tool.path_params)
        return tool.func(*args, **kwargs)
