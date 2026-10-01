import importlib.util
import json
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "benchmark_qwen_capabilities.py"
DATASET = ROOT / "benchmarks" / "qwen_capability_profile_v1.json"
SPEC = importlib.util.spec_from_file_location("benchmark_qwen_capabilities", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_frozen_profile_is_balanced_and_well_formed():
    payload = json.loads(DATASET.read_text())
    assert payload["suite"] == "qwen-capability-profile-v1"
    assert len(payload["cases"]) == 28
    names = [case["name"] for case in payload["cases"]]
    assert len(names) == len(set(names))
    categories = defaultdict(list)
    for case in payload["cases"]:
        assert set(case["choices"]) == {"A", "B", "C", "D"}
        assert case["expected"] in case["choices"]
        categories[case["category"]].append(case["expected"])
    assert len(categories) == 7
    assert all(Counter(answers) == Counter({"A": 1, "B": 1, "C": 1, "D": 1})
               for answers in categories.values())


def test_summary_scores_categories_and_confidence_separately():
    trials = [
        {"category": "one", "pass": True, "confidence": 80,
         "latency_s": 1.0, "completion_tokens_per_elapsed_s": 40.0},
        {"category": "one", "pass": False, "confidence": 90,
         "latency_s": 2.0, "completion_tokens_per_elapsed_s": 50.0},
    ]
    summary = MODULE.summarize(trials)
    assert summary["overall"]["rate"] == 0.5
    assert summary["categories"]["one"]["passed"] == 1
    assert summary["mean_confidence_when_correct"] == 80
    assert summary["mean_confidence_when_wrong"] == 90


def test_nearest_rank_and_wilson_interval_are_bounded():
    assert MODULE.nearest_rank([1, 2, 3, 4], 0.95) == 4
    low, high = MODULE.wilson_interval(3, 4)
    assert 0 <= low < 0.75 < high <= 1
