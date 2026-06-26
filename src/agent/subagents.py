"""Canonical lifecycle events for delegated subagents.

The delegate tool is used by several frontends, so lifecycle payloads must be
plain JSON data, predictable, and small enough to forward through progress
channels without surprising chat or web transports.
"""

from __future__ import annotations

import json
import math
import time
import uuid
from collections.abc import Callable
from typing import Any

SUBAGENT_EVENT_SCHEMA = "spark.subagent.lifecycle.v1"
SUBAGENT_LIFECYCLE_CALLBACK_EVENT = "subagent.lifecycle"

SUBAGENT_LIFECYCLE_EVENTS = frozenset(
    {
        "created",
        "started",
        "thinking",
        "tool_started",
        "tool_output",
        "tool_completed",
        "status",
        "completed",
        "failed",
        "interrupted",
    }
)

MAX_TEXT_CHARS = 500
MAX_LONG_TEXT_CHARS = 2000
MAX_COLLECTION_ITEMS = 20
MAX_PAYLOAD_DEPTH = 4

SUBAGENT_NAME_POOL = (
    "Ampere",
    "Cicero",
    "Curie",
    "Darwin",
    "Euclid",
    "Faraday",
    "Galileo",
    "Hopper",
    "Kepler",
    "Lovelace",
    "Maxwell",
    "Newton",
    "Noether",
    "Pascal",
    "Turing",
    "Vega",
)

SUBAGENT_COLOR_POOL = (
    "#7dd3fc",
    "#fbbf24",
    "#c084fc",
    "#fb7185",
    "#34d399",
    "#f97316",
    "#a5b4fc",
    "#2dd4bf",
)


def subagent_identity(task_index: int, task_count: int = 1) -> dict[str, Any]:
    """Return deterministic display identity fields for a subagent."""
    try:
        idx = int(task_index)
    except (TypeError, ValueError):
        idx = 0
    try:
        count = max(1, int(task_count))
    except (TypeError, ValueError):
        count = 1

    number = idx + 1
    return {
        "subagent_id": f"subagent-{number}",
        "task_index": idx,
        "task_number": number,
        "task_count": count,
        "display_name": f"Subagent {number}",
        "short_name": f"S{number}",
    }


def _run_display_identity(run_token: str, task_index: int) -> dict[str, str]:
    """Return a generated, stable display identity for a persisted run."""
    try:
        seed = int(str(run_token)[:8], 16)
    except (TypeError, ValueError):
        seed = int(time.time() * 1000)
    name = SUBAGENT_NAME_POOL[(seed + task_index) % len(SUBAGENT_NAME_POOL)]
    color = SUBAGENT_COLOR_POOL[(seed + task_index) % len(SUBAGENT_COLOR_POOL)]
    return {
        "display_name": name,
        "short_name": name[:1].upper(),
        "color": color,
    }


def _truncate_text(value: str, limit: int = MAX_TEXT_CHARS) -> str:
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return value[: limit - 3] + "..."


def _json_safe(value: Any, *, depth: int = 0) -> Any:
    """Convert arbitrary Python data into bounded JSON-safe values."""
    if depth >= MAX_PAYLOAD_DEPTH:
        return _truncate_text(str(value))

    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return _truncate_text(value)

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        items = list(value.items())
        for key, item in items[:MAX_COLLECTION_ITEMS]:
            out[_truncate_text(str(key), 80)] = _json_safe(item, depth=depth + 1)
        if len(items) > MAX_COLLECTION_ITEMS:
            out["_truncated"] = True
            out["_omitted_items"] = len(items) - MAX_COLLECTION_ITEMS
        return out

    if isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
        out = [_json_safe(item, depth=depth + 1) for item in items[:MAX_COLLECTION_ITEMS]]
        if len(items) > MAX_COLLECTION_ITEMS:
            out.append(
                {
                    "_truncated": True,
                    "_omitted_items": len(items) - MAX_COLLECTION_ITEMS,
                }
            )
        return out

    return _truncate_text(str(value))


def make_subagent_event(
    event: str,
    *,
    task_index: int,
    task_count: int = 1,
    goal: str | None = None,
    child_session_id: str | None = None,
    model: str | None = None,
    tool_name: str | None = None,
    preview: str | None = None,
    args: Any = None,
    duration_seconds: float | None = None,
    is_error: bool | None = None,
    result_lines: int | None = None,
    summary: str | None = None,
    error: str | None = None,
    api_calls: int | None = None,
    exit_reason: str | None = None,
    tokens: Any = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a bounded, JSON-safe subagent lifecycle event."""
    if event not in SUBAGENT_LIFECYCLE_EVENTS:
        raise ValueError(f"Unknown subagent lifecycle event: {event}")

    identity = subagent_identity(task_index, task_count)
    body: dict[str, Any] = {
        "schema": SUBAGENT_EVENT_SCHEMA,
        "type": f"subagent.{event}",
        "event": event,
        **identity,
    }

    if goal:
        body["goal_preview"] = _truncate_text(goal.strip(), 160)
    if child_session_id:
        body["child_session_id"] = _truncate_text(str(child_session_id), 120)
    if model:
        body["model"] = _truncate_text(str(model), 160)

    event_payload: dict[str, Any] = {}
    if payload:
        event_payload.update(_json_safe(payload))
    if tool_name:
        event_payload["tool"] = _truncate_text(str(tool_name), 120)
    if preview:
        event_payload["preview"] = _truncate_text(str(preview))
    if args is not None:
        event_payload["args"] = _json_safe(args)
    if duration_seconds is not None:
        try:
            event_payload["duration_seconds"] = round(float(duration_seconds), 3)
        except (TypeError, ValueError):
            pass
    if is_error is not None:
        event_payload["is_error"] = bool(is_error)
    if result_lines is not None:
        try:
            event_payload["result_lines"] = max(0, int(result_lines))
        except (TypeError, ValueError):
            pass
    if summary:
        event_payload["summary"] = _truncate_text(str(summary), MAX_LONG_TEXT_CHARS)
    if error:
        event_payload["error"] = _truncate_text(str(error), MAX_LONG_TEXT_CHARS)
    if api_calls is not None:
        try:
            event_payload["api_calls"] = max(0, int(api_calls))
        except (TypeError, ValueError):
            pass
    if exit_reason:
        event_payload["exit_reason"] = _truncate_text(str(exit_reason), 80)
    if tokens is not None:
        event_payload["tokens"] = _json_safe(tokens)

    if event_payload:
        body["payload"] = event_payload

    # Last-line defense: ensure the event can always be serialized as JSON.
    json.dumps(body, ensure_ascii=False, allow_nan=False)
    return body


def emit_subagent_event(
    callback: Callable[..., Any] | None,
    event: dict[str, Any],
) -> None:
    """Emit a lifecycle event through the existing progress callback surface."""
    if not callback:
        return
    preview = event.get("goal_preview")
    payload = event.get("payload")
    if isinstance(payload, dict):
        preview = payload.get("preview") or payload.get("summary") or payload.get("error") or preview
    try:
        callback(
            SUBAGENT_LIFECYCLE_CALLBACK_EVENT,
            event.get("subagent_id"),
            preview,
            event,
            event=event,
        )
    except Exception:
        pass


def make_run_record(
    *,
    parent_session_id: str | None = None,
    child_session_id: str | None = None,
    task_index: int,
    task_count: int = 1,
    task: str,
    context: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    toolsets: list[str] | None = None,
) -> dict[str, Any]:
    """Create stable lifecycle metadata shared by events for one child run."""
    run_token = uuid.uuid4().hex[:12]
    identity = {
        **subagent_identity(task_index, task_count),
        **_run_display_identity(run_token, task_index),
    }
    record = {
        "id": f"subagent_{run_token}",
        **identity,
        "parent_session_id": parent_session_id,
        "child_session_id": child_session_id,
        "task": task,
        "context_preview": _truncate_text((context or "").strip(), 240) if context else None,
        "model": model,
        "provider": provider,
        "toolsets": list(toolsets or []),
    }
    return _json_safe(record)


def emit(parent_agent: Any, run_record: dict[str, Any], event: str, payload: dict[str, Any] | None = None) -> None:
    """Emit a canonical lifecycle event to dedicated and progress callbacks."""
    if event not in SUBAGENT_LIFECYCLE_EVENTS:
        return

    payload = payload or {}
    task_index = int(run_record.get("task_index", 0) or 0)
    task_count = int(run_record.get("task_count", 1) or 1)
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}

    lifecycle_event = make_subagent_event(
        event,
        task_index=task_index,
        task_count=task_count,
        goal=run_record.get("task"),
        child_session_id=run_record.get("child_session_id"),
        model=payload.get("model") or result.get("model") or run_record.get("model"),
        tool_name=payload.get("tool") or payload.get("name"),
        preview=payload.get("preview") or payload.get("text"),
        args=payload.get("args"),
        duration_seconds=payload.get("duration_seconds") or payload.get("duration") or result.get("duration_seconds"),
        is_error=payload.get("is_error"),
        result_lines=payload.get("result_lines"),
        summary=payload.get("summary") or result.get("summary"),
        error=payload.get("error") or result.get("error"),
        api_calls=payload.get("api_calls") or result.get("api_calls"),
        exit_reason=payload.get("exit_reason") or result.get("exit_reason"),
        tokens=payload.get("tokens") or result.get("tokens"),
        payload={
            "parent_session_id": run_record.get("parent_session_id"),
            "provider": run_record.get("provider"),
            "toolsets": run_record.get("toolsets"),
            **{
                key: value
                for key, value in payload.items()
                if key not in {
                    "args",
                    "duration",
                    "duration_seconds",
                    "error",
                    "exit_reason",
                    "is_error",
                    "model",
                    "name",
                    "preview",
                    "result",
                    "result_lines",
                    "summary",
                    "text",
                    "tokens",
                    "tool",
                }
            },
        },
    )
    run_id = run_record.get("id") or lifecycle_event.get("subagent_id")
    lifecycle_event["id"] = run_id
    lifecycle_event["run_id"] = run_id
    lifecycle_event["display_name"] = run_record.get("display_name") or lifecycle_event.get("display_name")
    lifecycle_event["short_name"] = run_record.get("short_name") or lifecycle_event.get("short_name")
    lifecycle_event["color"] = run_record.get("color")
    lifecycle_event["subagent_run"] = _json_safe(run_record)

    status = {
        "created": "created",
        "started": "working",
        "thinking": "working",
        "tool_started": "working",
        "tool_output": "working",
        "tool_completed": "working",
        "status": payload.get("status") or "working",
        "completed": "completed",
        "failed": "failed",
        "interrupted": "interrupted",
    }.get(event, "working")
    now = time.time()
    run_snapshot = {
        **run_record,
        "id": run_id,
        "name": run_record.get("display_name") or run_record.get("name"),
        "glyph": run_record.get("short_name"),
        "color": run_record.get("color"),
        "status": status,
        "started_at": run_record.get("started_at") or now,
        "last_event_at": now,
    }
    if event in {"completed", "failed", "interrupted"}:
        run_snapshot["ended_at"] = now
    if result:
        run_snapshot.update(
            {
                "summary": result.get("summary"),
                "duration_seconds": result.get("duration_seconds"),
                "exit_reason": result.get("exit_reason"),
                "error": result.get("error"),
                "tokens": result.get("tokens"),
                "tool_trace": result.get("tool_trace"),
                "model": result.get("model") or run_record.get("model"),
            }
        )

    parent_attrs = getattr(parent_agent, "__dict__", {}) if parent_agent is not None else {}
    dedicated_cb = parent_attrs.get("subagent_event_callback") if isinstance(parent_attrs, dict) else None
    if not dedicated_cb:
        db = getattr(parent_agent, "_session_db", None) if parent_agent is not None else None
        if db is not None:
            try:
                if event == "created":
                    db.create_subagent_run(run_snapshot)
                else:
                    db.update_subagent_run(str(run_id), run_snapshot)
                db.append_subagent_event(str(run_id), event, lifecycle_event)
            except Exception:
                pass

    if dedicated_cb:
        try:
            dedicated_cb(lifecycle_event)
        except Exception:
            pass

    progress_cb = getattr(parent_agent, "tool_progress_callback", None) if parent_agent is not None else None
    emit_subagent_event(progress_cb, lifecycle_event)
