"""Server-side workflow execution engine for the Canvas tab.

A **workflow** is a directed graph of typed nodes. Each node receives a list of
*items* (the data envelope) on its inputs and emits a list of items on its output.
The engine walks the graph in topological order from its trigger node(s), passing
items along edges, and reports per-node state through an optional ``emit`` callback.

Node behaviour lives in **handlers** registered via :func:`register_node_handler`.
Tool/agent handlers are registered in ``workflow_nodes.py`` so this module stays
free of heavy agent/tool imports.

Data envelope (one "item")::

    {"json": {<any>}, "binary": {<key>: {"fileRef": ..., "mimeType": ..., "name": ...}}}

Node categories: ``trigger | action | control | agent | io | display``. ``display``
nodes (iframe/preview/media/note) are non-executable and simply pass their input
through, so the embed/moodboard half and the workflow half share one document.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

_log = logging.getLogger(__name__)

# ── Data envelope ───────────────────────────────────────────────────────────
Item = dict[str, Any]


def make_item(json_data: Any = None, binary: dict[str, Any] | None = None) -> Item:
    """Wrap a value in the standard item envelope."""
    return {"json": json_data if json_data is not None else {}, "binary": binary or {}}


# ── Document model ──────────────────────────────────────────────────────────
class WorkflowNode(BaseModel):
    id: str
    type: str
    # Free-form per-node configuration (form values, mappings, embed urls, …).
    params: dict[str, Any] = Field(default_factory=dict)
    position: dict[str, float] = Field(default_factory=lambda: {"x": 0.0, "y": 0.0})
    # React Flow display data (label, embed dims, etc.) — opaque to the engine.
    data: dict[str, Any] = Field(default_factory=dict)


class WorkflowEdge(BaseModel):
    id: str
    source: str
    target: str
    sourceHandle: str | None = None
    targetHandle: str | None = None


class WorkflowDoc(BaseModel):
    id: str
    name: str
    scope: str = "global"
    slug: str | None = None
    nodes: list[WorkflowNode] = Field(default_factory=list)
    edges: list[WorkflowEdge] = Field(default_factory=list)
    viewport: dict[str, Any] = Field(default_factory=lambda: {"x": 0, "y": 0, "zoom": 1})
    version: int = 2
    updatedAt: str | None = None


# ── Node-handler registry ───────────────────────────────────────────────────
@dataclass
class ExecContext:
    """Per-run context handed to every node handler."""

    doc: WorkflowDoc
    execution_id: str
    # node_id -> output items produced this run (for field-mapping resolution).
    outputs: dict[str, list[Item]] = field(default_factory=dict)
    emit: Callable[[str, dict[str, Any]], None] = lambda event, data: None
    # Project slug for project-scoped canvases (working dir for agent/tool nodes).
    slug: str | None = None
    cancelled: Callable[[], bool] = lambda: False
    max_iterations: int = 1000


# handler(node, input_items, ctx) -> output_items
NodeHandler = Callable[[WorkflowNode, list[Item], ExecContext], list[Item]]


@dataclass
class NodeTypeSpec:
    type: str
    category: str  # trigger | action | control | agent | io | display
    handler: NodeHandler


_NODE_HANDLERS: dict[str, NodeTypeSpec] = {}


def register_node_handler(node_type: str, category: str = "action") -> Callable[[NodeHandler], NodeHandler]:
    """Register a handler for ``node_type``. Use as a decorator."""

    def deco(fn: NodeHandler) -> NodeHandler:
        _NODE_HANDLERS[node_type] = NodeTypeSpec(type=node_type, category=category, handler=fn)
        return fn

    return deco


def get_node_spec(node_type: str) -> NodeTypeSpec | None:
    return _NODE_HANDLERS.get(node_type)


def registered_node_types() -> dict[str, NodeTypeSpec]:
    return dict(_NODE_HANDLERS)


# ── Field-mapping resolver ──────────────────────────────────────────────────
# A param value can be a literal, or a mapping reference:
#   {"__map": {"node": "<id>", "field": "json.path.to.value"}}
# resolved from that node's first output item.
def _get_path(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if part == "":
            continue
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return cur


def resolve_param(value: Any, ctx: ExecContext) -> Any:
    if isinstance(value, dict) and "__map" in value:
        ref = value["__map"] or {}
        node_id = ref.get("node")
        field_path = ref.get("field", "")
        items = ctx.outputs.get(node_id or "", [])
        if not items:
            return None
        first = items[0]
        # Default to reading from the item's json payload unless an explicit
        # "json."/"binary." prefix is given.
        if field_path.startswith(("json.", "binary.")) or field_path in ("json", "binary"):
            return _get_path(first, field_path)
        return _get_path(first.get("json", {}), field_path)
    if isinstance(value, dict):
        return {k: resolve_param(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_param(v, ctx) for v in value]
    return value


def resolve_params(node: WorkflowNode, ctx: ExecContext) -> dict[str, Any]:
    return {k: resolve_param(v, ctx) for k, v in (node.params or {}).items()}


# ── Execution ───────────────────────────────────────────────────────────────
class WorkflowError(Exception):
    pass


def _topological_order(doc: WorkflowDoc) -> list[str]:
    """Kahn's algorithm. Raises WorkflowError on a cycle (loop nodes handle their
    own iteration explicitly rather than via graph cycles)."""
    node_ids = [n.id for n in doc.nodes]
    indeg: dict[str, int] = {nid: 0 for nid in node_ids}
    adj: dict[str, list[str]] = defaultdict(list)
    for e in doc.edges:
        if e.source in indeg and e.target in indeg:
            adj[e.source].append(e.target)
            indeg[e.target] += 1
    q = deque([nid for nid in node_ids if indeg[nid] == 0])
    order: list[str] = []
    while q:
        nid = q.popleft()
        order.append(nid)
        for nxt in adj[nid]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                q.append(nxt)
    if len(order) != len(node_ids):
        raise WorkflowError("Workflow graph contains a cycle")
    return order


def _incoming_items(node_id: str, doc: WorkflowDoc, ctx: ExecContext) -> list[Item]:
    items: list[Item] = []
    for e in doc.edges:
        if e.target == node_id:
            items.extend(ctx.outputs.get(e.source, []))
    return items


@dataclass
class NodeResult:
    node_id: str
    status: str  # success | error | skipped
    items: list[Item]
    error: str | None = None
    duration_ms: int = 0


@dataclass
class ExecutionResult:
    execution_id: str
    status: str  # success | error
    nodes: list[NodeResult] = field(default_factory=list)
    error: str | None = None


def execute_workflow(
    doc: WorkflowDoc,
    *,
    execution_id: str,
    emit: Callable[[str, dict[str, Any]], None] | None = None,
    seed: list[Item] | None = None,
    start_node: str | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ExecutionResult:
    """Run a workflow to completion in topological order.

    ``start_node`` limits execution to a single node (run-one-node), seeded with
    ``seed`` items. Otherwise the whole graph runs from its roots.
    """
    ctx = ExecContext(
        doc=doc,
        execution_id=execution_id,
        emit=emit or (lambda event, data: None),
        slug=doc.slug,
        cancelled=cancelled or (lambda: False),
    )
    result = ExecutionResult(execution_id=execution_id, status="success")

    order = [start_node] if start_node else _topological_order(doc)
    nodes_by_id = {n.id: n for n in doc.nodes}

    for node_id in order:
        node = nodes_by_id.get(node_id)
        if node is None:
            continue
        if ctx.cancelled():
            result.status = "error"
            result.error = "cancelled"
            break

        spec = get_node_spec(node.type)
        inputs = seed if (start_node and seed is not None) else _incoming_items(node_id, doc, ctx)
        ctx.emit("node.started", {"nodeId": node_id, "type": node.type})
        started = time.monotonic()

        try:
            if spec is None:
                # Unknown/display-only node: pass input through unchanged.
                outputs = inputs
            else:
                outputs = spec.handler(node, inputs, ctx) or []
            ctx.outputs[node_id] = outputs
            dur = int((time.monotonic() - started) * 1000)
            nr = NodeResult(node_id=node_id, status="success", items=outputs, duration_ms=dur)
            result.nodes.append(nr)
            ctx.emit(
                "node.succeeded",
                {"nodeId": node_id, "items": outputs, "durationMs": dur, "count": len(outputs)},
            )
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:  # noqa: BLE001 — surface per-node, keep going semantics below
            dur = int((time.monotonic() - started) * 1000)
            err = f"{type(exc).__name__}: {exc}"
            ctx.outputs[node_id] = []
            result.nodes.append(NodeResult(node_id=node_id, status="error", items=[], error=err, duration_ms=dur))
            result.status = "error"
            result.error = err
            ctx.emit("node.failed", {"nodeId": node_id, "error": err, "durationMs": dur})
            _log.warning("Workflow %s node %s failed: %s", execution_id, node_id, err)
            break

    ctx.emit("execution.finished", {"status": result.status, "error": result.error})
    return result
