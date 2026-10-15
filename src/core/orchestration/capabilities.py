"""Capability snapshots describe exercised local controls, never provider promises."""

from __future__ import annotations

from typing import Any

TERMINAL_CHILD_STATES = frozenset({"completed", "failed", "interrupted", "cancelled", "uncertain"})


def owned_live_child(parent: Any, run: dict[str, Any]) -> Any:
    if parent is None or run.get("status") in TERMINAL_CHILD_STATES:
        return None
    child_sid = run.get("child_session_id")
    lock = getattr(parent, "_active_children_lock", None)
    if lock:
        with lock:
            children = list(getattr(parent, "_active_children", []) or [])
    else:
        children = list(getattr(parent, "_active_children", []) or [])
    return next((child for child in children
                 if ((child_sid and getattr(child, "session_id", None) == child_sid)
                     or (run.get("id") and getattr(child, "_spark_subagent_id", None) == run["id"]))
                 and callable(getattr(child, "interrupt", None))), None)


def child_capabilities(
    parent: Any, runs: list[dict[str, Any]], delegation: dict[str, Any]
) -> dict[str, Any]:
    live = any(owned_live_child(parent, run) is not None for run in runs)
    async_enabled = delegation.get("async_enabled") is True
    retryable = async_enabled and parent is not None and any(
        run.get("execution_mode") == "async" and run.get("status") in {"failed", "interrupted", "cancelled"}
        for run in runs
    )
    def selection(key):
        value = delegation.get(key) or (getattr(parent, key, None) if parent is not None else None)
        return value if isinstance(value, str) else None
    return {
        "schema_version": 1,
        "controls": {
            "inspect": {"supported": True, "reason": None},
            "interrupt": {"supported": live,
                          "reason": None if live else "No live owned child is available"},
            "retry": {"supported": retryable, "reason": None if retryable else (
                "Async execution is disabled" if not async_enabled else "No owned retryable child is available")},
        },
        "runtime": {"available": parent is not None, "model": selection("model"),
                    "provider": selection("provider"), "async_enabled": async_enabled,
                    "worker_kind": "process_local", "completion_delivery": "next_explicit_parent_turn"},
    }
