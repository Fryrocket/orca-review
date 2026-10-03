import json
from pathlib import Path

import pytest

from orca.gemini_bridge import INTERNAL_MODEL, PROVIDER_MODEL, _read_key, _validated_payload


def request(**overrides):
    payload = {
        "model": INTERNAL_MODEL,
        "stream": False,
        "messages": [{"role": "user", "content": "hello"}],
        "max_tokens": 9000,
    }
    payload.update(overrides)
    return payload


def test_bridge_replaces_internal_alias_and_caps_output():
    forwarded = json.loads(_validated_payload(request()))
    assert forwarded["model"] == PROVIDER_MODEL
    assert forwarded["max_tokens"] == 4096
    assert forwarded["stream"] is False
    assert forwarded["extra_body"] == {
        "google": {"thinking_config": {"thinking_level": "low"}}
    }


def test_bridge_rejects_other_models_streaming_and_oversized_prompts():
    with pytest.raises(PermissionError, match="allowlisted"):
        _validated_payload(request(model="paid-model"))
    with pytest.raises(ValueError, match="streaming"):
        _validated_payload(request(stream=True))
    with pytest.raises(ValueError, match="prompt limit"):
        _validated_payload(request(messages=[{"role": "user", "content": "x" * 64001}]))


def test_key_file_is_trimmed_but_never_accepted_if_malformed(tmp_path: Path):
    key_file = tmp_path / "key"
    key_file.write_text("a" * 32 + "\n")
    assert _read_key(key_file) == "a" * 32
    key_file.write_text("contains embedded whitespace")
    with pytest.raises(ValueError, match="credential"):
        _read_key(key_file)
