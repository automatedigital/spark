"""P06 navigation uses real profile-local SQLite and owned Git checkouts."""
from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from core import kanban_db as kb
from core.spark_constants import get_spark_home
from core.spark_state import SessionDB
from tools.subagent_worktree import create_subagent_worktree


def git(directory, *args):
    return subprocess.check_output(["git", "-c", "core.hooksPath=/dev/null", *args], cwd=directory, text=True).strip()


@pytest.fixture
def owned(tmp_path):
    repo = tmp_path / "repository"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "retained.txt").write_text("committed parent\n")
    git(repo, "add", "retained.txt")
    git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture")
    (repo / "retained.txt").write_text("dirty parent\n")
    record = create_subagent_worktree(repo, "owned-child")
    (Path(record.path) / "child-dirty.txt").write_text("useful active child work\n")
    db = SessionDB()
    for sid in ("original", "compressed", "unrelated"):
        db.create_session(sid, source="web", model="fixture", parent_session_id="original" if sid == "compressed" else None)
    db._execute_write(lambda conn: conn.execute("UPDATE sessions SET end_reason='compression' WHERE id='original'"))
    db.create_subagent_run({"id": "owned-child", "parent_session_id": "compressed", "status": "running", "worktree": record.as_dict()})
    db.close()
    from spark_cli.web_server import app
    return TestClient(app), repo, record


def linked_task(session_id="original", title="Actual linked task"):
    profile = "fixture-" + session_id
    task = kb.create_task(title=title, assignee=profile)
    kb.patch_task(task["id"], status="ready")
    token, run_id = kb.claim_ready_task(task["id"], profile=profile, claim_ttl_seconds=300)
    kb.record_worker_execution(task["id"], claim_token=token, run_id=run_id, execution={"session_id": session_id})
    return task, run_id


def endpoint(sid="original"):
    return f"/api/conversations/{sid}/subagents/owned-child/navigation"


def test_read_navigation_absent_board_is_read_only_and_compression_owned(owned):
    client, _, record = owned
    home = get_spark_home()
    for sid in ("original", "compressed"):
        value = client.get(endpoint(sid)).json()
        assert value["schema_version"] == 1
        assert value["task"]["supported"] is False
        assert "profile" in value["task"]["reason"]
        assert value["worktree"]["supported"] is True
        assert value["worktree"]["path"] == record.path
    assert not (home / "kanban.db").exists()
    assert not list((home / "workspace").glob("subagent-*"))


def test_actual_task_link_deleted_task_and_no_session_name_parsing(owned):
    client, _, _ = owned
    task, run_id = linked_task()
    assert client.get(endpoint()).json()["task"] == {
        "supported": True, "reason": None, "id": task["id"], "title": task["title"], "board_slug": "default", "run_id": run_id,
    }
    # A deleted task cannot leave a navigable dangling run/reference.
    kb.delete_task(task["id"])
    assert client.get(endpoint()).json()["task"]["supported"] is False
    assert not kb.task_references_for_sessions([f"kanban_{task['id']}_{run_id}"])


def test_ambiguous_tasks_do_not_choose_an_arbitrary_board_destination(owned):
    client, _, _ = owned
    linked_task()
    linked_task("compressed", "Another linked task")
    value = client.get(endpoint()).json()["task"]
    assert value["supported"] is False
    assert "Several" in value["reason"]
    assert "id" not in value


def test_foreign_profile_and_worker_board_override_are_not_followed(owned, monkeypatch, tmp_path):
    client, _, _ = owned
    active = get_spark_home()
    foreign = tmp_path / "foreign-profile"
    monkeypatch.setenv("SPARK_HOME", str(foreign))
    task, _ = linked_task()
    monkeypatch.setenv("SPARK_HOME", str(active))
    with kb.board_home(foreign):
        assert kb.task_references_for_sessions(["original"]) == []
    monkeypatch.setenv("SPARK_KANBAN_BOARD_HOME", str(foreign))
    assert client.get(endpoint()).json()["task"]["supported"] is False
    assert not (active / "kanban.db").exists()
    # Even a board symlink must not expose a different profile.
    (active / "kanban.db").symlink_to(foreign / "kanban.db")
    assert client.get(endpoint()).json()["task"]["supported"] is False
    assert task["id"] not in client.get(endpoint()).text


def test_open_worktree_idempotent_symlink_keeps_dirty_parent_and_active_child(owned):
    client, repo, record = owned
    before = git(repo, "status", "--porcelain")
    first = client.post(endpoint() + "/worktree", json={"path": str(repo), "source": "new_folder", "init_git": True})
    assert first.status_code == 200, first.text
    value = first.json()
    entry = get_spark_home() / "workspace" / value["project_slug"]
    inode = entry.lstat().st_ino
    assert entry.is_symlink() and entry.resolve() == Path(record.path).resolve()
    assert client.post(endpoint("compressed") + "/worktree").json() == value
    assert entry.lstat().st_ino == inode
    assert git(repo, "status", "--porcelain") == before
    assert (repo / "retained.txt").read_text() == "dirty parent\n"
    assert (Path(record.path) / "child-dirty.txt").read_text() == "useful active child work\n"
    assert git(record.path, "symbolic-ref", "--short", "HEAD") == record.branch
    assert git(record.path, "rev-parse", "HEAD") == record.base_commit
    assert json.loads((get_spark_home() / "subagent-worktrees/owned-child.json").read_text())["active"] is True
    projects = client.get("/api/workspace/projects").json()["projects"]
    assert any(project["slug"] == entry.name for project in projects)
    tree = client.get(f"/api/workspace/projects/{entry.name}/tree").json()
    assert "child-dirty.txt" in json.dumps(tree)


@pytest.mark.parametrize("collision", ["directory", "foreign_symlink", "broken_symlink"])
def test_collision_refuses_without_mutating_existing_entry(owned, tmp_path, collision):
    client, _, _ = owned
    slug = client.get(endpoint()).json()["worktree"]["project_slug"]
    entry = get_spark_home() / "workspace" / slug
    entry.parent.mkdir(exist_ok=True)
    if collision == "directory":
        entry.mkdir()
        (entry / "keep").write_text("retain")
    else:
        target = tmp_path / "other"
        if collision == "foreign_symlink":
            target.mkdir()
        entry.symlink_to(target, target_is_directory=True)
    inode = entry.lstat().st_ino
    assert client.post(endpoint() + "/worktree").status_code == 409
    assert client.get(endpoint()).json()["worktree"]["supported"] is False
    assert entry.lstat().st_ino == inode
    assert len(list(entry.parent.glob("subagent-*"))) == 1


@pytest.mark.parametrize("change", ["missing_checkout", "metadata_path", "snapshot_path", "branch", "missing_metadata", "invalid_metadata"])
def test_unverifiable_worktree_never_creates_project(owned, tmp_path, change):
    client, repo, record = owned
    metadata = get_spark_home() / "subagent-worktrees/owned-child.json"
    if change == "missing_checkout":
        Path(record.path).rename(tmp_path / "retained-checkout")
    elif change == "missing_metadata":
        metadata.unlink()
    elif change == "metadata_path":
        value = json.loads(metadata.read_text())
        value["path"] = str(repo)
        metadata.write_text(json.dumps(value))
    elif change == "invalid_metadata":
        value = json.loads(metadata.read_text())
        value["repository"] = ["not", "a", "path"]
        metadata.write_text(json.dumps(value))
    elif change == "snapshot_path":
        db = SessionDB()
        run = db.get_subagent_run("owned-child")
        db.create_subagent_run({**run, "worktree": {**record.as_dict(), "path": str(repo)}})
        db.close()
    elif change == "branch":
        git(record.path, "checkout", "-b", "feat/another-owned-branch")
    assert client.get(endpoint()).json()["worktree"]["supported"] is False
    assert client.post(endpoint() + "/worktree").status_code == 409
    assert not list((get_spark_home() / "workspace").glob("subagent-*"))


def test_unowned_or_foreign_child_cannot_create_files(owned, monkeypatch, tmp_path):
    client, _, _ = owned
    home = get_spark_home()
    assert client.get(endpoint("unrelated")).status_code == 404
    assert client.post(endpoint("unrelated") + "/worktree").status_code == 404
    assert client.post(endpoint().replace("owned-child", "missing") + "/worktree").status_code == 404
    assert not list((home / "workspace").glob("subagent-*"))
    monkeypatch.setenv("SPARK_HOME", str(tmp_path / "another-profile"))
    assert client.get(endpoint()).status_code == 404
    assert client.post(endpoint() + "/worktree").status_code == 404
    assert not list((get_spark_home() / "workspace").glob("subagent-*"))


def test_remote_navigation_keeps_dashboard_auth_and_child_ownership(owned, monkeypatch):
    local, _, _ = owned
    monkeypatch.setenv("SPARK_DASHBOARD_TOKEN", "navigation-auth-fixture")
    remote = TestClient(local.app, client=("198.51.100.2", 8000))
    assert remote.get(endpoint()).status_code == 401
    assert remote.post(endpoint() + "/worktree?dashboard_token=navigation-auth-fixture").status_code == 401
    headers = {"Authorization": "Bearer navigation-auth-fixture"}
    assert remote.get(endpoint(), headers=headers).status_code == 200
    assert remote.post(endpoint("unrelated") + "/worktree", headers=headers).status_code == 404
    assert not list((get_spark_home() / "workspace").glob("subagent-*"))


def test_legacy_or_corrupt_board_navigation_does_not_repair_schema():
    path = get_spark_home() / "kanban.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE legacy (retained TEXT)")
    before = path.read_bytes()
    assert kb.task_references_for_sessions(["original"]) == []
    assert path.read_bytes() == before
    path.write_bytes(b"retained non-sqlite fixture")
    assert kb.task_references_for_sessions(["original"]) == []
    assert path.read_bytes() == b"retained non-sqlite fixture"
