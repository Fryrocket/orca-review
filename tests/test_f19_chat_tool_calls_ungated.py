"""R11-F19 ("chat tools") — a crisp finding.

_invoke() builds tool_schemas for any agent with tools=[...] and
tools_allowed=True, independent of which model interface will be used.
The .complete() branch forwards those schemas (tools=tool_schemas);
the .chat() branch does not — it sends only system+user messages. So a
chat-only adapter is never told what tools exist or their parameter
shapes.

Despite that, both response-parsing branches read raw.get("tool_calls")
/ getattr(raw, "tool_calls", ...) and unconditionally execute whatever
they find via tool_proxy.call(...), with no check for whether this
particular call ever received a schema. A chat-path adapter (or a bug in
one, or a response that happens to echo a tool_calls-shaped dict) can
therefore trigger real tool execution — subject only to ToolRegistry's
own privilege/path checks, not to "did the model actually get offered
this tool" — even though the orchestrator itself never gave the model
any legitimate basis for producing that call.

Fix: track whether tool_schemas were actually handed to the model for
this invocation (schema_given), and only honor tool_calls when they
were. The .chat() path never sets it, so tool_calls reported there are
now ignored instead of executed.
"""

from mao.agent import Agent, Role
from mao.costguard import UsageTrackerCostGuard
from mao.orchestrator import Orchestrator
from mao.roles import GROK, PrivilegeBroker
from mao.tools import ToolRegistry


def _cost_guard():
    return UsageTrackerCostGuard(
        record_usage=lambda **kw: None,
        hard_ceiling_usd=100.0,
        estimate_cost=lambda model, tin, tout: 0.0,
    )


def _registry(repo_root, calls):
    def read_file(path="x"):
        calls.append(path)
        return "contents"

    reg = ToolRegistry(broker=None, repo_root_path=repo_root)
    reg.register_function("read_file", "read a file", read_file, is_read_only=True)
    return reg


class ChatOnlyModel:
    """Only implements .chat() — orchestrator never passes tools= here."""

    name = "chat-only-fake"

    def __init__(self, tool_calls):
        self._tool_calls = tool_calls

    def chat(self, messages):
        return {
            "text": "done",
            "input_tokens": 5,
            "output_tokens": 5,
            "tool_calls": self._tool_calls,
        }


class CompleteModel:
    """Implements .complete() — orchestrator passes tools=tool_schemas here."""

    name = "complete-fake"

    def __init__(self, tool_calls):
        self._tool_calls = tool_calls
        self.received_tools = None

    def complete(self, system, user, tools):
        self.received_tools = tools
        return {
            "text": "done",
            "input_tokens": 5,
            "output_tokens": 5,
            "tool_calls": self._tool_calls,
        }


def _orchestrator(agent, repo_root):
    calls = []
    reg = _registry(repo_root, calls)
    broker = PrivilegeBroker()
    orch = Orchestrator(
        [agent], tools=reg, broker=broker, cost_guard=_cost_guard(), runner=GROK.name
    )
    return orch, calls


def test_chat_path_never_receives_tool_schema(tmp_path):
    """The root cause: .chat() adapters are not offered tools= at all."""

    class RecordingChatModel:
        name = "recording-chat"
        received = "UNSET"

        def chat(self, messages):
            self.received = messages
            return {"text": "done", "input_tokens": 1, "output_tokens": 1}

    model = RecordingChatModel()
    role = Role(name="claude", description="editor")
    agent = Agent(role=role, system_prompt="sp", model=model, tools=["read_file"])
    orch, _calls = _orchestrator(agent, str(tmp_path))
    list(orch.run_sequential("objective"))
    assert model.received == [
        {"role": "system", "content": "sp"},
        {"role": "user", "content": "objective"},
    ]


def test_chat_path_tool_calls_are_not_executed(tmp_path):
    """The F19 bug: a chat-only adapter that reports tool_calls anyway
    must not have them executed — it was never given a schema."""
    role = Role(name="claude", description="editor")
    model = ChatOnlyModel(
        tool_calls=[{"name": "read_file", "arguments": {"path": "runs/x.txt"}}]
    )
    agent = Agent(role=role, system_prompt="sp", model=model, tools=["read_file"])
    orch, calls = _orchestrator(agent, str(tmp_path))
    results = list(orch.run_sequential("objective"))
    assert results[0].text == "done"
    assert calls == []  # tool must NOT have been invoked


def test_complete_path_tool_calls_still_executed(tmp_path):
    """Regression guard: this fix must not touch the .complete() path,
    which DOES receive a real schema and legitimately reports calls."""
    role = Role(name="claude", description="editor")
    model = CompleteModel(
        tool_calls=[{"name": "read_file", "arguments": {"path": "runs/x.txt"}}]
    )
    agent = Agent(role=role, system_prompt="sp", model=model, tools=["read_file"])
    orch, calls = _orchestrator(agent, str(tmp_path))
    results = list(orch.run_sequential("objective"))
    assert results[0].text == "done"
    assert calls == ["runs/x.txt"]  # tool WAS invoked
    assert model.received_tools == [
        {"name": "read_file", "description": "read a file", "parameters": {}}
    ]


def test_chat_path_with_no_tools_declared_is_unaffected(tmp_path):
    """Regression guard: an agent with no tools at all on the chat path
    behaves exactly as before (no schema was ever built either way)."""
    role = Role(name="claude", description="editor")
    model = ChatOnlyModel(tool_calls=[])
    agent = Agent(role=role, system_prompt="sp", model=model, tools=[])
    orch, calls = _orchestrator(agent, str(tmp_path))
    results = list(orch.run_sequential("objective"))
    assert results[0].text == "done"
    assert calls == []
