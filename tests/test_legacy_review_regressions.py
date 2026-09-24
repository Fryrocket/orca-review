"""Regression checks for retained legacy code reviewed September 23."""

import json

import pytest

from mao.costguard import UsageTrackerCostGuard
from mao.cost_store import DayCostStore
from mao.errors import OrcaConfigError
from mao.web_ui.auth import validate_bind


@pytest.mark.parametrize("host", ["192.168.7.30", "100.97.193.39", "forge.local", "::ffff:192.168.7.30"])
def test_every_non_loopback_bind_requires_lan_opt_in(monkeypatch, host):
    monkeypatch.delenv("ORCA_DASHBOARD_LAN", raising=False)
    monkeypatch.delenv("ORCA_DASHBOARD_TOKEN", raising=False)
    with pytest.raises(OrcaConfigError, match="LAN"):
        validate_bind(host)


@pytest.mark.parametrize("cost", [float("nan"), float("inf"), -1.0])
def test_bad_derived_cost_never_reaches_billing(cost):
    recorded = []
    guard = UsageTrackerCostGuard(estimate_cost=lambda *_: cost,
                                  record_usage=lambda **row: recorded.append(row),
                                  hard_ceiling_usd=1)
    with pytest.raises(OrcaConfigError):
        guard.record("fixture", 1, 1)
    assert recorded == []
    assert guard.total_usd == 0


@pytest.mark.parametrize("amount", [float("nan"), float("inf")])
def test_day_ledger_rejects_nonfinite_amount_without_creating_file(tmp_path, amount):
    ledger = DayCostStore(tmp_path / "cost.json")
    with pytest.raises(OrcaConfigError):
        ledger.add(amount, ceiling=1)
    assert not ledger.path.exists()


def test_corrupt_day_ledger_does_not_report_budget_available(tmp_path):
    ledger = DayCostStore(tmp_path / "cost.json")
    ledger.path.write_text(json.dumps({"day": ledger._utc_day(), "cost_usd": -100}))
    assert ledger.remaining(1) == 0


def test_orchestrator_retains_supplied_empty_event_bus():
    from mao.agent import Agent, Role
    from mao.bus import MessageBus
    from mao.models import EchoModel
    from mao.orchestrator import Orchestrator
    from mao.roles import PrivilegeBroker

    bus = MessageBus()
    guard = UsageTrackerCostGuard(estimate_cost=lambda *_: 0,
                                  record_usage=lambda **_: None, hard_ceiling_usd=0)
    orch = Orchestrator([Agent(Role("claude"), "fixture", model=EchoModel())],
                        bus=bus, cost_guard=guard, broker=PrivilegeBroker(enforce=True))
    list(orch.run_sequential("fixture"))
    assert len(bus.history()) == 1


def test_malformed_persisted_metadata_is_skipped(tmp_path):
    from mao.blackboard import Blackboard
    from mao.persist import load_blackboard

    path = tmp_path / "board.json"
    path.write_text(json.dumps({"entries": [
        {"key": "bad", "writer": "grok", "value": "ignored", "meta": 7},
        {"key": "good", "writer": "grok", "value": "restored", "meta": {}},
    ]}))
    board = load_blackboard(path, Blackboard(guard=lambda *_: None))
    assert board.get("good") == "restored"
