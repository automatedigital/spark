"""Kanban tools — only available when SPARK_KANBAN_TASK is set (dispatcher workers)."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from tools.registry import registry


def _session_context_metadata() -> Dict[str, Any]:
    """Return current gateway session metadata when available."""
    try:
        from gateway.session_context import get_session_env
    except Exception:
        get_session_env = None  # type: ignore[assignment]

    def _get(name: str) -> str:
        if get_session_env is not None:
            return get_session_env(name, "")
        return os.getenv(name, "")

    platform = _get("SPARK_SESSION_PLATFORM").strip()
    chat_id = _get("SPARK_SESSION_CHAT_ID").strip()
    chat_type = _get("SPARK_SESSION_CHAT_TYPE").strip() or "dm"
    thread_id = _get("SPARK_SESSION_THREAD_ID").strip()
    user_id = _get("SPARK_SESSION_USER_ID").strip()
    user_name = _get("SPARK_SESSION_USER_NAME").strip()
    session_key = _get("SPARK_SESSION_KEY").strip()
    source: Dict[str, Any] = {}
    if platform and chat_id:
        source = {
            "platform": platform,
            "chat_id": chat_id,
            "chat_name": _get("SPARK_SESSION_CHAT_NAME").strip() or None,
            "chat_type": chat_type,
            "user_id": user_id or None,
            "user_name": user_name or None,
            "thread_id": thread_id or None,
        }
    return {
        "platform": platform or None,
        "chat_id": chat_id or None,
        "thread_id": thread_id or None,
        "chat_type": chat_type,
        "user_id": user_id or None,
        "user_name": user_name or None,
        "session_key": session_key or None,
        "source": source,
    }


def _kanban_config() -> Dict[str, Any]:
    try:
        from spark_cli.config import load_config

        cfg = load_config().get("kanban", {})
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def _task_id(args: dict, kw: dict) -> str:
    tid = args.get("task_id") or kw.get("task_id") or os.getenv("SPARK_KANBAN_TASK")
    if not tid:
        raise ValueError("No kanban task id (set SPARK_KANBAN_TASK)")
    return str(tid)


def _kanban_available() -> bool:
    return bool(os.getenv("SPARK_KANBAN_TASK"))


def kanban_show(task_id: Optional[str] = None, **kw: Any) -> str:
    from core import kanban_db as kb

    tid = task_id or os.getenv("SPARK_KANBAN_TASK")
    if not tid:
        return json.dumps({"error": "No task id"})
    detail = kb.get_task_detail(tid)
    if not detail:
        return json.dumps({"error": "Task not found"})
    return json.dumps({"ok": True, "task": detail}, default=str)


def kanban_heartbeat(note: str = "", **kw: Any) -> str:
    from core import kanban_db as kb

    tid = os.getenv("SPARK_KANBAN_TASK")
    if not tid:
        return json.dumps({"error": "No SPARK_KANBAN_TASK"})
    kb.heartbeat(tid, note=note or "")
    return json.dumps({"ok": True})


def kanban_complete(
    summary: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    result: str = "",
) -> str:
    from core import kanban_db as kb

    tid = os.getenv("SPARK_KANBAN_TASK")
    if not tid:
        return json.dumps({"error": "No SPARK_KANBAN_TASK"})
    meta = _session_context_metadata()
    row = kb.complete_task(
        tid,
        summary=summary,
        metadata=metadata or {},
        result=result,
        actor=meta.get("user_name") or meta.get("user_id") or "worker",
        origin_session_key=meta.get("session_key"),
        origin_kind="kanban_tool",
    )
    if not row:
        return json.dumps({"error": "Task not found"})
    return json.dumps({"ok": True, "task": row}, default=str)


def kanban_block(reason: str, **kw: Any) -> str:
    from core import kanban_db as kb

    tid = os.getenv("SPARK_KANBAN_TASK")
    if not tid:
        return json.dumps({"error": "No SPARK_KANBAN_TASK"})
    meta = _session_context_metadata()
    row = kb.block_task(
        tid,
        reason,
        actor=meta.get("user_name") or meta.get("user_id") or "worker",
        origin_session_key=meta.get("session_key"),
        origin_kind="kanban_tool",
    )
    if not row:
        return json.dumps({"error": "Task not found"})
    return json.dumps({"ok": True, "task": row}, default=str)


def kanban_comment(task_id: str, body: str, author: str = "worker", **kw: Any) -> str:
    from core import kanban_db as kb

    meta = _session_context_metadata()
    cid = kb.add_comment(
        task_id,
        body,
        author,
        actor=author or meta.get("user_name") or meta.get("user_id") or "worker",
        origin_session_key=meta.get("session_key"),
        origin_kind="kanban_tool",
    )
    return json.dumps({"ok": True, "comment_id": cid})


def kanban_create_tool(
    title: str,
    assignee: str,
    body: str = "",
    parents: Optional[List[str]] = None,
    tenant: str = "",
    priority: int = 0,
    **kw: Any,
) -> str:
    from core import kanban_db as kb

    board = os.getenv("SPARK_KANBAN_BOARD", "default")
    meta = _session_context_metadata()
    cfg = _kanban_config()
    row = kb.create_task(
        title=title,
        board_slug=board,
        body=body,
        assignee=assignee,
        tenant=tenant or None,
        priority=priority,
        parent_ids=parents or [],
        owner_profile=assignee,
        owner_platform=meta.get("platform"),
        owner_channel=meta.get("chat_id"),
        owner_thread_id=meta.get("thread_id"),
        creator_session_key=meta.get("session_key"),
        creator_session_source=meta.get("source") if isinstance(meta.get("source"), dict) else {},
        notify_on_changes=bool(cfg.get("notify_on_changes", False)),
        wake_on_changes=bool(cfg.get("wake_creator_on_changes", False)),
    )
    return json.dumps({"ok": True, "task": row}, default=str)


def kanban_link_tool(parent_id: str, child_id: str, **kw: Any) -> str:
    from core import kanban_db as kb

    try:
        kb.add_link(parent_id, child_id)
        return json.dumps({"ok": True})
    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e)})


registry.register(
    name="kanban_show",
    toolset="kanban",
    schema={
        "name": "kanban_show",
        "description": "Load full Kanban task context (body, parents, runs, comments). Uses SPARK_KANBAN_TASK if task_id omitted.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task id (default: env SPARK_KANBAN_TASK)",
                },
            },
        },
    },
    handler=lambda args, **kw: kanban_show(
        task_id=args.get("task_id"),
    ),
    check_fn=_kanban_available,
)

registry.register(
    name="kanban_heartbeat",
    toolset="kanban",
    schema={
        "name": "kanban_heartbeat",
        "description": "Signal liveness during long-running Kanban work.",
        "parameters": {
            "type": "object",
            "properties": {
                "note": {"type": "string", "description": "Short status note"},
            },
        },
    },
    handler=lambda args, **kw: kanban_heartbeat(note=str(args.get("note", ""))),
    check_fn=_kanban_available,
)

registry.register(
    name="kanban_complete",
    toolset="kanban",
    schema={
        "name": "kanban_complete",
        "description": (
            "Mark the Kanban task ready for user review with summary + structured "
            "metadata for handoff."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "result": {"type": "string", "description": "Short one-line result for the task row"},
                "metadata": {"type": "object", "description": "JSON object e.g. changed_files, tests_run"},
            },
            "required": [],
        },
    },
    handler=lambda args, **kw: kanban_complete(
        summary=str(args.get("summary", "")),
        metadata=args.get("metadata") if isinstance(args.get("metadata"), dict) else {},
        result=str(args.get("result", "")),
    ),
    check_fn=_kanban_available,
)

registry.register(
    name="kanban_block",
    toolset="kanban",
    schema={
        "name": "kanban_block",
        "description": "Block the Kanban task pending human input or external dependency.",
        "parameters": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
        },
    },
    handler=lambda args, **kw: kanban_block(reason=str(args.get("reason", ""))),
    check_fn=_kanban_available,
)

registry.register(
    name="kanban_comment",
    toolset="kanban",
    schema={
        "name": "kanban_comment",
        "description": "Append a durable comment to a Kanban task thread.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "body": {"type": "string"},
                "author": {"type": "string"},
            },
            "required": ["task_id", "body"],
        },
    },
    handler=lambda args, **kw: kanban_comment(
        task_id=str(args.get("task_id", "")),
        body=str(args.get("body", "")),
        author=str(args.get("author", "worker")),
    ),
    check_fn=_kanban_available,
)

registry.register(
    name="kanban_create",
    toolset="kanban",
    schema={
        "name": "kanban_create",
        "description": "Create a child Kanban task on the current board (orchestrator use).",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "assignee": {"type": "string"},
                "body": {"type": "string"},
                "parents": {"type": "array", "items": {"type": "string"}},
                "tenant": {"type": "string"},
                "priority": {"type": "integer"},
            },
            "required": ["title", "assignee"],
        },
    },
    handler=lambda args, **kw: kanban_create_tool(
        title=str(args.get("title", "")),
        assignee=str(args.get("assignee", "")),
        body=str(args.get("body", "")),
        parents=args.get("parents") if isinstance(args.get("parents"), list) else [],
        tenant=str(args.get("tenant", "")),
        priority=int(args.get("priority", 0) or 0),
    ),
    check_fn=_kanban_available,
)

registry.register(
    name="kanban_link",
    toolset="kanban",
    schema={
        "name": "kanban_link",
        "description": "Add parent→child dependency between tasks.",
        "parameters": {
            "type": "object",
            "properties": {
                "parent_id": {"type": "string"},
                "child_id": {"type": "string"},
            },
            "required": ["parent_id", "child_id"],
        },
    },
    handler=lambda args, **kw: kanban_link_tool(
        parent_id=str(args.get("parent_id", "")),
        child_id=str(args.get("child_id", "")),
    ),
    check_fn=_kanban_available,
)
