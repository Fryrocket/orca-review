"""Bounded conversation context. Stored text is context, never authority."""

from .security import redact_text


MAX_HISTORY_MESSAGES = 20
MAX_HISTORY_CHARS = 12_000


def validate_history(history=None):
    if history is None:
        return []
    if not isinstance(history, list) or len(history) > MAX_HISTORY_MESSAGES:
        raise ValueError("conversation history must contain at most 20 messages")
    result = []
    total = 0
    for item in history:
        if (not isinstance(item, dict) or set(item) != {"role", "content"}
                or not isinstance(item["role"], str) or item["role"] not in {"user", "assistant"}
                or not isinstance(item["content"], str) or not item["content"].strip()):
            raise ValueError("conversation history must contain user/assistant text only")
        total += len(item["content"])
        if total > MAX_HISTORY_CHARS:
            raise ValueError("conversation history exceeds 12000 characters")
        if redact_text(item["content"]) != item["content"]:
            raise ValueError("conversation history contains secret-shaped data")
        result.append(dict(item))
    return result


def recent_history(history, limit):
    result = []
    remaining = max(0, limit)
    for item in reversed(history):
        if len(item["content"]) > remaining:
            break
        result.insert(0, item)
        remaining -= len(item["content"])
    return result
