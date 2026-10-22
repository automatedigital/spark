"""Tests for the project git endpoints powering the Changes (diff) tab."""

from __future__ import annotations

import json
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


@pytest.fixture(autouse=True)
def isolated_user_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


EXACT_PATHS = [
    "café.txt", "two words.txt", "tab\tname.txt", "line\nname.txt",
    "carriage\rname.txt", "literal -> arrow.txt", '"quoted.txt"',
    " leading and trailing.txt ", "back\\slash.txt",
]


@pytest.mark.parametrize("path", EXACT_PATHS)
@pytest.mark.parametrize("tracked", [False, True], ids=["untracked", "tracked"])
def test_exact_path_status_diff_revert(client, path, tracked):
    project = _make_repo()
    target = project / path
    if tracked:
        target.write_text("original\n", encoding="utf-8")
        _git(project, "add", "--", path)
        _git(project, "commit", "-qm", "track exact path")
    target.write_text("changed\nsecond\n", encoding="utf-8")

    response = client.get("/api/workspace/projects/repo/git/status")
    assert response.status_code == 200
    body = response.json()
    assert body["files"] == [{
        "path": path, "status": "modified" if tracked else "added",
        "adds": 2, "dels": 1 if tracked else 0,
    }]
    assert (body["total_adds"], body["total_dels"]) == (2, 1 if tracked else 0)
    returned_path = body["files"][0]["path"]
    diff = client.get("/api/workspace/projects/repo/git/diff", params={"path": returned_path})
    assert diff.status_code == 200
    assert "+changed\n+second" in diff.json()["diff"]
    reverted = client.post("/api/workspace/projects/repo/git/revert", json={"path": returned_path})
    assert reverted.status_code == 200
    if tracked:
        assert target.read_text() == "original\n"
    else:
        assert not target.exists()
    assert client.get("/api/workspace/projects/repo/git/status").json()["files"] == []


def test_exact_rename_records_and_following_file(client):
    project = _make_repo()
    source = 'old\t"café -> source.txt'
    destination = '"new\n雪 -> destination.txt"'
    original = "".join(f"line {i}\n" for i in range(30))
    (project / source).write_text(original, encoding="utf-8")
    _git(project, "add", "--", source)
    _git(project, "commit", "-qm", "track rename source")
    _git(project, "mv", "--", source, destination)
    (project / destination).write_text(original + "extra\n", encoding="utf-8")
    (project / "a.txt").write_text("one\ntwo\nfollowing\n")
    (project / "z.bin").write_bytes(b"\0binary")
    _git(project, "add", "--", "z.bin")

    response = client.get("/api/workspace/projects/repo/git/status")
    assert response.status_code == 200
    body = response.json()
    assert body["files"] == sorted([
        {"path": destination, "status": "modified", "adds": 1, "dels": 0},
        {"path": "a.txt", "status": "modified", "adds": 1, "dels": 0},
        {"path": "z.bin", "status": "added", "adds": None, "dels": None},
    ], key=lambda row: row["path"])
    assert (body["total_adds"], body["total_dels"]) == (2, 0)
    diff = client.get("/api/workspace/projects/repo/git/diff", params={"path": destination})
    assert diff.status_code == 200
    assert "+extra" in diff.json()["diff"]


def test_non_utf8_tree_name_is_disabled_with_valid_neighbor(client):
    project = _make_repo()
    blob = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"], cwd=project,
        input=b"raw content\n", check=True, capture_output=True,
    ).stdout.strip()
    # Tree/index entries work even on macOS filesystems rejecting raw bytes.
    _git(project, "update-index", "--add", "--cacheinfo", b"100644," + blob + b",invalid-\xff.txt")
    _git(project, "commit", "-qm", "raw byte tree entry")
    (project / "a.txt").write_text("neighbor edit\n")
    # This real filename resembles the escaped label; it must stay independent.
    label_neighbor = "invalid-\\xff.txt"
    (project / label_neighbor).write_text("valuable label neighbor\n")

    response = client.get("/api/workspace/projects/repo/git/status")
    assert response.status_code == 200
    rows = response.json()["files"]
    unsupported = next(row for row in rows if row.get("unsupported_reason"))
    assert unsupported["path"] == ""
    assert unsupported["display_path"] == "b'invalid-\\xff.txt'"
    assert any(row["path"] == "a.txt" for row in rows)
    assert any(row["path"] == label_neighbor for row in rows)
    # Empty/invalid action paths never become an escaped actionable filename.
    for path in ["", "invalid-\udcff.txt", "nul\0name"]:
        response = client.post(
            "/api/workspace/projects/repo/git/revert",
            content=json.dumps({"path": path}), headers={"content-type": "application/json"},
        )
        assert response.status_code == 400
    assert (project / label_neighbor).read_text() == "valuable label neighbor\n"
    assert client.get("/api/workspace/projects/repo/git/diff").status_code == 200
    assert "+neighbor edit" in client.get(
        "/api/workspace/projects/repo/git/diff", params={"path": "a.txt"},
    ).json()["diff"]
    assert client.post("/api/workspace/projects/repo/git/revert", json={"path": "a.txt"}).status_code == 200
    assert (project / "a.txt").read_text() == "one\ntwo\n"


@pytest.mark.parametrize("path", ["[ab].txt", "*.txt", ":(glob)*.txt", "?.txt"])
@pytest.mark.parametrize("tracked", [True, False])
def test_literal_pathspec_diff_and_discard_preserve_neighbor(client, path, tracked):
    project = _make_repo()
    literal = project / path
    if tracked:
        literal.write_text("literal original\n")
        _git(project, "--literal-pathspecs", "add", "--", path)
        _git(project, "commit", "-qm", "literal filename")
    literal.write_text("literal edit\n")
    (project / "a.txt").write_text("valuable sentinel\n")
    diff = client.get("/api/workspace/projects/repo/git/diff", params={"path": path})
    assert diff.status_code == 200
    assert "+literal edit" in diff.json()["diff"]
    assert "valuable sentinel" not in diff.json()["diff"]
    response = client.post("/api/workspace/projects/repo/git/revert", json={"path": path})
    assert response.status_code == 200
    if tracked:
        assert literal.read_text() == "literal original\n"
    else:
        assert not literal.exists()
    assert (project / "a.txt").read_text() == "valuable sentinel\n"


@pytest.mark.parametrize("tracked", [True, False])
@pytest.mark.parametrize("destination", ["a.txt", "missing.txt", "directory", "outside"])
def test_symlink_discard_targets_link_not_destination(client, tmp_path, tracked, destination):
    project = _make_repo()
    (project / "directory").mkdir()
    (project / "directory/sentinel").write_text("directory sentinel\n")
    outside = tmp_path / "outside"
    outside.write_text("outside sentinel\n")
    link = project / "nested/link"
    link.parent.mkdir()
    if tracked:
        link.symlink_to("../missing-original")
        _git(project, "add", "--", "nested/link")
        _git(project, "commit", "-qm", "tracked link")
        link.unlink()
    link.symlink_to(outside if destination == "outside" else project / destination)
    response = client.post("/api/workspace/projects/repo/git/revert", json={"path": "nested/link"})
    assert response.status_code == 200
    if tracked:
        assert link.is_symlink()
        assert link.readlink().as_posix() == "../missing-original"
    else:
        assert not link.is_symlink()
    assert (project / "a.txt").read_text() == "one\ntwo\n"
    assert (project / "directory/sentinel").read_text() == "directory sentinel\n"
    assert outside.read_text() == "outside sentinel\n"


def test_git_actions_reject_symlink_parent(client):
    project = _make_repo()
    (project / "real").mkdir()
    sentinel = project / "real/sentinel"
    sentinel.write_text("keep\n")
    (project / "alias").symlink_to(project / "real", target_is_directory=True)
    assert client.post(
        "/api/workspace/projects/repo/git/revert", json={"path": "alias/sentinel"},
    ).status_code == 400
    assert client.get(
        "/api/workspace/projects/repo/git/diff", params={"path": "alias/sentinel"},
    ).status_code == 400
    assert sentinel.read_text() == "keep\n"


def test_diff_invalid_utf8_content_is_display_safe(client):
    project = _make_repo()
    (project / "a.txt").write_bytes(b"invalid \xff\n")
    response = client.get("/api/workspace/projects/repo/git/diff", params={"path": "a.txt"})
    assert response.status_code == 200
    assert "+invalid \\udcff" in response.json()["diff"]


def test_git_actions_allow_linked_project_root(client, tmp_path):
    project = _make_repo()
    actual = tmp_path / "actual-repo"
    project.rename(actual)
    project.symlink_to(actual, target_is_directory=True)
    (actual / "a.txt").write_text("linked edit\n")
    diff = client.get("/api/workspace/projects/repo/git/diff", params={"path": "a.txt"})
    assert diff.status_code == 200
    assert "+linked edit" in diff.json()["diff"]
    assert client.post("/api/workspace/projects/repo/git/revert", json={"path": "a.txt"}).status_code == 200
    assert (actual / "a.txt").read_text() == "one\ntwo\n"
