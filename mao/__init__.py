"""Orca / mao package."""

from .agent import Agent, Role
from .bus import Message, MessageBus
from .blackboard import Blackboard, BoardEntry
from .costguard import CostGuard, UsageTrackerCostGuard
from .errors import (
    CostCapExceeded,
    CostLedgerCorrupt,
    GateTimeoutError,
    HardPrivilegeError,
    NTPNotSyncedError,
    OrcaConfigError,
    OrcaError,
    PriceTableStaleError,
    UnknownModelError,
)
from .human import GateDecision, GateResult, HumanGate
from .models import EchoModel, ModelAdapter, OpenAICompatibleModel, get_default_model
from .orchestrator import Orchestrator, StepResult, AgentToolProxy
from .persist import save_blackboard, save_bus
from .pricing import DEFAULT_MODEL, estimate_cost
from .roles import AMPERE, CLAUDE, GROK, RELAY, TEAM, Privilege, PrivilegeBroker
from .tools import Tool, ToolRegistry
from .tracking import UsageRecord, UsageTracker

__version__ = "0.5.12"

__all__ = [
    "AMPERE",
    "CLAUDE",
    "DEFAULT_MODEL",
    "GROK",
    "RELAY",
    "TEAM",
    "Agent",
    "AgentToolProxy",
    "Blackboard",
    "BoardEntry",
    "CostCapExceeded",
    "CostGuard",
    "CostLedgerCorrupt",
    "EchoModel",
    "GateDecision",
    "GateResult",
    "GateTimeoutError",
    "HardPrivilegeError",
    "HumanGate",
    "Message",
    "MessageBus",
    "ModelAdapter",
    "NTPNotSyncedError",
    "OpenAICompatibleModel",
    "OrcaConfigError",
    "OrcaError",
    "Orchestrator",
    "PriceTableStaleError",
    "Privilege",
    "PrivilegeBroker",
    "Role",
    "StepResult",
    "Tool",
    "ToolRegistry",
    "UnknownModelError",
    "UsageRecord",
    "UsageTracker",
    "UsageTrackerCostGuard",
    "estimate_cost",
    "get_default_model",
    "save_blackboard",
    "save_bus",
]
