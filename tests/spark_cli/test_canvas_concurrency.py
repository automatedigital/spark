"""Real-filesystem regression coverage for canvas compare-and-save ownership."""

import json
import multiprocessing
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
