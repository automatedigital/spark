"""Real spawned processes and atomic disk writes at controlled interleavings."""

import json
import multiprocessing
import os
import traceback
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest


def _worker(home, operation, job_id, attempted, read, release, results, timeout=10):
    # Spawn, rather than fork, proves independently imported CLI/gateway owners
    # use the same profile-local lock. No provider or live user state is used.
    os.environ.update(SPARK_HOME=home, HOME=home, USERPROFILE=home)
    try:
        from cron import jobs

        jobs._LOCK_TIMEOUT = timeout
        original_lock = jobs._jobs_lock
        original_load = jobs._load_jobs

        @contextmanager
        def observed_lock():
            attempted.set()
            with original_lock():
                yield

        def observed_load():
            snapshot = original_load()
            read.set()
            if release is not None and not release.wait(8):
                raise TimeoutError("test did not release snapshot reader")
            return snapshot

        jobs._jobs_lock = observed_lock
        jobs._load_jobs = observed_load
        if operation == "create":
            jobs.create_job(prompt="new job", schedule="every 1h")
        elif operation == "mark":
            jobs.mark_job_run(job_id, success=True)
        elif operation == "pause":
            jobs.pause_job(job_id, reason="user request")
        elif operation == "advance":
            jobs.advance_next_run(job_id)
        elif operation == "remove":
            jobs.remove_job(job_id)
        elif operation == "resume":
            jobs.resume_job(job_id)
        elif operation == "update":
            jobs.update_job(job_id, {"schedule": {"kind": "interval", "minutes": 120}})
        elif operation == "repair":
            jobs.get_due_jobs()
        elif operation == "load":
            jobs.load_jobs()
        else:
            raise AssertionError(operation)
        results.put(None)
    except Exception:
        results.put(traceback.format_exc())
        raise


@pytest.fixture
def isolated_jobs(tmp_path, monkeypatch):
    for name in ("SPARK_HOME", "HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(tmp_path))
    from cron import jobs

    monkeypatch.setattr(jobs, "CRON_DIR", tmp_path / "cron")
    monkeypatch.setattr(jobs, "JOBS_FILE", tmp_path / "cron" / "jobs.json")
    monkeypatch.setattr(jobs, "OUTPUT_DIR", tmp_path / "cron" / "output")
    return jobs


def _overlap(tmp_path, first, second, job_id):
    ctx = multiprocessing.get_context("spawn")
    release = ctx.Event()
    results = ctx.Queue()
    processes = []
    try:
        for operation, gate in ((first, release), (second, None)):
            attempted, read = ctx.Event(), ctx.Event()
            process = ctx.Process(
                target=_worker,
                args=(str(tmp_path), operation, job_id, attempted, read, gate, results),
            )
            processes.append(process)
            process.start()
            assert attempted.wait(5), "child never reached storage lock"
            if gate is not None:
                assert read.wait(5), "first child never read snapshot"
            else:
                # The first process is paused after its real disk read. The
                # second must not read that same stale snapshot before commit.
                assert not read.wait(0.25), "second mutation read before first committed"
        release.set()
        for process in processes:
            process.join(8)
            assert not process.is_alive(), "child deadlocked"
            assert process.exitcode == 0, results.get(timeout=2)
        assert [results.get(timeout=2) for _ in processes] == [None, None]
    finally:
        release.set()
        for process in processes:
            if process.is_alive():
                process.terminate()
            process.join(2)
        results.close()


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("create", "create"),
        ("create", "mark"),
        ("pause", "mark"),
        ("mark", "pause"),
        ("advance", "create"),
        ("remove", "create"),
        ("repair", "create"),
        ("load", "create"),
        ("resume", "update"),
    ],
)
def test_mutations_serialize_across_processes(isolated_jobs, tmp_path, first, second):
    jobs = isolated_jobs
    job = jobs.create_job(prompt="existing", schedule="every 1h")
    if first in ("advance", "repair"):
        jobs.update_job(job["id"], {
            "next_run_at": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
        })
    elif first == "resume":
        jobs.pause_job(job["id"])
    elif first == "load":
        # Exercise load's control-character auto-repair with real malformed JSON.
        jobs.JOBS_FILE.write_text(jobs.JOBS_FILE.read_text().replace("existing", "ex\nisting"))

    _overlap(tmp_path, first, second, job["id"])

    stored = jobs.load_jobs()
    existing = jobs.get_job(job["id"])
    creates = (first, second).count("create")
    assert len(stored) == (0 if first == "remove" else 1) + creates
    assert sum(j["prompt"] == "new job" for j in stored) == creates
    if "mark" in (first, second):
        assert existing["repeat"]["completed"] == 1
        assert existing["last_status"] == "ok"
    if "pause" in (first, second):
        assert existing["state"] == "paused"
        assert existing["enabled"] is False
        assert existing["paused_reason"] == "user request"
    if first in ("advance", "repair"):
        assert datetime.fromisoformat(existing["next_run_at"]) > datetime.now(UTC)
    if first == "resume":
        assert existing["enabled"] is True
        assert existing["schedule"]["minutes"] == 120
        assert datetime.fromisoformat(existing["next_run_at"]) > datetime.now(UTC) + timedelta(minutes=119)
    if first == "load":
        assert existing["prompt"] == "ex\nisting"
        json.loads(jobs.JOBS_FILE.read_text())  # Strict parsing succeeds after repair.


def test_write_failure_releases_lock(isolated_jobs, monkeypatch):
    jobs = isolated_jobs
    job = jobs.create_job(prompt="keep", schedule="every 1h")
    before = jobs.JOBS_FILE.read_bytes()
    with monkeypatch.context() as patch:
        def fail_replace(*args):
            raise OSError("injected replace failure")
        patch.setattr(jobs.os, "replace", fail_replace)
        with pytest.raises(OSError, match="injected"):
            jobs.pause_job(job["id"])
    assert jobs.JOBS_FILE.read_bytes() == before
    assert list(jobs.JOBS_FILE.parent.glob(".jobs_*.tmp")) == []
    assert jobs.pause_job(job["id"])["state"] == "paused"


@pytest.mark.parametrize("replace_fails", [False, True])
def test_control_character_repair_closes_readers_before_replace(isolated_jobs, monkeypatch, replace_fails):
    jobs = isolated_jobs
    job = jobs.create_job(prompt="existing", schedule="every 1h")
    jobs.JOBS_FILE.write_text(jobs.JOBS_FILE.read_text().replace("existing", "ex\nisting"))
    before = jobs.JOBS_FILE.read_bytes()
    readers = []
    original_open = open
    original_replace = jobs.os.replace
    replacements = []

    def observed_open(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        if path == jobs.JOBS_FILE:
            readers.append(stream)
        return stream

    def observed_replace(source, destination):
        assert destination == jobs.JOBS_FILE
        assert len(readers) == 2  # Strict parse and permissive repair parse.
        assert all(reader.closed for reader in readers)
        assert jobs._JOBS_THREAD_LOCK.locked()
        replacements.append(destination)
        if replace_fails:
            raise PermissionError("injected repair publication failure")
        return original_replace(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr(jobs, "open", observed_open, raising=False)
        patch.setattr(jobs.os, "replace", observed_replace)
        if replace_fails:
            with pytest.raises(RuntimeError, match="injected repair publication failure") as error:
                jobs.load_jobs()
            assert isinstance(error.value.__cause__, PermissionError)
            assert jobs.JOBS_FILE.read_bytes() == before
        else:
            assert jobs.load_jobs()[0]["prompt"] == "ex\nisting"
            assert json.loads(jobs.JOBS_FILE.read_text())["jobs"][0]["id"] == job["id"]
    assert replacements == [jobs.JOBS_FILE]
    assert not list(jobs.JOBS_FILE.parent.glob(".jobs_*.tmp"))
    assert jobs.pause_job(job["id"])["state"] == "paused"


def test_lock_timeout_does_not_mutate_and_recovers(isolated_jobs, tmp_path):
    jobs = isolated_jobs
    job = jobs.create_job(prompt="keep", schedule="every 1h")
    before = jobs.JOBS_FILE.read_bytes()
    ctx = multiprocessing.get_context("spawn")
    attempted, read, results = ctx.Event(), ctx.Event(), ctx.Queue()
    process = ctx.Process(target=_worker, args=(
        str(tmp_path), "pause", job["id"], attempted, read, None, results, 0.2,
    ))
    try:
        with jobs._jobs_lock():
            process.start()
            assert attempted.wait(5)
            process.join(3)
            assert not process.is_alive()
            assert process.exitcode != 0
            assert "Timed out waiting for cron mutation lock" in results.get(timeout=2)
            assert not read.is_set()
            assert jobs.JOBS_FILE.read_bytes() == before
        assert jobs.pause_job(job["id"])["state"] == "paused"
    finally:
        if process.is_alive():
            process.terminate()
        process.join(2)
        results.close()


def test_unrepairable_json_preserved_and_lock_released(isolated_jobs):
    jobs = isolated_jobs
    jobs.ensure_dirs()
    jobs.JOBS_FILE.write_text('{"jobs": [broken')
    before = jobs.JOBS_FILE.read_bytes()
    with pytest.raises(RuntimeError, match="corrupted and unrepairable"):
        jobs.load_jobs()
    assert jobs.JOBS_FILE.read_bytes() == before
    jobs.save_jobs([])
    assert jobs.load_jobs() == []
