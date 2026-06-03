"""Tests for the Canvas REST API (src/spark_cli/canvas_routes.py)."""

from __future__ import annotations

import pytest

from spark_cli.config import get_spark_home


@pytest.fixture
def client():
    fastapi = pytest.importorskip("fastapi")
    from starlette.testclient import TestClient

    from spark_cli.canvas_routes import register_canvas_routes

    app = fastapi.FastAPI()
    register_canvas_routes(app)
    return TestClient(app)


def _doc(canvas_id: str, name: str | None = None) -> dict:
    return {
        "id": canvas_id,
        "name": name or canvas_id,
        "nodes": [{"id": "n1", "type": "note", "position": {"x": 0, "y": 0}, "data": {}}],
        "edges": [],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }


def test_global_canvas_round_trip(client):
    # Create
    resp = client.put("/api/canvases/global/board-one", json=_doc("board-one", "Board One"))
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True

    # File written to ~/.spark/canvases/
    saved = get_spark_home() / "canvases" / "board-one.canvas.json"
    assert saved.exists()

    # Read back
    got = client.get("/api/canvases/global/board-one")
    assert got.status_code == 200
    body = got.json()
    assert body["name"] == "Board One"
    assert body["scope"] == "global"
    assert body["nodes"][0]["id"] == "n1"
    assert body["updatedAt"]

    # List includes it
    listed = client.get("/api/canvases").json()["canvases"]
    assert any(c["id"] == "board-one" and c["scope"] == "global" for c in listed)

    # Delete
    assert client.delete("/api/canvases/global/board-one").status_code == 200
    assert not saved.exists()
    assert client.get("/api/canvases/global/board-one").status_code == 404


def test_project_canvas_written_into_project_dir(client):
    # Create a project folder under the workspace root
    project = get_spark_home() / "workspace" / "myproj"
    project.mkdir(parents=True, exist_ok=True)

    resp = client.put("/api/canvases/project/myproj/flow", json=_doc("flow", "Flow"))
    assert resp.status_code == 200, resp.text

    # Stored as a visible file in the project folder
    saved = project / "flow.canvas.json"
    assert saved.exists()

    listed = client.get("/api/canvases").json()["canvases"]
    assert any(c["id"] == "flow" and c["scope"] == "project" and c["slug"] == "myproj" for c in listed)

    got = client.get("/api/canvases/project/myproj/flow").json()
    assert got["scope"] == "project"
    assert got["slug"] == "myproj"


def test_invalid_canvas_id_rejected(client):
    resp = client.put("/api/canvases/global/bad%2Fid", json=_doc("bad/id"))
    # Path traversal / separators must not be accepted as a valid id
    assert resp.status_code in (400, 404)


def test_missing_canvas_is_404(client):
    assert client.get("/api/canvases/global/nope").status_code == 404
    assert client.delete("/api/canvases/global/nope").status_code == 404


def test_project_scope_requires_existing_project(client):
    resp = client.put("/api/canvases/project/ghost/flow", json=_doc("flow"))
    assert resp.status_code == 404
