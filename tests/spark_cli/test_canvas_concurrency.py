"""Real-filesystem regression coverage for canvas compare-and-save ownership."""

import json
import multiprocessing
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import HTTPException

from spark_cli import canvas_routes as routes


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("SPARK_HOME", str(tmp_path / "profile"))


def save(name, expected=None, canvas_id="board"):
    return routes._write_canvas(
        "global",
        None,
        canvas_id,
        routes.CanvasDoc(
            id=canvas_id,
            name=name,
            expectedRevision=expected,
        ),
    )


def outcome(name, revision):
    try:
        return save(name, revision)
    except HTTPException as exc:
        return {"status": exc.status_code, "detail": exc.detail}


def process_save(home, revision, barrier, results, name):
    import os

    os.environ["SPARK_HOME"] = home
    barrier.wait(timeout=10)
    results.put((name, outcome(name, revision)))


@pytest.mark.parametrize("scope", ["global", "project"])
def test_same_revision_has_one_winner(scope, monkeypatch):
    if scope == "project":
        project = routes.get_spark_home() / "workspace" / "project"
        project.mkdir(parents=True)
    slug = "project" if scope == "project" else None

    def write(name, revision=None):
        try:
            return routes._write_canvas(
                scope,
                slug,
                "board",
                routes.CanvasDoc(
                    id="board",
                    name=name,
                    scope=scope,
                    slug=slug,
                    expectedRevision=revision,
                ),
            )
        except HTTPException as exc:
            return {"status": exc.status_code, "detail": exc.detail}

    revision = write("original")["revision"]
    replacing = threading.Event()
    release = threading.Event()
    contender = threading.Event()
    real_replace = Path.replace
    real_lock = routes._canvas_lock

    def replace(path, target):
        if threading.current_thread().name.startswith("winner"):
            replacing.set()
            assert release.wait(5)
        return real_replace(path, target)

    @contextmanager
    def lock(path):
        if threading.current_thread().name.startswith("loser"):
            contender.set()
        with real_lock(path):
            yield

    monkeypatch.setattr(Path, "replace", replace)
    monkeypatch.setattr(routes, "_canvas_lock", lock)
    with (
        ThreadPoolExecutor(1, thread_name_prefix="winner") as first,
        ThreadPoolExecutor(1, thread_name_prefix="loser") as second,
    ):
        a = first.submit(write, "A", revision)
        assert replacing.wait(5)
        b = second.submit(write, "B", revision)
        try:
            assert contender.wait(5)
            assert not b.done()
        finally:
            release.set()
        winner, loser = a.result(5), b.result(5)
    assert winner["ok"] is True
    assert loser == {
        "status": 409,
        "detail": {
            "error": "revision_conflict",
            "message": "Canvas was modified since it was loaded",
            "currentRevision": winner["revision"],
        },
    }
    got = routes._read_canvas(scope, slug, "board")
    assert got["name"] == "A"
    assert got["revision"] == winner["revision"] != revision


def test_separate_processes_share_revision_lock():
    revision = save("original")["revision"]
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(2)
    results = ctx.Queue()
    workers = [
        ctx.Process(
            target=process_save,
            args=(str(routes.get_spark_home()), revision, barrier, results, name),
        )
        for name in ("A", "B")
    ]
    for worker in workers:
        worker.start()
    try:
        received = [results.get(timeout=15) for _ in workers]
        winners = [(name, result) for name, result in received if result.get("ok")]
        losers = [result for _, result in received if result.get("status") == 409]
        assert len(winners) == len(losers) == 1
        name, result = winners[0]
        got = routes._read_canvas("global", None, "board")
        assert got["name"] == name
        assert got["revision"] == result["revision"] == losers[0]["detail"]["currentRevision"]
    finally:
        for worker in workers:
            worker.join(5)
            if worker.is_alive():
                worker.terminate()
                worker.join(5)
            assert worker.exitcode == 0


def test_delete_waits_for_save_and_other_canvas_is_independent(monkeypatch):
    revision = save("original")["revision"]
    entered, release, deleting = threading.Event(), threading.Event(), threading.Event()
    real_replace, real_lock = Path.replace, routes._canvas_lock

    def replace(path, target):
        if target.name == "board.canvas.json":
            entered.set()
            assert release.wait(5)
        return real_replace(path, target)

    @contextmanager
    def lock(path):
        if threading.current_thread().name.startswith("delete"):
            deleting.set()
        with real_lock(path):
            yield

    monkeypatch.setattr(Path, "replace", replace)
    monkeypatch.setattr(routes, "_canvas_lock", lock)
    with (
        ThreadPoolExecutor(1) as first,
        ThreadPoolExecutor(1, thread_name_prefix="delete") as second,
    ):
        writing = first.submit(save, "updated", revision)
        assert entered.wait(5)
        deletion = second.submit(routes._delete_canvas, "global", None, "board")
        try:
            assert deleting.wait(5)
            assert not deletion.done()
            assert save("independent", canvas_id="other")["ok"]
        finally:
            release.set()
        assert writing.result(5)["ok"]
        assert deletion.result(5)["ok"]
    assert not routes._canvas_path("global", None, "board").exists()
    assert outcome("stale", revision)["status"] == 409
    assert not routes._canvas_path("global", None, "board").exists()
    assert save("explicit recreation")["ok"]


def test_unique_temporary_files_with_frozen_clock(monkeypatch):
    monkeypatch.setattr(routes.time, "time", lambda: 1)
    paths = []
    real_replace = Path.replace

    def replace(path, target):
        paths.append(path)
        return real_replace(path, target)

    monkeypatch.setattr(Path, "replace", replace)
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(save, ["A", "B", "C", "D"]))
    assert all(result["ok"] for result in results)
    assert len(set(paths)) == 4
    assert len({result["revision"] for result in results}) == 4
    assert all(not path.exists() for path in paths)
    assert json.loads(routes._canvas_path("global", None, "board").read_text())["name"] in {
        "A",
        "B",
        "C",
        "D",
    }


def test_failed_replace_cleans_temp_and_releases_lock(monkeypatch):
    revision = save("original")["revision"]
    with monkeypatch.context() as patch:

        def fail(*args):
            raise OSError("fixture replace failure")

        patch.setattr(Path, "replace", fail)
        with pytest.raises(HTTPException, match="fixture replace failure") as error:
            save("failed", revision)
        assert error.value.status_code == 500
    assert not list(routes._global_dir().glob("*.tmp"))
    assert save("retry", revision)["ok"]


def test_deleted_revision_cannot_recreate_canvas():
    revision = save("original")["revision"]
    assert routes._delete_canvas("global", None, "board")["ok"]
    result = outcome("stale", revision)
    assert result["status"] == 409
    assert result["detail"]["currentRevision"] is None
    assert not routes._canvas_path("global", None, "board").exists()


@pytest.fixture
def client():
    from fastapi import FastAPI
    from starlette.testclient import TestClient

    app = FastAPI()
    routes.register_canvas_routes(app)
    return TestClient(app)


@pytest.mark.parametrize("scope", ["global", "project"])
@pytest.mark.parametrize("dangling", [False, True])
def test_final_symlinks_rejected_by_routes_and_listing(client, tmp_path, scope, dangling):
    project = routes.get_spark_home() / "workspace" / "project"
    project.mkdir(parents=True)
    directory = routes._global_dir() if scope == "global" else project
    outside = tmp_path / "outside.json"
    sentinel = b'{"name":"private sentinel"}'
    if not dangling:
        outside.write_bytes(sentinel)
    link = directory / "escape.canvas.json"
    link.symlink_to(outside)
    url = f"/api/canvases/{scope}/" + ("project/" if scope == "project" else "") + "escape"
    doc = {"id": "escape", "name": "overwrite", "scope": scope, "slug": "project" if scope == "project" else None}
    for response in (client.get(url), client.put(url, json=doc), client.delete(url)):
        assert response.status_code == 400, response.text
    assert client.get("/api/canvases").json() == {"canvases": []}
    assert link.is_symlink()
    assert outside.exists() is not dangling
    if not dangling:
        assert outside.read_bytes() == sentinel


@pytest.mark.parametrize("nofollow", [True, False])
def test_read_rejects_symlink_inserted_at_open(client, tmp_path, monkeypatch, nofollow):
    if not nofollow:
        monkeypatch.delattr(os, "O_NOFOLLOW", raising=False)
    save("original")
    path = routes._canvas_path("global", None, "board")
    outside = tmp_path / "outside.json"
    sentinel = b'{"name":"private sentinel"}'
    outside.write_bytes(sentinel)
    real_open = os.open

    def open_after_swap(filename, flags, *args, **kwargs):
        if Path(filename) == path:
            path.unlink()
            path.symlink_to(outside)
        return real_open(filename, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", open_after_swap)
    response = client.get("/api/canvases/global/board")
    assert response.status_code == 400
    assert "private sentinel" not in response.text
    assert outside.read_bytes() == sentinel


@pytest.mark.parametrize("action", ["read", "write", "delete"])
def test_symlink_inserted_while_waiting_for_lock_is_rejected(tmp_path, monkeypatch, action):
    save("original")
    path = routes._canvas_path("global", None, "board")
    outside = tmp_path / "outside.json"
    sentinel = b'{"name":"sentinel"}'
    outside.write_bytes(sentinel)
    real_lock = routes._canvas_lock

    @contextmanager
    def swapping_lock(filename):
        with real_lock(filename):
            path.unlink()
            path.symlink_to(outside)
            yield

    monkeypatch.setattr(routes, "_canvas_lock", swapping_lock)
    with pytest.raises(HTTPException) as error:
        if action == "write":
            save("overwrite")
        else:
            getattr(routes, f"_{action}_canvas")("global", None, "board")
    assert error.value.status_code == 400
    assert outside.read_bytes() == sentinel
    assert path.is_symlink()


def test_last_instant_symlink_cannot_redirect_atomic_save(tmp_path, monkeypatch):
    revision = save("original")["revision"]
    path = routes._canvas_path("global", None, "board")
    outside = tmp_path / "outside.json"
    sentinel = b'{"name":"sentinel"}'
    outside.write_bytes(sentinel)
    real_replace = Path.replace

    def swapping_replace(temp, destination):
        assert destination == path
        path.unlink()
        path.symlink_to(outside)
        return real_replace(temp, destination)

    monkeypatch.setattr(Path, "replace", swapping_replace)
    assert save("safe lexical save", revision)["ok"]
    assert not path.is_symlink()
    assert json.loads(path.read_text())["name"] == "safe lexical save"
    assert outside.read_bytes() == sentinel


def project_process_save(home, started, results):
    os.environ["SPARK_HOME"] = home
    started.set()
    try:
        results.put(routes._write_canvas(
            "project", "alias", "board",
            routes.CanvasDoc(id="board", name="contender", scope="project", slug="alias"),
        ))
    except Exception as exc:
        results.put({"error": str(exc)})


def test_git_revert_and_project_alias_cannot_split_process_lock(tmp_path):
    from spark_cli import workspace_routes

    project = tmp_path / "real-project"
    project.mkdir()
    workspace = workspace_routes._workspace_root()
    for alias in ("project", "alias"):
        (workspace / alias).symlink_to(project, target_is_directory=True)

    def git(*args):
        subprocess.run(["git", *args], cwd=project, check=True, capture_output=True)

    git("init", "-q")
    git("-c", "user.name=fixture", "-c", "user.email=fixture@example.com", "commit", "--allow-empty", "-qm", "init")
    doc = routes.CanvasDoc(id="board", name="original", scope="project", slug="project")
    revision = routes._write_canvas("project", "project", "board", doc)["revision"]
    path = routes._canvas_path("project", "project", "board")
    assert path.parent == project.resolve()
    assert routes._canvas_lock_path(path) == routes._canvas_lock_path(routes._canvas_path("project", "alias", "board"))
    metadata = routes._canvas_lock_path(path)
    assert metadata.parent == routes.get_spark_home() / "canvas-locks"
    assert not metadata.is_relative_to(project)
    legacy = project / ".board.canvas.json.lock"
    ctx = multiprocessing.get_context("spawn")
    started, results = ctx.Event(), ctx.Queue()
    worker = ctx.Process(target=project_process_save, args=(str(routes.get_spark_home()), started, results))
    try:
        with routes._canvas_lock(path):
            inode = metadata.stat().st_ino
            legacy.touch()
            assert workspace_routes.git_revert("project", workspace_routes.RevertBody(path=legacy.name))["ok"]
            assert not legacy.exists()
            legacy.touch()
            legacy.unlink()
            worker.start()
            assert started.wait(5)
            # A real second process cannot complete its route until release.
            import queue

            with pytest.raises(queue.Empty):
                results.get(timeout=0.5)
            assert metadata.stat().st_ino == inode
            assert json.loads(path.read_text())["name"] == "original"
            assert save("independent global")["ok"]
        assert results.get(timeout=10)["ok"]
        worker.join(5)
        assert worker.exitcode == 0
    finally:
        if worker.pid is not None and worker.is_alive():
            worker.terminate()
            worker.join(5)
    assert routes._read_canvas("project", "project", "board")["name"] == "contender"
    assert routes._delete_canvas("project", "alias", "board")["ok"]
    assert metadata.exists()  # Never retire a lock while another waiter may own it.
    doc.expectedRevision = revision
    with pytest.raises(HTTPException) as error:
        routes._write_canvas("project", "project", "board", doc)
    assert error.value.status_code == 409
    assert not path.exists()


def test_symlink_inserted_during_serialization_rejects_save_and_cleans_temp(tmp_path, monkeypatch):
    revision = save("original")["revision"]
    path = routes._canvas_path("global", None, "board")
    outside = tmp_path / "outside.json"
    sentinel = b'{"name":"sentinel"}'
    outside.write_bytes(sentinel)
    real_temp = routes.tempfile.NamedTemporaryFile

    @contextmanager
    def swapped_temp(*args, **kwargs):
        with real_temp(*args, **kwargs) as fh:
            yield fh
        path.unlink()
        path.symlink_to(outside)

    monkeypatch.setattr(routes.tempfile, "NamedTemporaryFile", swapped_temp)
    with pytest.raises(HTTPException) as error:
        save("unsafe", revision)
    assert error.value.status_code == 400
    assert path.is_symlink()
    assert outside.read_bytes() == sentinel
    assert not list(path.parent.glob("*.tmp"))
