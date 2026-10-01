import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "benchmark_orca_math.py"
SPEC = importlib.util.spec_from_file_location("benchmark_orca_math", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_numeric_scoring_accepts_display_punctuation_without_false_failure():
    values = MODULE.numbers_in_text("After inspection, 1,657 usable fasteners remain.")
    assert 1657.0 in values


def test_numeric_scoring_rejects_outside_tolerance():
    assert MODULE.close_enough(90.0, 90.0, 1e-9)
    assert not MODULE.close_enough(0.9, 90.0, 1e-9)


def test_nearest_rank_percentile_and_wilson_bounds():
    assert MODULE.nearest_rank([1, 2, 3, 4, 5], 0.95) == 5
    low, high = MODULE.wilson_interval(3, 7)
    assert 0 <= low < 3 / 7 < high <= 1


def test_orca_requires_deterministic_tools_for_quantitative_answers():
    from orca.bots import BOT_PROGRAMS

    prompt = BOT_PROGRAMS["orca"].system_prompt()
    assert "using it is mandatory" in prompt
    assert "unverified numeric engineering result" in prompt
