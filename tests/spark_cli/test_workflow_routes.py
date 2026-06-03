"""Tests for the workflow execution REST API."""

from __future__ import annotations

import pytest


@pytest.fixture
def client():
    fastapi = pytest.importorskip("fastapi")
    from starlette.testclient import TestClient

    from spark_cli.workflow_routes import register_workflow_routes

    app = fastapi.FastAPI()
    register_workflow_routes(app)
    return TestClient(app)


def _simple_doc():
    return {
        "id": "wf1",
        "name": "WF1",
        "scope": "global",
        "slug": None,
        "nodes": [
            {"id": "a", "type": "trigger.manual", "params": {"payload": {"n": 1}}},
            {"id": "b", "type": "data.set", "params": {"fields": {"doubled": 2}}},
        ],
        "edges": [{"id": "e1", "source": "a", "target": "b"}],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "version": 2,
    }


def test_node_types_includes_builtins(client):
    res = client.get("/api/workflows/node-types")
    assert res.status_code == 200
    types = {t["type"] for t in res.json()["nodeTypes"]}
    assert "trigger.manual" in types
    assert "agent" in types
    assert "display.iframe" in types


def test_run_workflow_and_history(client):
    res = client.post("/api/workflows/run", json={"doc": _simple_doc(), "trigger": "manual"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "success"
    exec_id = body["executionId"]
    b = next(n for n in body["nodes"] if n["nodeId"] == "b")
    assert b["items"][0]["json"]["doubled"] == 2

    # History records it
    hist = client.get("/api/workflows/executions?canvas=wf1").json()["executions"]
    assert any(e["id"] == exec_id for e in hist)

    detail = client.get(f"/api/workflows/executions/{exec_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "success"


def test_run_single_node(client):
    res = client.post(
        "/api/workflows/run-node",
        json={"doc": _simple_doc(), "nodeId": "b", "seed": [{"json": {"keep": 1}}]},
    )
    assert res.status_code == 200, res.text
    node = res.json()["nodes"][0]
    assert node["items"][0]["json"] == {"keep": 1, "doubled": 2}


def test_run_node_missing_404(client):
    res = client.post("/api/workflows/run-node", json={"doc": _simple_doc(), "nodeId": "zzz"})
    assert res.status_code == 404


def test_missing_execution_404(client):
    assert client.get("/api/workflows/executions/nope").status_code == 404
