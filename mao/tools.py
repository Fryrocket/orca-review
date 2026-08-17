"""Tool registry — single choke point; signature-bound path checks."""

from __future__ import annotations

import inspect
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Set

from .errors import HardPrivilegeError
from .roles import Privilege

KNOWN_WRITE_CLASS: Dict[str, Optional[Privilege]] = {
    "write_file": Privilege.CODE_EDIT,
    "write_design": Privilege.HARDWARE_DESIGN,
    "kicad_note": Privilege.HARDWARE_DESIGN,
    "kicad_gen": Privilege.HARDWARE_DESIGN,
    "bom_update": Privilege.HARDWARE_DESIGN,
    "flash_note": Privilege.FIRMWARE_EDIT,
    "read_file": None,
    "search_code": None,
    "run_tests": None,
}

WRITE_ALLOWLIST = {"runs", "orca-out", "examples"}  # not docs/, not mao/


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
    path_params: tuple = (
        "path", "output_dir", "out_dir", "output_csv",
        "file", "filename", "dest", "target", "filepath", "out",
    )


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

    def register(self, tool: Tool) -> None:
        if tool.is_read_only and tool.write_class is not None:
            raise ValueError(
                f"{tool.name}: is_read_only=True conflicts with write_class={tool.write_class}"
            )
        if tool.write_class is None and not tool.is_read_only:
            tool.write_class = Privilege.UNCLASSIFIED
        if tool.is_read_only:
            tool.write_class = None
        self._tools[tool.name] = tool

    def register_function(
        self,
        name: str,
        description: str,
        func: Callable,
        parameters: Optional[dict] = None,
        write_class: Optional[Privilege] = None,
        is_read_only: bool = False,
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
            Tool(name, description, func, parameters or {}, write_class, is_read_only)
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

    def _check_write_paths(self, arguments: dict, path_params: tuple) -> None:
        candidates = []
        for k in path_params:
            if k in arguments and arguments[k] is not None:
                candidates.append(str(arguments[k]))
        for raw in candidates:
            parts_lower = [x.lower() for x in Path(raw).parts]
            if "bgm" in parts_lower:
                raise HardPrivilegeError(f"BGM path blocked: {raw}")
            resolved = self._resolve_safe(raw)
            try:
                rel = resolved.relative_to(self.repo_root)
            except ValueError:
                raise HardPrivilegeError(
                    f"path outside repo root: {raw} -> {resolved}"
                )
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
                bound = inspect.signature(tool.func).bind(*args, **kwargs)
                bound.apply_defaults()
                arguments = dict(bound.arguments)
            except TypeError as e:
                raise HardPrivilegeError(f"cannot bind args for {name!r}: {e}") from e
            self._check_write_paths(arguments, tool.path_params)
        return tool.func(*args, **kwargs)
