"""Kanban tools — only available when SPARK_KANBAN_TASK is set (dispatcher workers)."""

from __future__ import annotations

import json
import os
from typing import Any

from tools.registry import registry


def _task_id(args: dict, kw: dict) -> str:
    tid = args.get("task_id") or kw.get("task_id") or os.getenv("SPARK_KANBAN_TASK")
    if not tid:
        raise ValueError("No kanban task id (set SPARK_KANBAN_TASK)")
    return str(tid)


def _kanban_available() -> bool:
    return bool(os.getenv("SPARK_KANBAN_TASK"))


def kanban_show(task_id: str | None = None, **kw: Any) -> str:
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
    metadata: dict[str, Any] | None = None,
    result: str = "",
) -> str:
    from core import kanban_db as kb

    tid = os.getenv("SPARK_KANBAN_TASK")
    if not tid:
        return json.dumps({"error": "No SPARK_KANBAN_TASK"})
    row = kb.complete_task(tid, summary=summary, metadata=metadata or {}, result=result)
    if not row:
        return json.dumps({"error": "Task not found"})
    return json.dumps({"ok": True, "task": row}, default=str)


def kanban_block(reason: str, **kw: Any) -> str:
    from core import kanban_db as kb

    tid = os.getenv("SPARK_KANBAN_TASK")
    if not tid:
        return json.dumps({"error": "No SPARK_KANBAN_TASK"})
    row = kb.block_task(tid, reason)
    if not row:
        return json.dumps({"error": "Task not found"})
    return json.dumps({"ok": True, "task": row}, default=str)


def kanban_comment(task_id: str, body: str, author: str = "worker", **kw: Any) -> str:
    from core import kanban_db as kb

    cid = kb.add_comment(task_id, body, author)
    return json.dumps({"ok": True, "comment_id": cid})


def kanban_create_tool(
    title: str,
    assignee: str,
    body: str = "",
    parents: list[str] | None = None,
    tenant: str = "",
    priority: int = 0,
    **kw: Any,
) -> str:
    from core import kanban_db as kb

    board = os.getenv("SPARK_KANBAN_BOARD", "default")
    row = kb.create_task(
        title=title,
        board_slug=board,
        body=body,
        assignee=assignee,
        tenant=tenant or None,
        priority=priority,
        parent_ids=parents or [],
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
