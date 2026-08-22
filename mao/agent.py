"""Agent base class and role definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional
import uuid


@dataclass
class Role:
    name: str
    description: str = ""


@dataclass
class Agent:
    """A single agent with role, system prompt, and model binding."""

    role: Role
    system_prompt: str
    model: Any = None  # ModelAdapter later
    tools: list[str] = field(default_factory=list)  # tool names from registry
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def __post_init__(self):
        if not self.role.name:
            raise ValueError("Agent must have a named role")

    def bind_model(self, model: Any) -> "Agent":
        self.model = model
        return self

    def allow_tools(self, tool_names: list[str]) -> "Agent":
        self.tools = list(tool_names)
        return self
