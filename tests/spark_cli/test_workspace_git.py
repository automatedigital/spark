"""Tests for the project git endpoints powering the Changes (diff) tab."""

from __future__ import annotations

import shutil
import subprocess

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


def _git(project, *args):
    subprocess.run(["git", *args], cwd=str(project), check=True, capture_output=True, text=True)


def _make_repo(slug: str = "repo"):
    project = get_spark_home() / "workspace" / slug
    project.mkdir(parents=True, exist_ok=True)
    _git(project, "init", "-q")
    _git(project, "config", "user.email", "t@t.t")
    _git(project, "config", "user.name", "t")
    (project / "a.txt").write_text("one\ntwo\n")
    _git(project, "add", "-A")
    _git(project, "commit", "-qm", "init")
    return project


def _make_plain_project(slug: str = "plain"):
    project = get_spark_home() / "workspace" / slug
    project.mkdir(parents=True, exist_ok=True)
    (project / "f.txt").write_text("hi")
    return project


git_missing = shutil.which("git") is None
pytestmark = pytest.mark.skipif(git_missing, reason="git not installed")


def test_status_non_git(client):
    _make_plain_project()
    body = client.get("/api/workspace/projects/plain/git/status").json()
    assert body["is_repo"] is False
    assert body["files"] == []


def test_status_clean_repo(client):
    _make_repo()
    body = client.get("/api/workspace/projects/repo/git/status").json()
    assert body["is_repo"] is True
    assert body["files"] == []
    assert body["total_adds"] == 0


def test_status_modified_file(client):
    project = _make_repo()
    (project / "a.txt").write_text("one\ntwo\nthree\n")
    body = client.get("/api/workspace/projects/repo/git/status").json()
    by_path = {f["path"]: f for f in body["files"]}
    assert by_path["a.txt"]["status"] == "modified"
    assert by_path["a.txt"]["adds"] == 1
    assert body["total_adds"] == 1


def test_status_untracked_added(client):
    project = _make_repo()
    (project / "new.txt").write_text("x\ny\nz\n")
    body = client.get("/api/workspace/projects/repo/git/status").json()
    by_path = {f["path"]: f for f in body["files"]}
    assert by_path["new.txt"]["status"] == "added"
    assert by_path["new.txt"]["adds"] == 3


def test_status_deleted_file(client):
    project = _make_repo()
    (project / "a.txt").unlink()
    body = client.get("/api/workspace/projects/repo/git/status").json()
    by_path = {f["path"]: f for f in body["files"]}
    assert by_path["a.txt"]["status"] == "deleted"


def test_diff_for_file(client):
    project = _make_repo()
    (project / "a.txt").write_text("one\ntwo\nthree\n")
    body = client.get("/api/workspace/projects/repo/git/diff", params={"path": "a.txt"}).json()
    assert "+three" in body["diff"]


def test_diff_untracked_file(client):
    project = _make_repo()
    (project / "new.txt").write_text("hello\n")
    body = client.get("/api/workspace/projects/repo/git/diff", params={"path": "new.txt"}).json()
    assert "+hello" in body["diff"]


def test_revert_tracked_file(client):
    project = _make_repo()
    (project / "a.txt").write_text("garbage\n")
    res = client.post("/api/workspace/projects/repo/git/revert", json={"path": "a.txt"})
    assert res.status_code == 200
    assert (project / "a.txt").read_text() == "one\ntwo\n"


def test_revert_untracked_file_deletes_it(client):
    project = _make_repo()
    (project / "junk.txt").write_text("x")
    res = client.post("/api/workspace/projects/repo/git/revert", json={"path": "junk.txt"})
    assert res.status_code == 200
    assert not (project / "junk.txt").exists()


def test_nested_untracked_files_status_diff_and_revert(client):
    project = _make_repo()
    (project / ".gitignore").write_text("*.ignored\n")
    _git(project, "add", ".gitignore")
    _git(project, "commit", "-qm", "ignore fixture files")
    contents = {"newdir/child.txt": "first\nsecond\n", "newdir/nested/leaf.txt": "leaf\n"}
    for path, content in contents.items():
        target = project / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    ignored = project / "newdir/keep.ignored"
    ignored.write_text("keep me\n")

    status = client.get("/api/workspace/projects/repo/git/status")
    assert status.status_code == 200
    assert status.json()["files"] == [
        {"path": path, "status": "added", "adds": len(content.splitlines()), "dels": 0}
        for path, content in contents.items()
    ]
    assert status.json()["total_adds"] == 3
    assert status.json()["total_dels"] == 0

    for path, content in contents.items():
        diff = client.get("/api/workspace/projects/repo/git/diff", params={"path": path})
        assert diff.status_code == 200
        for line in content.splitlines():
            assert f"+{line}\n" in diff.json()["diff"]
        response = client.post("/api/workspace/projects/repo/git/revert", json={"path": path})
        assert response.status_code == 200
        assert not (project / path).exists()
        for sibling, sibling_content in contents.items():
            if sibling > path:
                assert (project / sibling).read_text() == sibling_content
        assert ignored.read_text() == "keep me\n"
    assert client.get("/api/workspace/projects/repo/git/status").json()["files"] == []
    assert (project / "newdir/nested").is_dir()


@pytest.mark.parametrize("path", ["newdir", "newdir/", "tracked", "", "."])
def test_revert_rejects_directories_without_changing_contents(client, path):
    project = _make_repo()
    tracked = project / "tracked/child.txt"
    tracked.parent.mkdir()
    tracked.write_text("original\n")
    _git(project, "add", "tracked")
    _git(project, "commit", "-qm", "tracked directory")
    tracked.write_text("edited\n")
    untracked = project / "newdir/nested/child.txt"
    untracked.parent.mkdir(parents=True)
    untracked.write_text("untracked\n")

    response = client.post("/api/workspace/projects/repo/git/revert", json={"path": path})

    assert response.status_code == 400
    assert "file path" in response.json()["detail"]
    assert tracked.read_text() == "edited\n"
    assert untracked.read_text() == "untracked\n"


def test_diff_non_git_400(client):
    _make_plain_project()
    res = client.get("/api/workspace/projects/plain/git/diff", params={"path": "f.txt"})
    assert res.status_code == 400
