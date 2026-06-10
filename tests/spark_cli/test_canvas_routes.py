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


def _doc(canvas_id: str, name: str | None = None, scope: str = "global", slug: str | None = None) -> dict:
    return {
        "id": canvas_id,
        "name": name or canvas_id,
        "scope": scope,
        "slug": slug,
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
    assert body["revision"]

    # List includes it
    listed = client.get("/api/canvases").json()["canvases"]
    assert any(c["id"] == "board-one" and c["scope"] == "global" and c["revision"] for c in listed)

    # Delete
    assert client.delete("/api/canvases/global/board-one").status_code == 200
    assert not saved.exists()
    assert client.get("/api/canvases/global/board-one").status_code == 404


def test_project_canvas_written_into_project_dir(client):
    # Create a project folder under the workspace root
    project = get_spark_home() / "workspace" / "myproj"
    project.mkdir(parents=True, exist_ok=True)

    resp = client.put("/api/canvases/project/myproj/flow", json=_doc("flow", "Flow", scope="project", slug="myproj"))
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


def test_canvas_viewport_and_dimensions_round_trip(client):
    doc = _doc("layout")
    doc["viewport"] = {"x": 42, "y": -12, "zoom": 1.75}
    doc["nodes"][0]["width"] = 320
    doc["nodes"][0]["height"] = 180

    resp = client.put("/api/canvases/global/layout", json=doc)
    assert resp.status_code == 200, resp.text

    got = client.get("/api/canvases/global/layout").json()
    assert got["viewport"] == {"x": 42, "y": -12, "zoom": 1.75}
    assert got["nodes"][0]["width"] == 320
    assert got["nodes"][0]["height"] == 180


def test_stale_revision_rejected(client):
    first = client.put("/api/canvases/global/revisioned", json=_doc("revisioned"))
    assert first.status_code == 200, first.text
    revision = first.json()["revision"]

    second_doc = _doc("revisioned", "Second")
    second_doc["expectedRevision"] = revision
    second = client.put("/api/canvases/global/revisioned", json=second_doc)
    assert second.status_code == 200, second.text

    stale_doc = _doc("revisioned", "Stale")
    stale_doc["expectedRevision"] = revision
    stale = client.put("/api/canvases/global/revisioned", json=stale_doc)

    assert stale.status_code == 409
    detail = stale.json()["detail"]
    assert detail["error"] == "revision_conflict"
    assert detail["currentRevision"]


def test_duplicate_node_ids_rejected(client):
    doc = _doc("dupes")
    doc["nodes"].append({"id": "n1", "type": "note", "position": {"x": 1, "y": 1}, "data": {}})

    resp = client.put("/api/canvases/global/dupes", json=doc)

    assert resp.status_code == 400
    assert "Duplicate canvas node id" in resp.json()["detail"]


def test_invalid_edge_references_rejected(client):
    doc = _doc("bad-edge")
    doc["edges"] = [{"id": "e1", "source": "n1", "target": "missing"}]

    resp = client.put("/api/canvases/global/bad-edge", json=doc)

    assert resp.status_code == 400
    assert "missing target node" in resp.json()["detail"]


def test_scope_mismatch_rejected(client):
    resp = client.put("/api/canvases/global/scope-mismatch", json=_doc("scope-mismatch", scope="project", slug="proj"))

    assert resp.status_code == 400
    assert "scope does not match" in resp.json()["detail"]


def test_slug_mismatch_rejected(client):
    project = get_spark_home() / "workspace" / "myproj"
    project.mkdir(parents=True, exist_ok=True)

    resp = client.put(
        "/api/canvases/project/myproj/slug-mismatch",
        json=_doc("slug-mismatch", scope="project", slug="other"),
    )

    assert resp.status_code == 400
    assert "slug does not match" in resp.json()["detail"]


def test_corrupt_canvas_file_listed_with_error(client):
    canvas_dir = get_spark_home() / "canvases"
    canvas_dir.mkdir(parents=True, exist_ok=True)
    (canvas_dir / "broken.canvas.json").write_text("{not-json", encoding="utf-8")

    listed = client.get("/api/canvases").json()["canvases"]

    broken = next(c for c in listed if c["id"] == "broken")
    assert broken["scope"] == "global"
    assert broken["error"]
