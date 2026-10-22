"""Readable Markdown rendering of already sanitized SessionDB exports.

Original Spark implementation; no upstream source is copied. Transcript text is
fenced as literal text so tool output/HTML cannot alter the document structure.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any


def _block(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(
        value, indent=2, ensure_ascii=False, default=str
    )
    fence = "`" * max(3, 1 + max((len(m[0]) for m in re.finditer(r"`+", text)), default=0))
    language = "text" if isinstance(value, str) else "json"
    return f"{fence}{language}\n{text}\n{fence}"


def _timestamp(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(value, UTC).isoformat()
        except (ValueError, OverflowError, OSError):
            pass
    return str(value)


def render_session_markdown(session: dict[str, Any]) -> str:
    """Render metadata/lineage as exported; do not fetch other sessions."""
    metadata = {k: v for k, v in session.items() if k != "messages"}
    parts = ["# Spark session", "## Session metadata", _block(metadata), "## Messages"]
    messages = session.get("messages") or []
    if not messages:
        parts.append("_No messages in this session._")
    for number, message in enumerate(messages, 1):
        role = str(message.get("role") or "message")
        # Only use a fixed role label in headings; unknown labels remain in JSON.
        label = role.capitalize() if role in {"user", "assistant", "system", "tool", "developer"} else "Message"
        parts.append(f"### {number}. {label}")
        timestamp = message.get("timestamp", message.get("created_at"))
        if timestamp is not None:
            parts.extend(["Timestamp:", _block(_timestamp(timestamp))])
        if message.get("content") is not None:
            parts.append(_block(message["content"]))
        if message.get("reasoning") is not None:
            parts.extend(["#### Reasoning", _block(message["reasoning"])])
        if message.get("tool_calls"):
            parts.extend(["#### Tool calls", _block(message["tool_calls"])])
        extra = {k: v for k, v in message.items() if k not in {
            "role", "content", "reasoning", "tool_calls", "timestamp", "created_at"
        }}
        if extra or label == "Message":
            parts.extend(["#### Message metadata", _block({"role": role, **extra})])
    return "\n\n".join(parts) + "\n"
