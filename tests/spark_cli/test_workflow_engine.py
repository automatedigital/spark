"""Tests for the workflow execution engine + built-in node handlers."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import spark_cli.workflow_nodes  # noqa: F401 — registers handlers
from spark_cli.workflow_engine import (
    WorkflowDoc,
    WorkflowEdge,
    WorkflowError,
    WorkflowNode,
    execute_workflow,
    make_item,
)


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


def test_switch_node_filters_matching_case():
    doc = _doc(
        nodes=[
            {"id": "a", "type": "trigger.manual", "params": {"payload": {"kind": "invoice"}}},
            {"id": "b", "type": "control.switch", "params": {"field": "kind", "case": "invoice"}},
        ],
        edges=[{"id": "e1", "source": "a", "target": "b"}],
    )
    res = execute_workflow(doc, execution_id="x9")
    b = next(n for n in res.nodes if n.node_id == "b")
    assert b.items[0]["json"]["kind"] == "invoice"


def test_loop_node_expands_items():
    doc = _doc(
        nodes=[
            {"id": "a", "type": "trigger.manual", "params": {"payload": {"seed": "x"}}},
            {"id": "b", "type": "control.loop", "params": {"count": 3, "batchSize": 2}},
        ],
        edges=[{"id": "e1", "source": "a", "target": "b"}],
    )
    res = execute_workflow(doc, execution_id="x10")
    b = next(n for n in res.nodes if n.node_id == "b")
    assert [it["json"]["iteration"] for it in b.items] == [1, 2, 3]
    assert b.items[2]["json"]["batchIndex"] == 1


def test_wait_node_can_passthrough_without_sleep():
    doc = _doc(
        nodes=[
            {"id": "a", "type": "trigger.manual", "params": {"payload": {"v": 1}}},
            {"id": "b", "type": "action.wait", "params": {"seconds": 0}},
        ],
        edges=[{"id": "e1", "source": "a", "target": "b"}],
    )
    res = execute_workflow(doc, execution_id="x11")
    b = next(n for n in res.nodes if n.node_id == "b")
    assert b.items[0]["json"]["v"] == 1


def test_code_node_uses_sandbox(monkeypatch):
    import tools.code_execution_tool as code_tool

    def fake_execute_code(code, task_id=None, enabled_tools=None):
        assert "items = json.loads" in code
        payload = [{"json": {"answer": 42}, "binary": {}}]
        return json.dumps({"status": "success", "output": "__SPARK_WORKFLOW_OUTPUT__=" + json.dumps(payload)})

    monkeypatch.setattr(code_tool, "execute_code", fake_execute_code)
    doc = _doc(nodes=[{"id": "a", "type": "action.code", "params": {"code": "output = {'answer': 42}"}}])
    res = execute_workflow(doc, execution_id="x12")
    assert res.nodes[0].items[0]["json"]["answer"] == 42


def test_http_node_fetches_json():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = json.dumps({"ok": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/data"
        doc = _doc(nodes=[{"id": "a", "type": "action.http", "params": {"url": url}}])
        res = execute_workflow(doc, execution_id="x13")
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert res.status == "success"
    assert res.nodes[0].items[0]["json"]["body"] == {"ok": True}
