"""FastAPI routes for workflow execution (the Canvas tab's n8n-style engine).

- ``GET  /api/workflows/node-types``   — catalog of node types (built-ins + every tool)
- ``POST /api/workflows/run``          — execute a workflow doc, return per-node results
- ``POST /api/workflows/run-node``     — execute a single node with seed items
- ``GET  /api/workflows/executions``   — execution history
- ``GET  /api/workflows/executions/{id}`` — one execution with per-node items
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from spark_cli import workflow_store
from spark_cli.workflow_engine import WorkflowDoc, execute_workflow, make_item
from spark_cli.workflow_nodes import node_type_catalog

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workflows", tags=["workflows"])

# Guardrails
_MAX_NODES = 200
_TRIGGER_TICK_SECONDS = 30
_ticker_started = False
_ticker_stop = threading.Event()
_ticker_lock = threading.Lock()


@router.get("/node-types")
def get_node_types() -> dict[str, Any]:
    return {"nodeTypes": node_type_catalog()}


class RunBody(BaseModel):
    doc: WorkflowDoc
    trigger: str = "manual"


def _node_results_payload(result) -> list[dict[str, Any]]:
    return [
        {
            "nodeId": n.node_id,
            "status": n.status,
            "items": n.items,
            "error": n.error,
            "durationMs": n.duration_ms,
        }
        for n in result.nodes
    ]


def _run_and_record(doc: WorkflowDoc, *, trigger: str, seed: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if len(doc.nodes) > _MAX_NODES:
        raise HTTPException(status_code=400, detail=f"Too many nodes (>{_MAX_NODES})")
    execution_id = "exec_" + uuid.uuid4().hex[:12]
    started = time.time()
    try:
        result = execute_workflow(
            doc,
            execution_id=execution_id,
            seed=[make_item(i.get("json"), i.get("binary")) for i in seed] if seed else None,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc))

    nodes_payload = _node_results_payload(result)
    try:
        workflow_store.record_execution(
            execution_id=execution_id,
            canvas_id=doc.id,
            scope=doc.scope,
            slug=doc.slug,
            status=result.status,
            error=result.error,
            started_at=started,
            trigger=trigger,
            nodes=nodes_payload,
        )
    except Exception:  # noqa: BLE001 — history is best-effort
        _log.debug("Failed to record execution %s", execution_id, exc_info=True)

    return {
        "executionId": execution_id,
        "status": result.status,
        "error": result.error,
        "nodes": nodes_payload,
    }


@router.post("/run")
def run_workflow(body: RunBody) -> dict[str, Any]:
    return _run_and_record(body.doc, trigger=body.trigger)


class RunNodeBody(BaseModel):
    doc: WorkflowDoc
    nodeId: str
    seed: list[dict[str, Any]] | None = None


@router.post("/run-node")
def run_single_node(body: RunNodeBody) -> dict[str, Any]:
    doc = body.doc
    if not any(n.id == body.nodeId for n in doc.nodes):
        raise HTTPException(status_code=404, detail=f"Node not found: {body.nodeId}")
    execution_id = "exec_" + uuid.uuid4().hex[:12]
    seed = (
        [make_item(i.get("json"), i.get("binary")) for i in body.seed]
        if body.seed is not None
        else [make_item({})]
    )
    try:
        result = execute_workflow(doc, execution_id=execution_id, start_node=body.nodeId, seed=seed)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "executionId": execution_id,
        "status": result.status,
        "error": result.error,
        "nodes": _node_results_payload(result),
    }


@router.get("/executions")
def list_executions(
    canvas: str | None = Query(default=None),
    scope: str | None = Query(default=None),
    slug: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
) -> dict[str, Any]:
    return {"executions": workflow_store.list_executions(canvas_id=canvas, scope=scope, slug=slug, limit=limit)}


@router.get("/executions/{execution_id}")
def get_execution(execution_id: str) -> dict[str, Any]:
    ex = workflow_store.get_execution(execution_id)
    if not ex:
        raise HTTPException(status_code=404, detail="Execution not found")
    return ex


class RegisterTriggersBody(BaseModel):
    doc: WorkflowDoc


@router.post("/triggers/register")
def register_triggers(body: RegisterTriggersBody) -> dict[str, Any]:
    """Persist non-manual trigger nodes for server-side execution."""
    triggers = _extract_triggers(body.doc)
    workflow_store.replace_triggers(
        canvas_id=body.doc.id,
        scope=body.doc.scope,
        slug=body.doc.slug,
        triggers=triggers,
    )
    return {"ok": True, "triggers": _public_triggers(triggers)}


@router.get("/triggers")
def list_triggers(canvas: str | None = Query(default=None), kind: str | None = Query(default=None)) -> dict[str, Any]:
    return {"triggers": workflow_store.list_triggers(canvas_id=canvas, kind=kind)}


@router.post("/webhook/{secret}")
async def fire_webhook(secret: str, request: Request) -> dict[str, Any]:
    trigger = workflow_store.find_webhook(secret)
    if not trigger:
        raise HTTPException(status_code=404, detail="Webhook trigger not found")
    payload = await _request_payload(request)
    doc = _doc_with_trigger_payload(trigger, payload)
    result = _run_and_record(doc, trigger=f"webhook:{trigger['node_id']}", seed=[{"json": payload}])
    workflow_store.update_trigger_state(trigger["id"], last_run_at=time.time())
    return {"ok": True, "triggerId": trigger["id"], **result}


def _extract_triggers(doc: WorkflowDoc) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    doc_payload = doc.model_dump()
    for node in doc.nodes:
        params = node.params or {}
        if node.type == "trigger.schedule":
            schedule = str(params.get("schedule") or "").strip()
            if not schedule:
                continue
            out.append(
                {
                    "id": _trigger_id(doc, node.id, "schedule"),
                    "canvas_id": doc.id,
                    "node_id": node.id,
                    "kind": "schedule",
                    "schedule": schedule,
                    "next_run_at": _next_run_timestamp(schedule),
                    "doc": doc_payload,
                }
            )
        elif node.type == "trigger.webhook":
            secret = str(params.get("secret") or "").strip() or uuid.uuid4().hex
            out.append(
                {
                    "id": _trigger_id(doc, node.id, "webhook"),
                    "canvas_id": doc.id,
                    "node_id": node.id,
                    "kind": "webhook",
                    "secret": secret,
                    "doc": _doc_with_node_param(doc_payload, node.id, {"secret": secret}),
                }
            )
        elif node.type == "trigger.filewatch":
            path = str(params.get("path") or "").strip()
            if not path:
                continue
            out.append(
                {
                    "id": _trigger_id(doc, node.id, "filewatch"),
                    "canvas_id": doc.id,
                    "node_id": node.id,
                    "kind": "filewatch",
                    "path": path,
                    "last_file_mtime": _file_mtime(path),
                    "doc": doc_payload,
                }
            )
    return out


def _public_triggers(triggers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in t.items() if k != "doc"} for t in triggers]


def _trigger_id(doc: WorkflowDoc, node_id: str, kind: str) -> str:
    slug = doc.slug or "global"
    return f"{doc.scope}:{slug}:{doc.id}:{node_id}:{kind}"


def _next_run_timestamp(schedule: str, *, after: float | None = None) -> float | None:
    from cron.jobs import compute_next_run, parse_schedule

    try:
        parsed = parse_schedule(schedule)
        last = datetime.fromtimestamp(after).isoformat() if after else None
        next_run = compute_next_run(parsed, last_run_at=last)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Invalid schedule {schedule!r}: {exc}") from exc
    return datetime.fromisoformat(next_run).timestamp() if next_run else None


async def _request_payload(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
        return data if isinstance(data, dict) else {"value": data}
    except Exception:  # noqa: BLE001
        body = await request.body()
        return {"body": body.decode("utf-8", errors="replace")}


def _doc_with_trigger_payload(trigger: dict[str, Any], payload: dict[str, Any]) -> WorkflowDoc:
    doc_payload = _doc_with_node_param(trigger["doc"], trigger["node_id"], {"payload": payload})
    return WorkflowDoc(**doc_payload)


def _doc_with_node_param(doc_payload: dict[str, Any], node_id: str, params: dict[str, Any]) -> dict[str, Any]:
    cloned = {**doc_payload, "nodes": [dict(n) for n in doc_payload.get("nodes", [])]}
    for node in cloned["nodes"]:
        if node.get("id") == node_id:
            node["params"] = {**(node.get("params") or {}), **params}
            break
    return cloned


def tick_registered_triggers() -> list[dict[str, Any]]:
    """Run due schedule/file-watch triggers once. Used by the web-server ticker."""
    ran: list[dict[str, Any]] = []
    now = time.time()
    for trigger in workflow_store.due_schedules(now):
        doc = WorkflowDoc(**trigger["doc"])
        result = _run_and_record(doc, trigger=f"schedule:{trigger['node_id']}")
        workflow_store.update_trigger_state(
            trigger["id"],
            last_run_at=now,
            next_run_at=_next_run_timestamp(trigger["schedule"], after=now),
        )
        ran.append({"triggerId": trigger["id"], **result})

    for trigger in workflow_store.enabled_file_triggers():
        mtime = _file_mtime(trigger["path"])
        if mtime is None or mtime == trigger.get("last_file_mtime"):
            continue
        payload = {"path": trigger["path"], "event": "change", "mtime": mtime}
        doc = _doc_with_trigger_payload(trigger, payload)
        result = _run_and_record(doc, trigger=f"filewatch:{trigger['node_id']}", seed=[{"json": payload}])
        workflow_store.update_trigger_state(trigger["id"], last_run_at=now, last_file_mtime=mtime)
        ran.append({"triggerId": trigger["id"], **result})
    return ran


def _file_mtime(path: str) -> float | None:
    try:
        return Path(os.path.expanduser(path)).stat().st_mtime
    except OSError:
        return None


def start_trigger_ticker() -> None:
    global _ticker_started
    with _ticker_lock:
        if _ticker_started:
            return
        _ticker_stop.clear()
        thread = threading.Thread(target=_trigger_ticker_loop, name="workflow-trigger-ticker", daemon=True)
        thread.start()
        _ticker_started = True


def stop_trigger_ticker() -> None:
    global _ticker_started
    _ticker_stop.set()
    _ticker_started = False


def _trigger_ticker_loop() -> None:
    while not _ticker_stop.wait(_TRIGGER_TICK_SECONDS):
        try:
            tick_registered_triggers()
        except Exception:  # noqa: BLE001
            _log.debug("Workflow trigger tick failed", exc_info=True)


def register_workflow_routes(app) -> None:
    app.include_router(router)
    if hasattr(app, "add_event_handler"):
        app.add_event_handler("startup", start_trigger_ticker)
        app.add_event_handler("shutdown", stop_trigger_ticker)
