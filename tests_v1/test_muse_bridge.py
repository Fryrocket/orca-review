import json
from pathlib import Path

import pytest

from orca.muse_bridge import INTERNAL_MODEL, _read_key, _validated_payload


def request(**overrides):
    payload = {
        "model": INTERNAL_MODEL,
        "stream": False,
        "messages": [{"role": "user", "content": "hello"}],
        "max_tokens": 9000,
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize("model", ["muse-spark-1.3", "muse-spark-1.3-contributor"])
def test_bridge_replaces_internal_alias_and_enforces_low_cost_bounds(model):
    forwarded = json.loads(_validated_payload(request(), model))
    assert forwarded["model"] == model
    assert forwarded["max_tokens"] == 2048
    assert forwarded["reasoning_effort"] == "low"
    assert forwarded["stream"] is False


def test_bridge_rejects_other_models_streaming_and_oversized_prompts():
    with pytest.raises(ValueError, match="provider model"):
        _validated_payload(request(), "unknown")
    with pytest.raises(PermissionError, match="allowlisted"):
        _validated_payload(request(model="paid-model"), "muse-spark-1.3")
    with pytest.raises(ValueError, match="streaming"):
        _validated_payload(request(stream=True), "muse-spark-1.3")
    with pytest.raises(ValueError, match="prompt limit"):
        _validated_payload(request(messages=[{"role": "user", "content": "x" * 64001}]),
                           "muse-spark-1.3")


def test_key_file_is_trimmed_but_never_accepted_if_malformed(tmp_path: Path):
    key_file = tmp_path / "key"
    key_file.write_text("a" * 32 + "\n")
    assert _read_key(key_file) == "a" * 32
    key_file.write_text("contains embedded whitespace")
    with pytest.raises(ValueError, match="credential"):
        _read_key(key_file)
