"""Pure message-history helpers for the AIAgent loop.

This module owns pre-provider message repair that can be tested without
constructing an agent instance. Keep these helpers side-effect-light: callers
may pass a shallow copy or the live API message list immediately before an LLM
request.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

VALID_API_ROLES = frozenset({"system", "user", "assistant", "tool", "function", "developer"})


def get_tool_call_id_static(tool_call: Any) -> str:
    """Extract a tool-call ID from a dict or SDK object."""
    if isinstance(tool_call, dict):
        return tool_call.get("id", "") or ""
    return getattr(tool_call, "id", "") or ""


def sanitize_api_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fix orphaned tool_call / tool_result pairs before every LLM call.

    Runs unconditionally so orphans from session loading or manual message
    manipulation are always caught at the provider boundary.
    """
    filtered = []
    for msg in messages:
        role = msg.get("role")
        if role not in VALID_API_ROLES:
            logger.debug(
                "Pre-call sanitizer: dropping message with invalid role %r",
                role,
            )
            continue
        filtered.append(msg)
    messages = filtered

    surviving_call_ids: set[str] = set()
    for msg in messages:
        if msg.get("role") == "assistant":
            for tool_call in msg.get("tool_calls") or []:
                call_id = get_tool_call_id_static(tool_call)
                if call_id:
                    surviving_call_ids.add(call_id)

    result_call_ids: set[str] = set()
    for msg in messages:
        if msg.get("role") == "tool":
            call_id = msg.get("tool_call_id")
            if call_id:
                result_call_ids.add(call_id)

    orphaned_results = result_call_ids - surviving_call_ids
    if orphaned_results:
        messages = [
            msg
            for msg in messages
            if not (msg.get("role") == "tool" and msg.get("tool_call_id") in orphaned_results)
        ]
        logger.debug(
            "Pre-call sanitizer: removed %d orphaned tool result(s)",
            len(orphaned_results),
        )

    missing_results = surviving_call_ids - result_call_ids
    if missing_results:
        patched: list[dict[str, Any]] = []
        for msg in messages:
            patched.append(msg)
            if msg.get("role") == "assistant":
                for tool_call in msg.get("tool_calls") or []:
                    call_id = get_tool_call_id_static(tool_call)
                    if call_id in missing_results:
                        patched.append({
                            "role": "tool",
                            "content": "[Result unavailable — see context summary above]",
                            "tool_call_id": call_id,
                        })
        messages = patched
        logger.debug(
            "Pre-call sanitizer: added %d stub tool result(s)",
            len(missing_results),
        )
    return messages
