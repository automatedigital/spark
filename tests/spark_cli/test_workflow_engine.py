"""Tests for the workflow execution engine + built-in node handlers."""

from __future__ import annotations

import pytest

from spark_cli.workflow_engine import (
    WorkflowDoc,
    WorkflowEdge,
    WorkflowNode,
    WorkflowError,
    execute_workflow,
    make_item,
)
import spark_cli.workflow_nodes  # noqa: F401 — registers handlers


def _doc(nodes, edges=None, **kw):
    return WorkflowDoc(
        id="t",
        name="t",
        nodes=[WorkflowNode(**n) for n in nodes],
        edges=[WorkflowEdge(**e) for e in (edges or [])],
        **kw,
    )


def test_manual_trigger_into_set_fields():
    doc = _doc(
        nodes=[
            {"id": "a", "type": "trigger.manual", "params": {}},
            {"id": "b", "type": "data.set", "params": {"fields": {"hello": "world"}}},
        ],
        edges=[{"id": "e1", "source": "a", "target": "b"}],
    )
    res = execute_workflow(doc, execution_id="x1")
    assert res.status == "success"
    b = next(n for n in res.nodes if n.node_id == "b")
    assert b.items[0]["json"]["hello"] == "world"


def test_field_mapping_between_nodes():
    doc = _doc(
        nodes=[
            {"id": "a", "type": "data.set", "params": {"fields": {"name": "ada"}}},
            {
                "id": "b",
                "type": "data.set",
                "params": {"fields": {"greeting": {"__map": {"node": "a", "field": "name"}}}},
            },
        ],
        edges=[{"id": "e1", "source": "a", "target": "b"}],
    )
    res = execute_workflow(doc, execution_id="x2")
    b = next(n for n in res.nodes if n.node_id == "b")
    assert b.items[0]["json"]["greeting"] == "ada"


def test_if_node_filters():
    doc = _doc(
        nodes=[
            {"id": "a", "type": "trigger.manual", "params": {"payload": {"ok": True}}},
            {"id": "b", "type": "control.if", "params": {"field": "ok", "equals": True}},
        ],
        edges=[{"id": "e1", "source": "a", "target": "b"}],
    )
    res = execute_workflow(doc, execution_id="x3")
    b = next(n for n in res.nodes if n.node_id == "b")
    assert len(b.items) == 1


def test_cycle_detected():
    doc = _doc(
        nodes=[
            {"id": "a", "type": "data.set"},
            {"id": "b", "type": "data.set"},
        ],
        edges=[
            {"id": "e1", "source": "a", "target": "b"},
            {"id": "e2", "source": "b", "target": "a"},
        ],
    )
    with pytest.raises(WorkflowError):
        execute_workflow(doc, execution_id="x4")


def test_tool_node_dispatches(monkeypatch):
    import tools.registry as reg

    monkeypatch.setattr(reg.registry, "dispatch", lambda name, args: '{"echoed": ' + str(args.get("n", 0)) + "}")
    doc = _doc(
        nodes=[{"id": "a", "type": "tool", "params": {"tool": "fake", "args": {"n": 42}}}],
    )
    res = execute_workflow(doc, execution_id="x5")
    a = next(n for n in res.nodes if n.node_id == "a")
    assert a.status == "success"
    assert a.items[0]["json"]["echoed"] == 42


def test_run_single_node_with_seed():
    doc = _doc(nodes=[{"id": "b", "type": "data.set", "params": {"fields": {"x": 1}}}])
    res = execute_workflow(doc, execution_id="x6", start_node="b", seed=[make_item({"keep": "me"})])
    b = res.nodes[0]
    assert b.items[0]["json"] == {"keep": "me", "x": 1}


def test_unknown_node_passes_through():
    doc = _doc(
        nodes=[
            {"id": "a", "type": "trigger.manual", "params": {"payload": {"v": 5}}},
            {"id": "b", "type": "display.iframe", "params": {"url": "https://example.com"}},
        ],
        edges=[{"id": "e1", "source": "a", "target": "b"}],
    )
    res = execute_workflow(doc, execution_id="x7")
    b = next(n for n in res.nodes if n.node_id == "b")
    assert b.items[0]["json"]["v"] == 5


def test_node_failure_stops_and_reports():
    doc = _doc(nodes=[{"id": "a", "type": "tool", "params": {"tool": ""}}])
    res = execute_workflow(doc, execution_id="x8")
    assert res.status == "error"
    assert res.nodes[0].status == "error"
