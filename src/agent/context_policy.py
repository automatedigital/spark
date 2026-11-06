"""Conservative policy for user-requested compaction at an idle boundary."""
from __future__ import annotations

import copy
import json
import queue
import re
import threading
from itertools import groupby
from typing import Any

SUMMARY_TIMEOUT_SECONDS = 20.0
SUMMARY_OUTPUT_TOKENS = 4000
SUMMARY_INPUT_TOKENS = 32000
_PROTECTED = re.compile(
    r"\b(?:decid\w*|chose|chosen|pending|unresolved|approval|permission|must|never|"
    r"preserve|constraint|artifact|checkpoint|blocked|remaining|question)\b|\?", re.I,
)


def protected_message(message: dict[str, Any]) -> bool:
    """Only plain assistant narrative is eligible for a lossy summary."""
    content = message.get("content")
    return bool(
        message.get("role") != "assistant" or message.get("tool_calls")
        or message.get("reasoning") or message.get("reasoning_details")
        or message.get("codex_reasoning_items") or not isinstance(content, str)
        or _PROTECTED.search(content) or content.startswith("[CONTEXT")
        or content.startswith("[TYPED CONTEXT")
    )


def reduce_tool_output(content: str) -> str:
    """Run-length encode identical lines; retain every distinct line and count.

    JSON envelopes remain JSON, including exit status and artifact metadata.
    Unique output is never truncated and the stored transcript is never edited.
    """
    def reduce_lines(text: str) -> str:
        output = []
        for line, group in groupby(text.splitlines(keepends=True)):
            count = sum(1 for _ in group)
            if count >= 4 and line.strip():
                output.append(line.rstrip("\r\n") + f"\n[preceding line repeated {count} times total]\n")
            else:
                output.extend([line] * count)
        reduced = "".join(output)
        return reduced if len(reduced) < len(text) else text

    try:
        parsed = json.loads(content)
    except (ValueError, TypeError):
        return reduce_lines(content)
    if not isinstance(parsed, dict):
        return content
    for key in ("stdout", "stderr", "output", "content"):
        if isinstance(parsed.get(key), str):
            parsed[key] = reduce_lines(parsed[key])
    reduced = json.dumps(parsed, ensure_ascii=False)
    return reduced if len(reduced) < len(content) else content


def validate_tool_pairs(messages: list[dict[str, Any]]) -> bool:
    pending: set[str] = set()
    for message in messages:
        if message.get("role") == "tool":
            call_id = message.get("tool_call_id")
            if call_id not in pending:
                return False
            pending.remove(call_id)
        else:
            if pending:
                return False
            for call in message.get("tool_calls") or []:
                call_id = call.get("id") if isinstance(call, dict) else getattr(call, "id", None)
                if not call_id or call_id in pending:
                    return False
                pending.add(call_id)
    return not pending


# Bound abandoned provider calls too. A late result has no access to live state.
_SUMMARY_SLOTS = threading.BoundedSemaphore(2)


def bounded_summary(compressor, messages, focus_topic):
    from agent.model_metadata import estimate_messages_tokens_rough

    if estimate_messages_tokens_rough(messages) > SUMMARY_INPUT_TOKENS:
        return None
    if not _SUMMARY_SLOTS.acquire(blocking=False):
        return None
    isolated = copy.copy(compressor)
    isolated._summary_timeout = SUMMARY_TIMEOUT_SECONDS
    isolated._summary_output_limit = min(SUMMARY_OUTPUT_TOKENS, compressor.max_summary_tokens)
    isolated._previous_summary = None
    result = queue.Queue(maxsize=1)

    def run():
        try:
            result.put(isolated._generate_summary(messages, focus_topic=focus_topic))
        except Exception:
            result.put(None)
        finally:
            _SUMMARY_SLOTS.release()

    threading.Thread(target=run, name="context-summary", daemon=True).start()
    try:
        return result.get(timeout=SUMMARY_TIMEOUT_SECONDS)
    except queue.Empty:
        return None
