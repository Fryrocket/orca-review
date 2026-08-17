"""Round-6 verification suite.

Every pytest.raises carries match= — an assertion that only checks the
exception TYPE passes when the guard fires for the wrong reason, which is
how three of the round-4 tests were green while the bug they named was live.

No test touches os.environ directly; all env goes through monkeypatch so the
suite is order-independent.
"""

import inspect

import pytest

from mao import pricing, scheduler_ntp
from mao.cost_store import DayCostStore
from mao.errors import (
    CostCapExceeded,
    CostLedgerCorrupt,
    HardPrivilegeError,
    NTPNotSyncedError,
    OrcaConfigError,
    OrcaError,
    PriceTableStaleError,
    UnknownModelError,
)
from mao.roles import Privilege, PrivilegeBroker
from mao.tools import Tool, ToolRegistry
from mao.tracking import UsageTracker


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("ORCA_PROFILE", "test")
    monkeypatch.delenv("ORCA_REPO_ROOT", raising=False)
    monkeypatch.delenv("MAO_REPO_ROOT", raising=False)
    return monkeypatch


@pytest.fixture
def repo(tmp_path, env):
    env.setenv("ORCA_REPO_ROOT", str(tmp_path))
    for d in ("runs", "mao", "orca-out", "examples", "docs"):
        (tmp_path / d).mkdir()
    return tmp_path


def _wf(path, content=""):
    return "ok"


# --------------------------------------------------------------------------
# Privilege + turn
# --------------------------------------------------------------------------

def test_write_tool_denied_without_grant(repo):
    broker = PrivilegeBroker(enforce=True)
    reg = ToolRegistry(broker=broker, repo_root_path=repo)
    broker.start_turn("claude")
    reg.register_function("write_file", "write", _wf, write_class=Privilege.CODE_EDIT)
    with pytest.raises(HardPrivilegeError, match=r"claude lacks code_edit"):
        reg.call("write_file", agent="claude", path="runs/x.py", content="x")


def test_grant_denied_without_human_approve(env):
    broker = PrivilegeBroker(enforce=True)
    with pytest.raises(HardPrivilegeError, match=r"requires HumanGate APPROVE from Fry"):
        broker.grant("grok", "claude", {Privilege.CODE_EDIT}, human_approved=False)


def test_only_grok_may_grant(env):
    broker = PrivilegeBroker(enforce=True)
    with pytest.raises(HardPrivilegeError, match=r"Only Grok can propose grants"):
        broker.grant("claude", "claude", {Privilege.READ})


def test_unclassified_is_not_grantable(env):
    """D2: the sentinel must be ungrantable, not merely unheld."""
    broker = PrivilegeBroker(enforce=True)
    with pytest.raises(HardPrivilegeError, match=r"UNCLASSIFIED is a sentinel"):
        broker.grant("grok", "claude", {Privilege.UNCLASSIFIED}, human_approved=True)


def test_start_turn_refuses_when_another_turn_active(env):
    """D3: a second start_turn must not silently displace the first."""
    broker = PrivilegeBroker(enforce=True)
    broker.start_turn("claude")
    with pytest.raises(HardPrivilegeError, match=r"turn already active for 'claude'"):
        broker.start_turn("ampere")


def test_start_turn_same_agent_is_idempotent(env):
    broker = PrivilegeBroker(enforce=True)
    broker.start_turn("claude")
    broker.start_turn("claude")
    assert broker._active_turn == "claude"


def test_turn_switch_does_not_orphan_grant(env):
    """D3: the grant must not survive to the agent's next turn unapproved."""
    broker = PrivilegeBroker(enforce=True)
    broker.grant("grok", "claude", {Privilege.CODE_EDIT}, human_approved=True)
    broker.start_turn("claude")
    broker.end_turn()
    broker.start_turn("ampere")
    broker.end_turn()
    broker.start_turn("claude")
    assert not broker.can("claude", Privilege.CODE_EDIT)


def test_no_turn_blocks_write(repo):
    broker = PrivilegeBroker(enforce=True)
    broker.grant("grok", "claude", {Privilege.CODE_EDIT}, human_approved=True)
    reg = ToolRegistry(broker=broker, repo_root_path=repo)
    reg.register_function("write_file", "w", _wf, write_class=Privilege.CODE_EDIT)
    with pytest.raises(HardPrivilegeError, match=r"no active turn for claude"):
        reg.call("write_file", agent="claude", path="runs/x.py", content="x")


def test_end_turn_revokes_grant(env):
    broker = PrivilegeBroker(enforce=True)
    broker.grant("grok", "claude", {Privilege.CODE_EDIT}, human_approved=True)
    broker.start_turn("claude")
    assert broker.can("claude", Privilege.CODE_EDIT)
    broker.end_turn()
    assert not broker.can("claude", Privilege.CODE_EDIT)
    assert broker._active_turn is None


def test_enforce_false_does_not_forge_human_approved(monkeypatch):
    monkeypatch.setenv("ORCA_PROFILE", "dev")
    broker = PrivilegeBroker(enforce=False)
    broker.grant("grok", "claude", {Privilege.CODE_EDIT}, human_approved=False)
    st = broker.status()
    assert st["agents"]["claude"]["human_approved"] is False
    assert st["agents"]["claude"]["enforce_bypass"] is True


def test_pi5_profile_refuses_enforce_false(monkeypatch):
    monkeypatch.setenv("ORCA_PROFILE", "pi5")
    with pytest.raises(HardPrivilegeError, match=r"pi5 refuses enforce=False"):
        PrivilegeBroker(enforce=False)


def test_partial_revoke_clears_stale_human_approved(env):
    """status() must not keep advertising an approval whose privilege is gone."""
    broker = PrivilegeBroker(enforce=True)
    broker.grant("grok", "claude", {Privilege.CODE_EDIT, Privilege.READ},
                 human_approved=True)
    assert broker.status()["agents"]["claude"]["human_approved"] is True
    broker.revoke("grok", "claude", {Privilege.CODE_EDIT})
    st = broker.status()["agents"]["claude"]
    assert st["human_approved"] is False
    assert "read" in st["granted"]


# --------------------------------------------------------------------------
# Tool registry / path allowlist
# --------------------------------------------------------------------------

def test_positional_path_is_checked(repo):
    broker = PrivilegeBroker(enforce=True)
    broker.grant("grok", "claude", {Privilege.CODE_EDIT}, human_approved=True)
    broker.start_turn("claude")
    reg = ToolRegistry(broker=broker, repo_root_path=repo)
    reg.register_function("write_file", "w", _wf, write_class=Privilege.CODE_EDIT)
    with pytest.raises(HardPrivilegeError, match=r"writes into mao/ forbidden"):
        reg.call("write_file", "mao/roles.py", content="pwned", agent="claude")


def test_var_keyword_path_is_checked(repo):
    """bind() buries **kwargs one level down; the allowlist must still see it."""
    broker = PrivilegeBroker(enforce=True)
    broker.grant("grok", "claude", {Privilege.CODE_EDIT}, human_approved=True)
    broker.start_turn("claude")
    reg = ToolRegistry(broker=broker, repo_root_path=repo)
    reg.register_function("write_file", "w", lambda **kw: "ok",
                          write_class=Privilege.CODE_EDIT)
    with pytest.raises(HardPrivilegeError, match=r"writes into mao/ forbidden"):
        reg.call("write_file", agent="claude", path="mao/roles.py")


def test_var_positional_write_tool_refused_at_register(repo):
    reg = ToolRegistry(broker=None, repo_root_path=repo)
    with pytest.raises(ValueError, match=r"may not declare \*a"):
        reg.register_function("write_file", "w", lambda *a: "ok",
                              write_class=Privilege.CODE_EDIT)


def test_read_only_plus_write_class_raises(repo):
    reg = ToolRegistry(broker=None, repo_root_path=repo)
    with pytest.raises(ValueError, match=r"is_read_only=True conflicts with write_class"):
        reg.register(
            Tool("x", "d", lambda: None, write_class=Privilege.CODE_EDIT, is_read_only=True)
        )


def test_read_only_tool_is_not_write_allowlisted(repo):
    """D4 regression guard: the WRITE allowlist must never gate a READ."""
    broker = PrivilegeBroker(enforce=True)
    reg = ToolRegistry(broker=broker, repo_root_path=repo)
    reg.register_function("read_file", "r", lambda path: "contents")
    assert reg.get("read_file").write_class is None
    assert reg.call("read_file", agent="claude", path="docs/PI5.md") == "contents"


def test_escape_outside_repo_root_blocked(repo):
    broker = PrivilegeBroker(enforce=True)
    broker.grant("grok", "claude", {Privilege.CODE_EDIT}, human_approved=True)
    broker.start_turn("claude")
    reg = ToolRegistry(broker=broker, repo_root_path=repo)
    reg.register_function("write_file", "w", _wf, write_class=Privilege.CODE_EDIT)
    with pytest.raises(HardPrivilegeError, match=r"path outside repo root"):
        reg.call("write_file", agent="claude", path="../elsewhere/x.py")


def test_bgm_path_outside_root_names_bgm(repo):
    broker = PrivilegeBroker(enforce=True)
    broker.grant("grok", "claude", {Privilege.CODE_EDIT}, human_approved=True)
    broker.start_turn("claude")
    reg = ToolRegistry(broker=broker, repo_root_path=repo)
    reg.register_function("write_file", "w", _wf, write_class=Privilege.CODE_EDIT)
    with pytest.raises(HardPrivilegeError, match=r"BGM path blocked"):
        reg.call("write_file", agent="claude", path="../BGM/firmware.c")


def test_in_repo_runs_bgm_subdir_is_allowed(repo):
    """runs/bgm/ is inside Orca and inside the allowlist — not the BGM repo."""
    broker = PrivilegeBroker(enforce=True)
    broker.grant("grok", "claude", {Privilege.CODE_EDIT}, human_approved=True)
    broker.start_turn("claude")
    reg = ToolRegistry(broker=broker, repo_root_path=repo)
    reg.register_function("write_file", "w", _wf, write_class=Privilege.CODE_EDIT)
    assert reg.call("write_file", agent="claude", path="runs/bgm/notes.md") == "ok"


def test_docs_dir_not_writable(repo):
    broker = PrivilegeBroker(enforce=True)
    broker.grant("grok", "claude", {Privilege.CODE_EDIT}, human_approved=True)
    broker.start_turn("claude")
    reg = ToolRegistry(broker=broker, repo_root_path=repo)
    reg.register_function("write_file", "w", _wf, write_class=Privilege.CODE_EDIT)
    with pytest.raises(HardPrivilegeError, match=r"outside write allowlist"):
        reg.call("write_file", agent="claude", path="docs/PI5.md")


def test_custom_path_params_are_honoured(repo):
    broker = PrivilegeBroker(enforce=True)
    broker.grant("grok", "claude", {Privilege.CODE_EDIT}, human_approved=True)
    broker.start_turn("claude")
    reg = ToolRegistry(broker=broker, repo_root_path=repo)
    reg.register_function("write_file", "w", lambda sink: "ok",
                          write_class=Privilege.CODE_EDIT, path_params=("sink",))
    with pytest.raises(HardPrivilegeError, match=r"writes into mao/ forbidden"):
        reg.call("write_file", agent="claude", sink="mao/roles.py")


def test_unknown_tool_denied_for_ampere(repo):
    broker = PrivilegeBroker(enforce=True)
    broker.start_turn("ampere")
    reg = ToolRegistry(broker=broker, repo_root_path=repo)
    reg.register_function("mystery_tool", "u", lambda: "x")
    assert reg.get("mystery_tool").write_class == Privilege.UNCLASSIFIED
    with pytest.raises(HardPrivilegeError, match=r"ampere lacks unclassified"):
        reg.call("mystery_tool", agent="ampere")


def test_unknown_tool_denied_for_grok(repo):
    broker = PrivilegeBroker(enforce=True)
    broker.start_turn("grok")
    reg = ToolRegistry(broker=broker, repo_root_path=repo)
    reg.register_function("mystery_tool", "u", lambda: "x")
    with pytest.raises(HardPrivilegeError, match=r"grok lacks unclassified"):
        reg.call("mystery_tool", agent="grok")


def test_repo_root_required(env):
    env.setenv("ORCA_PROFILE", "pi5")
    with pytest.raises(HardPrivilegeError, match=r"ORCA_REPO_ROOT is required"):
        ToolRegistry(broker=PrivilegeBroker(enforce=True))


def test_agent_is_keyword_only(repo):
    """agent= must not be positionally settable, or the identity race returns."""
    sig = inspect.signature(ToolRegistry.call)
    assert sig.parameters["agent"].kind is inspect.Parameter.KEYWORD_ONLY


# --------------------------------------------------------------------------
# Cost
# --------------------------------------------------------------------------

def test_day_counter_survives_restart(tmp_path):
    p = tmp_path / "cost_day.json"
    DayCostStore(p).add(1.25)
    assert DayCostStore(p).read()["cost_usd"] == 1.25


def test_preflight_blocks_when_estimate_exceeds_remaining(tmp_path, env):
    tracker = UsageTracker(
        per_day_ceiling_usd=1.0,
        per_run_ceiling_usd=10.0,
        day_store=DayCostStore(tmp_path / "cost_day.json"),
    )
    tracker.day_store.add(0.9)
    with pytest.raises(CostCapExceeded, match=r"preflight per-day exceeded"):
        tracker.preflight(0.2)


def test_corrupt_ledger_raises_even_without_ceiling(tmp_path):
    p = tmp_path / "cost_day.json"
    p.write_text("{not json")
    with pytest.raises(CostLedgerCorrupt, match=r"corrupt ledger"):
        DayCostStore(p).add(0.01)


def test_corrupt_ledger_is_not_a_runtimeerror(tmp_path):
    """One `except RuntimeError` upstream must not re-create the N4 swallow."""
    assert not issubclass(CostLedgerCorrupt, RuntimeError)
    assert issubclass(CostLedgerCorrupt, OrcaError)
    assert not issubclass(CostCapExceeded, RuntimeError)


def test_record_keeps_usage_on_breach(tmp_path, env):
    tracker = UsageTracker(
        per_run_ceiling_usd=0.5,
        per_day_ceiling_usd=100.0,
        day_store=DayCostStore(tmp_path / "c.json"),
    )
    with pytest.raises(CostCapExceeded, match=r"per-run ceiling exceeded"):
        tracker.record("claude", "echo", cost_usd=0.9)
    assert len(tracker.records) == 1
    assert tracker.records[0].cost_usd == 0.9
    assert tracker.records[0].posted is True


def test_day_ceiling_breach_marks_record_unposted(tmp_path, env):
    """Local tally and durable ledger diverge on a day breach — say so."""
    tracker = UsageTracker(
        per_day_ceiling_usd=0.5,
        per_run_ceiling_usd=100.0,
        day_store=DayCostStore(tmp_path / "c.json"),
    )
    with pytest.raises(CostCapExceeded, match=r"per-day ceiling"):
        tracker.record("claude", "echo", cost_usd=0.9)
    assert len(tracker.unposted()) == 1
    assert tracker.total_cost(posted_only=True) == 0.0


def test_missing_repo_root_does_not_disable_day_cap(env):
    """D1: construction must fail, not silently drop the ledger."""
    with pytest.raises(OrcaConfigError, match=r"ORCA_REPO_ROOT required"):
        UsageTracker(per_run_ceiling_usd=1.0, per_day_ceiling_usd=1.0)


def test_pi5_profile_requires_both_ceilings(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCA_PROFILE", "pi5")
    with pytest.raises(HardPrivilegeError, match=r"requires per_run_ceiling_usd"):
        UsageTracker(day_store=DayCostStore(tmp_path / "c.json"))


def test_clock_backward_refused(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"day": "2099-01-01", "cost_usd": 1.0}')
    with pytest.raises(CostLedgerCorrupt, match=r"clock went backward"):
        DayCostStore(p).add(0.01)


def test_clock_forward_jump_refused(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"day": "2000-01-01", "cost_usd": 1.0}')
    with pytest.raises(CostLedgerCorrupt, match=r"clock jumped forward too far"):
        DayCostStore(p).add(0.01)


def test_kill_switch_blocks_preflight_and_record(tmp_path, env):
    tracker = UsageTracker(kill_switch=True,
                           day_store=DayCostStore(tmp_path / "c.json"))
    with pytest.raises(CostCapExceeded, match=r"kill_switch ON"):
        tracker.preflight(0.0)
    with pytest.raises(CostCapExceeded, match=r"kill_switch ON"):
        tracker.record("claude", "echo", cost_usd=0.0)


# --------------------------------------------------------------------------
# Pricing + NTP
# --------------------------------------------------------------------------

def test_unknown_model_refused(env):
    with pytest.raises(UnknownModelError, match=r"Unknown model 'grok-2-latest'"):
        pricing.estimate_cost("grok-2-latest", 1000, 1000)


def test_floating_alias_not_in_table():
    assert "grok-2" not in pricing.PRICE_TABLE
    assert "grok-2-latest" not in pricing.PRICE_TABLE


def test_model_string_is_normalized(env):
    assert pricing.estimate_cost("  GROK-2-1212 ", 1_000_000, 0) == 2.0


def test_stale_price_table_refuses(monkeypatch):
    monkeypatch.setattr(pricing, "PRICE_TABLE_AS_OF", "2020-01-01")
    with pytest.raises(PriceTableStaleError, match=r"PRICE_TABLE is \d+ days old"):
        pricing.estimate_cost("echo", 10, 10)


def test_unknown_model_is_not_a_valueerror():
    assert not issubclass(UnknownModelError, ValueError)
    assert issubclass(UnknownModelError, OrcaError)


def test_ntp_unsynced_refuses_with_stage(monkeypatch):
    monkeypatch.setattr(scheduler_ntp, "ntp_synchronized", lambda: False)
    with pytest.raises(NTPNotSyncedError, match=r"stage='fire'"):
        scheduler_ntp.require_ntp_or_refuse(stage="fire")


def test_ntp_synced_permits_arming(monkeypatch):
    monkeypatch.setattr(scheduler_ntp, "ntp_synchronized", lambda: True)
    scheduler_ntp.require_ntp_or_refuse(stage="arm")


def test_ntp_error_is_orca_error():
    assert issubclass(NTPNotSyncedError, OrcaError)
