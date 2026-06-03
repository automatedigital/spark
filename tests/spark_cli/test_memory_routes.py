"""Memory REST routes for the Memory page (browse/add/replace/delete)."""

from __future__ import annotations

import pytest


@pytest.fixture
def client():
    fastapi = pytest.importorskip("fastapi")
    from starlette.testclient import TestClient

    from spark_cli.memory_routes import register_memory_routes

    app = fastapi.FastAPI()
    register_memory_routes(app)
    return TestClient(app)


def test_list_empty(client):
    body = client.get("/api/memory").json()
    assert "memory" in body["targets"] and "user" in body["targets"]
    assert body["targets"]["memory"]["entry_count"] == 0


def test_add_list_delete_roundtrip(client):
    add = client.post("/api/memory/memory/entry", json={"content": "Python 3.12 project"})
    assert add.status_code == 200
    assert "Python 3.12 project" in add.json()["entries"]

    listed = client.get("/api/memory").json()["targets"]["memory"]["entries"]
    assert "Python 3.12 project" in listed

    rm = client.request("DELETE", "/api/memory/memory/entry", json={"old_text": "Python 3.12 project"})
    assert rm.status_code == 200
    assert "Python 3.12 project" not in rm.json()["entries"]


def test_replace_entry(client):
    client.post("/api/memory/user/entry", json={"content": "Name: Bob"})
    rep = client.post("/api/memory/user/replace", json={"old_text": "Name: Bob", "new_content": "Name: Bobby"})
    assert rep.status_code == 200
    assert "Name: Bobby" in rep.json()["entries"]


def test_invalid_target_rejected(client):
    assert client.post("/api/memory/bogus/entry", json={"content": "x"}).status_code == 400


def test_delete_missing_entry_404(client):
    r = client.request("DELETE", "/api/memory/memory/entry", json={"old_text": "nope"})
    assert r.status_code == 404
