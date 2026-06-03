"""FastAPI routes for workflow execution (the Canvas tab's n8n-style engine).

- ``GET  /api/workflows/node-types``   — catalog of node types (built-ins + every tool)
- ``POST /api/workflows/run``          — execute a workflow doc, return per-node results
- ``POST /api/workflows/run-node``     — execute a single node with seed items
- ``GET  /api/workflows/executions``   — execution history
- ``GET  /api/workflows/executions/{id}`` — one execution with per-node items
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from spark_cli import workflow_store
from spark_cli.workflow_engine import WorkflowDoc, execute_workflow, make_item
from spark_cli.workflow_nodes import node_type_catalog

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workflows", tags=["workflows"])

# Guardrails
_MAX_NODES = 200


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


@router.post("/run")
def run_workflow(body: RunBody) -> dict[str, Any]:
    doc = body.doc
    if len(doc.nodes) > _MAX_NODES:
        raise HTTPException(status_code=400, detail=f"Too many nodes (>{_MAX_NODES})")
    execution_id = "exec_" + uuid.uuid4().hex[:12]
    started = time.time()
    try:
        result = execute_workflow(doc, execution_id=execution_id)
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
            trigger=body.trigger,
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


def register_workflow_routes(app) -> None:
    app.include_router(router)
