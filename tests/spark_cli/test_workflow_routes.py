"""Tests for the workflow execution REST API."""

from __future__ import annotations

import time

import pytest


@pytest.fixture
def client():
    fastapi = pytest.importorskip("fastapi")
    from spark_cli.workflow_routes import register_workflow_routes
    from starlette.testclient import TestClient

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


def test_register_workflow_triggers(client):
    doc = _simple_doc()
    doc["nodes"][0] = {"id": "a", "type": "trigger.webhook", "params": {"secret": "hook-secret"}}
    res = client.post("/api/workflows/triggers/register", json={"doc": doc})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["triggers"][0]["kind"] == "webhook"
    assert body["triggers"][0]["secret"] == "hook-secret"

    listed = client.get("/api/workflows/triggers?canvas=wf1").json()["triggers"]
    assert listed[0]["kind"] == "webhook"


def test_webhook_trigger_executes_registered_workflow(client):
    doc = _simple_doc()
    doc["nodes"] = [
        {"id": "a", "type": "trigger.webhook", "params": {"secret": "hook-secret"}},
        {"id": "b", "type": "data.set", "params": {"fields": {"fromWebhook": True}}},
    ]
    client.post("/api/workflows/triggers/register", json={"doc": doc})

    res = client.post("/api/workflows/webhook/hook-secret", json={"event": "push"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "success"
    b = next(n for n in body["nodes"] if n["nodeId"] == "b")
    assert b["items"][0]["json"]["event"] == "push"
    assert b["items"][0]["json"]["fromWebhook"] is True


def test_schedule_tick_runs_due_trigger(client, monkeypatch):
    from spark_cli import workflow_routes, workflow_store

    now = time.time()
    doc = _simple_doc()
    doc["nodes"][0] = {"id": "a", "type": "trigger.schedule", "params": {"schedule": "1h"}}
    res = client.post("/api/workflows/triggers/register", json={"doc": doc})
    assert res.status_code == 200, res.text
    trigger_id = res.json()["triggers"][0]["id"]
    workflow_store.update_trigger_state(trigger_id, next_run_at=now - 1)
    monkeypatch.setattr(workflow_routes, "_next_run_timestamp", lambda schedule, after=None: now + 3600)

    ran = workflow_routes.tick_registered_triggers()
    assert len(ran) == 1
    assert ran[0]["status"] == "success"
    updated = workflow_store.get_trigger(trigger_id)
    assert updated["next_run_at"] == now + 3600


def test_filewatch_tick_runs_when_mtime_changes(client, tmp_path):
    from spark_cli import workflow_routes, workflow_store

    watched = tmp_path / "watched.txt"
    watched.write_text("one", encoding="utf-8")
    doc = _simple_doc()
    doc["nodes"][0] = {"id": "a", "type": "trigger.filewatch", "params": {"path": str(watched)}}
    res = client.post("/api/workflows/triggers/register", json={"doc": doc})
    assert res.status_code == 200, res.text
    trigger_id = res.json()["triggers"][0]["id"]
    workflow_store.update_trigger_state(trigger_id, last_file_mtime=0)

    ran = workflow_routes.tick_registered_triggers()
    assert len(ran) == 1
    assert ran[0]["status"] == "success"
    updated = workflow_store.get_trigger(trigger_id)
    assert updated["last_file_mtime"] == watched.stat().st_mtime
