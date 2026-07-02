"""FastAPI routes for Kanban board API."""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from core import kanban_db as kb

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/kanban", tags=["kanban"])


class TaskCreateBody(BaseModel):
    title: str
    body: str = ""
    board: str = "default"
    assignee: Optional[str] = None
    tenant: Optional[str] = None
    priority: int = 0
    parents: List[str] = Field(default_factory=list)
    idempotency_key: Optional[str] = None
    workspace_kind: str = "scratch"
    workspace_path: Optional[str] = None
    skills: List[str] = Field(default_factory=list)
    owner_profile: Optional[str] = None
    owner_platform: Optional[str] = None
    owner_channel: Optional[str] = None
    owner_thread_id: Optional[str] = None
    creator_session_key: Optional[str] = None
    creator_session_source: Dict[str, Any] = Field(default_factory=dict)
    notify_on_changes: bool = False
    wake_on_changes: bool = False
    triage: bool = False
    max_runtime_seconds: int = 0


class TaskPatchBody(BaseModel):
    status: Optional[str] = None
    title: Optional[str] = None
    body: Optional[str] = None
    assignee: Optional[str] = None
    priority: Optional[int] = None
    tenant: Optional[str] = None
    result: Optional[str] = None
    in_triage: Optional[bool] = None
    workspace_path: Optional[str] = None
    actor: Optional[str] = None
    origin_session_key: Optional[str] = None
    origin_kind: Optional[str] = None
    internal_event: bool = False


class BulkPatchBody(BaseModel):
    ids: List[str]
    status: Optional[str] = None
    assignee: Optional[str] = None
    priority: Optional[int] = None


class BulkPatchResponse(BaseModel):
    ok: bool
    errors: Dict[str, str] = Field(default_factory=dict)


class DispatchResponse(BaseModel):
    ok: Optional[bool] = None
    claimed: Optional[int] = None
    task_ids: Optional[List[str]] = None
    dry_run: Optional[bool] = None
    ready: Optional[List[str]] = None
    blocked_by_assignee: Optional[List[str]] = None


class CommentBody(BaseModel):
    body: str
    author: Optional[str] = None
    origin_session_key: Optional[str] = None
    origin_kind: Optional[str] = None
    internal_event: bool = False


class LinkBody(BaseModel):
    parent_id: str
    child_id: str


class CompleteBody(BaseModel):
    summary: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)
    result: str = ""
    actor: Optional[str] = None
    origin_session_key: Optional[str] = None
    origin_kind: Optional[str] = None
    internal_event: bool = False


class BlockBody(BaseModel):
    reason: str
    actor: Optional[str] = None
    origin_session_key: Optional[str] = None
    origin_kind: Optional[str] = None
    internal_event: bool = False


@router.get("/board")
async def board(
    board: str = "default",
    tenant: Optional[str] = None,
    assignee: Optional[str] = None,
    archived: bool = False,
    q: Optional[str] = None,
):
    try:
        return kb.get_board(
            board_slug=board,
            tenant=tenant,
            assignee=assignee,
            include_archived=archived,
            search=q,
        )
    except Exception as e:
        _log.exception("kanban board")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/{task_id}")
async def task_detail(task_id: str):
    d = kb.get_task_detail(task_id)
    if not d:
        raise HTTPException(status_code=404, detail="Task not found")
    return d


@router.post("/tasks")
async def task_create(body: TaskCreateBody):
    try:
        return kb.create_task(
            title=body.title,
            board_slug=body.board,
            body=body.body,
            assignee=body.assignee,
            tenant=body.tenant,
            priority=body.priority,
            parent_ids=body.parents,
            idempotency_key=body.idempotency_key,
            workspace_kind=body.workspace_kind,
            workspace_path=body.workspace_path,
            skills=body.skills,
            owner_profile=body.owner_profile,
            owner_platform=body.owner_platform,
            owner_channel=body.owner_channel,
            owner_thread_id=body.owner_thread_id,
            creator_session_key=body.creator_session_key,
            creator_session_source=body.creator_session_source,
            notify_on_changes=body.notify_on_changes,
            wake_on_changes=body.wake_on_changes,
            in_triage=body.triage,
            max_runtime_seconds=body.max_runtime_seconds,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except sqlite3.IntegrityError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/tasks/{task_id}")
async def task_patch(task_id: str, body: TaskPatchBody):
    try:
        provided_fields = getattr(body, "model_fields_set", None)
        if provided_fields is None:
            provided_fields = getattr(body, "__fields_set__", set())
        row = kb.patch_task(
            task_id,
            status=body.status,
            title=body.title,
            body=body.body,
            assignee=body.assignee,
            priority=body.priority,
            tenant=body.tenant,
            result=body.result,
            in_triage=body.in_triage,
            workspace_path=body.workspace_path,
            workspace_path_set="workspace_path" in provided_fields,
            actor=body.actor,
            origin_session_key=body.origin_session_key,
            origin_kind=body.origin_kind,
            internal_event=body.internal_event,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Task not found")
        return row
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/tasks/{task_id}")
async def task_delete(task_id: str):
    if kb.delete_task(task_id):
        return {"ok": True, "deleted": task_id}
    raise HTTPException(status_code=404, detail="Task not found")


@router.post("/tasks/bulk", response_model=BulkPatchResponse)
async def task_bulk(body: BulkPatchBody):
    fields: Dict[str, Any] = {
        "status": body.status,
        "assignee": body.assignee,
        "priority": body.priority,
    }
    return kb.bulk_patch(body.ids, fields)


@router.post("/tasks/{task_id}/comments")
async def task_comment(task_id: str, body: CommentBody):
    try:
        cid = kb.add_comment(
            task_id,
            body.body,
            body.author,
            actor=body.author,
            origin_session_key=body.origin_session_key,
            origin_kind=body.origin_kind,
            internal_event=body.internal_event,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True, "id": cid}


@router.post("/links")
async def link_add(body: LinkBody):
    try:
        kb.add_link(body.parent_id, body.child_id)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except sqlite3.IntegrityError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/links")
async def link_del(parent_id: str = Query(...), child_id: str = Query(...)):
    if kb.remove_link(parent_id, child_id):
        return {"ok": True}
    raise HTTPException(status_code=404, detail="Link not found")


@router.post("/tasks/{task_id}/complete")
async def task_complete(task_id: str, body: CompleteBody):
    row = kb.complete_task(
        task_id,
        summary=body.summary,
        metadata=body.metadata,
        result=body.result,
        actor=body.actor,
        origin_session_key=body.origin_session_key,
        origin_kind=body.origin_kind,
        internal_event=body.internal_event,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return row


@router.post("/tasks/{task_id}/block")
async def task_block(task_id: str, body: BlockBody):
    row = kb.block_task(
        task_id,
        body.reason,
        actor=body.actor,
        origin_session_key=body.origin_session_key,
        origin_kind=body.origin_kind,
        internal_event=body.internal_event,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return row


@router.post("/tasks/{task_id}/unblock")
async def task_unblock(task_id: str):
    row = kb.unblock_task(task_id)
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return row


@router.post(
    "/dispatch",
    response_model=DispatchResponse,
    response_model_exclude_none=True,
)
async def dispatch_nudge(max_tasks: int = 3, dry_run: bool = False):
    """Manual dispatcher nudge (claims + spawns are handled in gateway)."""
    from spark_cli import kanban_dispatch as kd  # circular safe

    if dry_run:
        return kb.preview_ready_for_dispatch(max_tasks=max_tasks)
    return await kd.run_dispatch_tick(max_tasks=max_tasks)


@router.get("/events")
async def kanban_events(request: Request, since: int = 0):
    """SSE stream of new task_events rows."""
    from fastapi.responses import StreamingResponse

    async def gen():
        last = since
        try:
            while True:
                if await request.is_disconnected():
                    break
                rows = kb.append_events_since(last, limit=100)
                if rows:
                    for r in rows:
                        last = max(last, int(r["id"]))
                        yield f"data: {json.dumps(dict(r), default=str)}\n\n"
                else:
                    yield "event: ping\ndata: {}\n\n"
                import asyncio
                await asyncio.sleep(0.8)
        except Exception:
            pass

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def register_kanban_routes(app) -> None:
    app.include_router(router)
