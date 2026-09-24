"""ORCA v1 policy-first control plane."""

from importlib import import_module
from typing import Any

__all__ = ["Action", "AgentIdentity", "ControlPlane", "Job", "PermissionLevel"]
__version__ = "1.0.0a1"


def __getattr__(name: str) -> Any:
    if name == "ControlPlane":
        value = import_module(".control_plane", __name__).ControlPlane
    elif name in {"Action", "AgentIdentity", "Job", "PermissionLevel"}:
        value = getattr(import_module(".domain", __name__), name)
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value
