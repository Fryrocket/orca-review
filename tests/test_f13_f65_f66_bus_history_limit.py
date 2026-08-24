"""R11-F13/F65/F66 ("bus").

MessageBus.history(limit=N) used `items[-limit:]`. Python treats -0 as 0,
and `list[0:]` returns the WHOLE list — so `limit=0` ("give me none")
silently returned everything instead of nothing. No current caller passes
limit=0 (web_ui/server.py uses limit=120), but it's a real footgun in a
public method's contract: any future paginated caller computing a limit
that can legitimately be 0 gets silently wrong results with no error.
Negative limits are equally nonsensical for "last N" and get the same
treatment (empty)."""

from mao.bus import MessageBus


def _bus_with(n):
    b = MessageBus()
    for i in range(n):
        b.publish("grok", f"msg{i}")
    return b


def test_history_limit_zero_returns_empty():
    """The exact F13/F65/F66 bug: this used to return everything."""
    b = _bus_with(3)
    assert b.history(limit=0) == []


def test_history_limit_positive_returns_last_n():
    b = _bus_with(5)
    result = b.history(limit=2)
    assert len(result) == 2
    assert [m.content for m in result] == ["msg3", "msg4"]


def test_history_limit_none_returns_everything():
    b = _bus_with(3)
    assert len(b.history(limit=None)) == 3
    assert len(b.history()) == 3


def test_history_limit_negative_returns_empty():
    """Negative limits are as meaningless as zero for 'last N' semantics."""
    b = _bus_with(3)
    assert b.history(limit=-5) == []


def test_history_limit_larger_than_available_returns_all():
    b = _bus_with(2)
    assert len(b.history(limit=100)) == 2


def test_history_limit_combined_with_topic_filter():
    """Regression guard: limit=0 must still correctly interact with the
    other filters, not just work in isolation."""
    b = MessageBus()
    b.publish("grok", "a", topic="x")
    b.publish("grok", "b", topic="y")
    assert b.history(topic="x", limit=0) == []
    assert len(b.history(topic="x", limit=None)) == 1
