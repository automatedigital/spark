"""Tests for project-scoped file mutation endpoints (write/mkdir/rename).

Covers the endpoints added for the Files-pane inline operations.
"""

from __future__ import annotations

import pytest

from spark_cli.config import get_spark_home


@pytest.fixture
def client():
    fastapi = pytest.importorskip("fastapi")
    from starlette.testclient import TestClient

    from spark_cli.workspace_routes import register_workspace_routes

    app = fastapi.FastAPI()
    register_workspace_routes(app)
    return TestClient(app)


def _make_project(slug: str = "proj"):
    project = get_spark_home() / "workspace" / slug
    project.mkdir(parents=True, exist_ok=True)
    return project


def test_write_creates_file(client):
    _make_project()
    res = client.put("/api/workspace/projects/proj/file?path=notes/todo.md", json={"content": "hi"})
    assert res.status_code == 200
    assert (get_spark_home() / "workspace" / "proj" / "notes" / "todo.md").read_text() == "hi"


def test_write_overwrites_existing(client):
    project = _make_project()
    (project / "a.txt").write_text("old")
    res = client.put("/api/workspace/projects/proj/file?path=a.txt", json={"content": "new"})
    assert res.status_code == 200
    assert (project / "a.txt").read_text() == "new"


def test_write_rejects_directory_path(client):
    project = _make_project()
    (project / "sub").mkdir()
    res = client.put("/api/workspace/projects/proj/file?path=sub", json={"content": "x"})
    assert res.status_code == 400


def test_mkdir_creates_directory(client):
    _make_project()
    res = client.post("/api/workspace/projects/proj/mkdir?path=src/components")
    assert res.status_code == 200
    assert (get_spark_home() / "workspace" / "proj" / "src" / "components").is_dir()


def test_mkdir_conflict_on_existing(client):
    project = _make_project()
    (project / "exists").mkdir()
    res = client.post("/api/workspace/projects/proj/mkdir?path=exists")
    assert res.status_code == 409


def test_rename_moves_file(client):
    project = _make_project()
    (project / "old.txt").write_text("data")
    res = client.post(
        "/api/workspace/projects/proj/rename",
        json={"src": "old.txt", "dst": "renamed.txt"},
    )
    assert res.status_code == 200
    assert not (project / "old.txt").exists()
    assert (project / "renamed.txt").read_text() == "data"


def test_rename_missing_source(client):
    _make_project()
    res = client.post(
        "/api/workspace/projects/proj/rename",
        json={"src": "ghost.txt", "dst": "x.txt"},
    )
    assert res.status_code == 404


def test_rename_conflict_on_existing_dst(client):
    project = _make_project()
    (project / "a.txt").write_text("a")
    (project / "b.txt").write_text("b")
    res = client.post(
        "/api/workspace/projects/proj/rename",
        json={"src": "a.txt", "dst": "b.txt"},
    )
    assert res.status_code == 409


def test_project_rename_migrates_session_sources(client):
    _make_project("old-proj")
    from core.spark_state import SessionDB

    db = SessionDB()
    try:
        db.create_session("project-chat", source="workspace:old-proj")
        db.create_session("plain-chat", source="web")
    finally:
        db.close()

    res = client.post(
        "/api/workspace/projects/old-proj/rename-project",
        json={"name": "new proj"},
    )

    assert res.status_code == 200
    assert res.json()["slug"] == "new-proj"
    assert not (get_spark_home() / "workspace" / "old-proj").exists()
    assert (get_spark_home() / "workspace" / "new-proj").is_dir()

    db = SessionDB()
    try:
        assert db.get_session("project-chat")["source"] == "workspace:new-proj"
        assert db.get_session("plain-chat")["source"] == "web"
    finally:
        db.close()


def test_path_traversal_rejected(client):
    _make_project()
    res = client.put("/api/workspace/projects/proj/file?path=../escape.txt", json={"content": "x"})
    assert res.status_code == 400


def test_global_workspace_scope_uses_workspace_root(client):
    workspace = get_spark_home() / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "root-note.md").write_text("hello root")

    tree = client.get("/api/workspace/projects/__workspace__/tree")
    assert tree.status_code == 200
    names = {node["name"] for node in tree.json()["tree"]}
    assert "root-note.md" in names

    read = client.get("/api/workspace/projects/__workspace__/file?path=root-note.md")
    assert read.status_code == 200
    assert read.json()["content"] == "hello root"

    written = client.put(
        "/api/workspace/projects/__workspace__/file?path=notes/from-chat.md",
        json={"content": "from chat"},
    )
    assert written.status_code == 200
    assert (workspace / "notes" / "from-chat.md").read_text() == "from chat"


def test_global_workspace_scope_cannot_delete_workspace_root(client):
    workspace = get_spark_home() / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    res = client.delete("/api/workspace/projects/__workspace__")

    assert res.status_code == 400
    assert workspace.exists()
