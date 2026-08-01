"""Turn lifecycle initialization separated from provider execution."""

from __future__ import annotations

from typing import Any


def reset_turn_state(agent: Any) -> None:
    """Reset counters that are scoped to one user turn, not one session."""
    agent._invalid_tool_retries = 0
    agent._invalid_json_retries = 0
    agent._empty_content_retries = 0
    agent._incomplete_scratchpad_retries = 0
    agent._codex_incomplete_retries = 0
    agent._thinking_prefill_retries = 0
    agent._last_content_with_tools = None
    agent._mute_post_response = False
    agent._unicode_sanitization_passes = 0
