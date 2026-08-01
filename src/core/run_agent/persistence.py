"""Small persistence transformations shared by every AIAgent exit path."""

from __future__ import annotations

from typing import Any


def apply_user_message_override(
    messages: list[dict[str, Any]], index: int | None, override: str | None
) -> bool:
    """Replace an API-only user message before session persistence."""
    if override is None or index is None or not 0 <= index < len(messages):
        return False
    message = messages[index]
    if not isinstance(message, dict) or message.get("role") != "user":
        return False
    message["content"] = override
    return True
