"""Tests for the workflow execution engine + built-in node handlers."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import spark_cli.workflow_nodes  # noqa: F401 — registers handlers
from spark_cli.config import get_spark_home
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
    assert b.items[0]["json"]["__branch"] == "true"


def test_if_node_routes_by_source_handle():
    doc = _doc(
        nodes=[
            {"id": "a", "type": "trigger.manual", "params": {"payload": {"ok": False}}},
            {"id": "b", "type": "control.if", "params": {"field": "ok", "equals": True}},
            {"id": "c", "type": "data.set", "params": {"fields": {"routed": "false"}}},
        ],
        edges=[
            {"id": "e1", "source": "a", "target": "b"},
            {"id": "e2", "source": "b", "target": "c", "sourceHandle": "false"},
        ],
    )
    res = execute_workflow(doc, execution_id="x3b")
    c = next(n for n in res.nodes if n.node_id == "c")
    assert c.items[0]["json"]["routed"] == "false"


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


def test_agent_node_honors_iteration_toolset_and_memory_params(monkeypatch):
    import core.run_agent as run_agent
    import spark_cli.workflow_nodes as workflow_nodes

    captured = {}

    class FakeAgent:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def chat(self, prompt):
            captured["prompt"] = prompt
            return "done"

    monkeypatch.setattr(workflow_nodes, "_resolve_runtime", lambda prompt, model: {"model": model or "m", "runtime": {}})
    monkeypatch.setattr(run_agent, "AIAgent", FakeAgent)
    doc = _doc(
        nodes=[
            {
                "id": "a",
                "type": "agent",
                "params": {
                    "prompt": "hello",
                    "model": "test-model",
                    "maxIterations": 3,
                    "toolsets": "web,terminal",
                    "skipMemory": True,
                },
            }
        ]
    )
    res = execute_workflow(doc, execution_id="x14")
    assert res.nodes[0].items[0]["json"]["reply"] == "done"
    assert captured["max_iterations"] == 3
    assert captured["enabled_toolsets"] == ["web", "terminal"]
    assert captured["skip_memory"] is True


def test_context_memory_node_shares_state():
    doc = _doc(
        nodes=[
            {"id": "a", "type": "memory.context", "params": {"key": "topic", "value": "canvas"}},
            {"id": "b", "type": "memory.context", "params": {"key": "topic", "mode": "read"}},
        ],
        edges=[{"id": "e1", "source": "a", "target": "b"}],
    )
    res = execute_workflow(doc, execution_id="x15")
    b = next(n for n in res.nodes if n.node_id == "b")
    assert b.items[0]["json"]["value"] == "canvas"


def test_subworkflow_node_runs_saved_canvas(monkeypatch):
    import spark_cli.canvas_routes as canvas_routes

    child = {
        "id": "child",
        "name": "Child",
        "scope": "global",
        "slug": None,
        "nodes": [{"id": "c", "type": "data.set", "params": {"fields": {"child": True}}}],
        "edges": [],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "version": 2,
    }
    monkeypatch.setattr(canvas_routes, "_read_canvas", lambda scope, slug, canvas_id: child)
    doc = _doc(
        nodes=[
            {"id": "a", "type": "trigger.manual", "params": {"payload": {"parent": True}}},
            {"id": "b", "type": "workflow.subworkflow", "params": {"canvasId": "child"}},
        ],
        edges=[{"id": "e1", "source": "a", "target": "b"}],
    )
    res = execute_workflow(doc, execution_id="x16")
    b = next(n for n in res.nodes if n.node_id == "b")
    assert b.items[0]["json"] == {"parent": True, "child": True}


def test_file_source_and_write_file_nodes():
    files_dir = get_spark_home() / "workspace" / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    (files_dir / "input.txt").write_text("hello", encoding="utf-8")
    doc = _doc(
        nodes=[
            {"id": "a", "type": "io.file_source", "params": {"source": "files", "path": "input.txt"}},
            {
                "id": "b",
                "type": "io.write_file",
                "params": {"source": "files", "path": "output.txt", "content": {"__map": {"node": "a", "field": "content"}}},
            },
        ],
        edges=[{"id": "e1", "source": "a", "target": "b"}],
    )
    res = execute_workflow(doc, execution_id="x17")
    a = next(n for n in res.nodes if n.node_id == "a")
    assert a.items[0]["json"]["content"] == "hello"
    assert a.items[0]["binary"]["file"]["fileRef"] == "workspace:files/input.txt"
    assert (files_dir / "output.txt").read_text(encoding="utf-8") == "hello"


def test_read_and_write_table_nodes():
    files_dir = get_spark_home() / "workspace" / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    (files_dir / "input.csv").write_text("name,score\nAda,10\nLin,9\n", encoding="utf-8")
    doc = _doc(
        nodes=[
            {"id": "a", "type": "io.read_table", "params": {"source": "files", "path": "input.csv"}},
            {"id": "b", "type": "io.write_table", "params": {"source": "files", "path": "output.json"}},
        ],
        edges=[{"id": "e1", "source": "a", "target": "b"}],
    )
    res = execute_workflow(doc, execution_id="x18")
    a = next(n for n in res.nodes if n.node_id == "a")
    assert a.items[0]["json"]["row"] == {"name": "Ada", "score": "10"}
    out = json.loads((files_dir / "output.json").read_text(encoding="utf-8"))
    assert len(out) == 2


def test_web_preview_node_fetches_metadata():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = b"""
            <html><head>
              <title>Fallback</title>
              <meta property="og:title" content="Preview Title">
              <meta name="description" content="Preview description">
              <meta property="og:image" content="/card.png">
              <link rel="icon" href="/favicon.ico">
            </head><body><main>Hello preview text</main></body></html>
            """
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/"
        doc = _doc(nodes=[{"id": "a", "type": "display.preview", "params": {"url": url}}])
        res = execute_workflow(doc, execution_id="x19")
    finally:
        server.shutdown()
        thread.join(timeout=2)

    meta = res.nodes[0].items[0]["json"]
    assert meta["title"] == "Preview Title"
    assert meta["description"] == "Preview description"
    assert meta["image"].endswith("/card.png")
    assert "Hello preview text" in meta["text"]


def test_render_node_exposes_input_for_display():
    doc = _doc(
        nodes=[
            {"id": "a", "type": "trigger.manual", "params": {"payload": {"message": "hi"}}},
            {"id": "b", "type": "display.render", "params": {"format": "json"}},
        ],
        edges=[{"id": "e1", "source": "a", "target": "b"}],
    )
    res = execute_workflow(doc, execution_id="x20")
    assert next(n for n in res.nodes if n.node_id == "b").items[0]["json"]["content"] == {"message": "hi"}
