"""FastAPI routes for the admin API.

Extracted from web_server.py, which declared these directly on the app.
"""

from __future__ import annotations

import json
import logging
import queue as thread_queue
import threading

from fastapi import APIRouter, HTTPException, Request

from spark_cli.admin_runs import (
    ADMIN_ACTIONS,
    AdminActionStart,
    _admin_run_queues,
    _admin_runs,
    _new_admin_run,
    _run_admin_action,
)
from spark_cli.web_runtime import _run_blocking

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/actions")
async def admin_actions():
    """Return bounded admin actions available to the dashboard."""
    return {"ok": True, "actions": [a.to_metadata() for a in ADMIN_ACTIONS.values()]}


@router.post("/actions/{action_id}")
async def start_admin_action(action_id: str, payload: AdminActionStart):
    action = ADMIN_ACTIONS.get(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail=f"Unknown admin action: {action_id}")
    meta = action.to_metadata()
    if not meta["available"]:
        raise HTTPException(status_code=400, detail=meta["unavailable_reason"] or "Action unavailable")
    if action.requires_confirmation and not payload.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")
    run_id, _queue = _new_admin_run(action_id, payload.args or {})
    threading.Thread(target=_run_admin_action, args=(run_id, action, payload.args or {}), daemon=True).start()
    return {"run_id": run_id, "status": "queued"}


@router.get("/actions/runs/{run_id}")
async def get_admin_action_run(run_id: str):
    run = _admin_runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/actions/runs/{run_id}/stream")
async def stream_admin_action_run(request: Request, run_id: str):
    from fastapi.responses import StreamingResponse as _StreamingResponse

    run = _admin_runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    queue = _admin_run_queues.get(run_id)
    if queue is None:
        queue = thread_queue.Queue(maxsize=512)
        _admin_run_queues[run_id] = queue

    async def event_generator():
        yield f"data: {json.dumps({'type': 'state', 'status': run.get('status')})}\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await _run_blocking(queue.get, True, 20)
                except thread_queue.Empty:
                    yield "event: ping\ndata: {}\n\n"
                    if run.get("status") in ("done", "failed"):
                        break
                    continue
                yield f"data: {json.dumps(event, default=str)}\n\n"
                if event.get("type") == "done":
                    break
        finally:
            if run.get("status") in ("done", "failed"):
                _admin_run_queues.pop(run_id, None)

    return _StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def register_admin_routes(app) -> None:
    app.include_router(router)
