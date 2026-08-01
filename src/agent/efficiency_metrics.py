"""Low-overhead, redacted efficiency accounting for model iterations.

The recorder deliberately stores counts and timings only. Message text, tool
arguments, credentials, and response content never enter the report. Set
``SPARK_EFFICIENCY_REPORT`` to a file path to append machine-readable JSONL;
otherwise rows remain available on the agent instance for callers/tests.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agent.model_metadata import estimate_messages_tokens_rough, estimate_tokens_rough

ACCOUNTING_VERSION = "1.0"


def _json_tokens(value: Any) -> int:
    try:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    except Exception:
        text = repr(value)
    return int(estimate_tokens_rough(text))


@dataclass(frozen=True)
class RequestBreakdown:
    system_prompt_tokens: int
    conversation_tokens: int
    injected_context_tokens: int
    tool_result_tokens: int
    schema_tokens: int
    estimated_prompt_tokens: int


def measure_request(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    *,
    injected_context: str = "",
    schema_tokens: int | None = None,
) -> RequestBreakdown:
    """Return mutually exclusive estimated prompt buckets."""
    system_messages = [m for m in messages if m.get("role") == "system"]
    tool_messages = [m for m in messages if m.get("role") == "tool"]
    ordinary_messages = [
        m for m in messages if m.get("role") not in {"system", "tool"}
    ]
    injected = estimate_tokens_rough(injected_context) if injected_context else 0
    conversation = max(0, estimate_messages_tokens_rough(ordinary_messages) - injected)
    system = estimate_messages_tokens_rough(system_messages)
    tool_results = estimate_messages_tokens_rough(tool_messages)
    schemas = _json_tokens(tools or []) if schema_tokens is None else max(0, schema_tokens)
    total = system + conversation + injected + tool_results + schemas
    return RequestBreakdown(
        system_prompt_tokens=system,
        conversation_tokens=conversation,
        injected_context_tokens=injected,
        tool_result_tokens=tool_results,
        schema_tokens=schemas,
        estimated_prompt_tokens=total,
    )


def estimate_response_tokens(response: Any) -> int:
    """Estimate visible output for provider responses that omit usage fields."""
    parts: list[str] = []
    choices = getattr(response, "choices", None) or []
    for choice in choices:
        message = getattr(choice, "message", None)
        content = getattr(message, "content", None)
        if content:
            parts.append(str(content))
    for block in getattr(response, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(str(text))
    for item in getattr(response, "output", None) or []:
        for block in getattr(item, "content", None) or []:
            text = getattr(block, "text", None)
            if text:
                parts.append(str(text))
    return int(estimate_tokens_rough("\n".join(parts))) if parts else 0


@dataclass(frozen=True)
class ModelIterationAccounting:
    version: str
    session_id: str
    iteration: int
    provider: str
    model: str
    api_mode: str
    request_latency_ms: float
    system_prompt_tokens: int
    conversation_tokens: int
    injected_context_tokens: int
    tool_result_tokens: int
    schema_tokens: int
    prompt_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    output_tokens: int
    reasoning_tokens: int
    usage_source: str
    estimator_delta_tokens: int | None
    routing_reason: str | None = None
    request_class: str | None = None


@dataclass(frozen=True)
class ToolRuntimeAccounting:
    session_id: str
    iteration: int
    tool_name: str
    queue_wait_ms: float
    execution_ms: float
    result_bytes: int
    failed: bool


class EfficiencyRecorder:
    """Thread-safe bounded recorder with optional JSONL persistence."""

    def __init__(self, session_id: str, output_path: str | os.PathLike[str] | None = None):
        self.session_id = session_id
        configured = output_path or os.getenv("SPARK_EFFICIENCY_REPORT")
        self.output_path = Path(configured).expanduser() if configured else None
        self._lock = threading.Lock()
        self.model_iterations: list[dict[str, Any]] = []
        self.tool_calls: list[dict[str, Any]] = []

    def _append(self, kind: str, row: dict[str, Any]) -> None:
        payload = {"kind": kind, "recorded_at": time.time(), **row}
        with self._lock:
            target = self.model_iterations if kind == "model_iteration" else self.tool_calls
            target.append(payload)
            if len(target) > 500:
                del target[:-500]
            if self.output_path:
                self.output_path.parent.mkdir(parents=True, exist_ok=True)
                with self.output_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(payload, sort_keys=True) + "\n")

    def record_model_iteration(self, row: ModelIterationAccounting) -> None:
        self._append("model_iteration", asdict(row))

    def record_tool_call(self, row: ToolRuntimeAccounting) -> None:
        self._append("tool_call", asdict(row))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "version": ACCOUNTING_VERSION,
                "session_id": self.session_id,
                "model_iterations": list(self.model_iterations),
                "tool_calls": list(self.tool_calls),
            }
