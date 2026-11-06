"""Real process ownership and queued terminal retirement regressions."""
import os
import subprocess
import threading
import time

import pytest

from spark_cli import workspace_routes as w
from spark_cli.terminal_process import terminate_terminal_process


@pytest.mark.skipif(os.name == "nt", reason="POSIX process groups")
def test_stop_escalates_ignored_term_and_preserves_replacement(tmp_path):
    marker = tmp_path / "ready"
    proc = subprocess.Popen(["/bin/sh", "-c", f"trap '' TERM; touch {marker}; while :; do sleep 1; done"], start_new_session=True)
    replacement = subprocess.Popen(["/bin/sleep", "30"], start_new_session=True)
    try:
        deadline = time.monotonic() + 3
        while not marker.exists():
            assert time.monotonic() < deadline
            time.sleep(0.01)
        terminate_terminal_process(proc)
        assert proc.returncode is not None
        assert replacement.poll() is None
    finally:
        for child in (proc, replacement):
            if child.poll() is None:
                os.killpg(child.pid, 9)
            child.wait()


@pytest.mark.parametrize("worker", [w._run_terminal_shell, w._run_terminal_command])
def test_stop_revokes_queued_start(monkeypatch, tmp_path, worker):
    run_id = "queued-test"
    run = {"slug": "test", "command": "echo unexpected", "cwd": str(tmp_path),
           "status": "queued", "process": None, "output": [],
           "lifecycle_lock": threading.RLock()}
    monkeypatch.setitem(w._terminal_runs, run_id, run)
    monkeypatch.setattr(w.subprocess, "Popen", lambda *a, **k: pytest.fail("retired start spawned"))
    assert w.stop_terminal_run("test", run_id)["status"] == "stopped"
    worker(run_id)
    assert run["status"] == "stopped"


def test_stop_failure_is_not_success(monkeypatch):
    run = {"slug": "test", "process": object(), "status": "running", "lifecycle_lock": threading.RLock()}
    monkeypatch.setitem(w._terminal_runs, "failure-test", run)
    def fail(proc):
        raise RuntimeError("unconfirmed")
    monkeypatch.setattr("spark_cli.terminal_process.terminate_terminal_process", fail)
    with pytest.raises(w.HTTPException, match="500"):
        w.stop_terminal_run("test", "failure-test")
    assert run["status"] == "running"


@pytest.mark.skipif(os.name == "nt", reason="POSIX process groups")
def test_stop_waits_for_inflight_spawn_adoption(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SHELL", "/bin/sh")
    entered, release = threading.Event(), threading.Event()
    real_popen = subprocess.Popen
    def delayed_spawn(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return real_popen(*args, **kwargs)
    run_id = "adoption-test"
    run = {"slug": "test", "command": "sleep 30", "cwd": str(tmp_path),
           "status": "queued", "process": None, "output": [],
           "lifecycle_lock": threading.RLock()}
    monkeypatch.setitem(w._terminal_runs, run_id, run)
    monkeypatch.setattr(w.subprocess, "Popen", delayed_spawn)
    worker = threading.Thread(target=w._run_terminal_command, args=(run_id,))
    worker.start()
    assert entered.wait(3)
    results = []
    stopper = threading.Thread(target=lambda: results.append(w.stop_terminal_run("test", run_id)))
    stopper.start()
    release.set()
    stopper.join(5)
    worker.join(5)
    assert not stopper.is_alive() and not worker.is_alive()
    assert results[0]["status"] == "stopped"
    assert run["exit_code"] is not None


@pytest.mark.skipif(os.name == "nt", reason="POSIX process groups")
def test_stop_rejects_callers_process_group():
    proc = subprocess.Popen(["/bin/sleep", "30"])
    try:
        with pytest.raises(RuntimeError, match="does not own"):
            terminate_terminal_process(proc)
        assert proc.poll() is None
    finally:
        proc.terminate()
        proc.wait()


@pytest.mark.skipif(os.name == "nt", reason="POSIX process groups")
def test_stop_kills_group_after_leader_exits_without_reaping(tmp_path):
    marker = tmp_path / "child"
    proc = subprocess.Popen(["/bin/sh", "-c", f"sleep 30 & echo $! > {marker}"], start_new_session=True)
    try:
        deadline = time.monotonic() + 3
        while not marker.exists():
            assert time.monotonic() < deadline
            time.sleep(0.01)
        # Leave the exited leader unreaped, preserving its group identity.
        time.sleep(0.1)
        terminate_terminal_process(proc)
        assert proc.returncode is not None
        child = int(marker.read_text())
        # A killed orphan may briefly be a zombie; it cannot execute further.
        state = subprocess.run(["ps", "-o", "stat=", "-p", str(child)], capture_output=True, text=True).stdout.strip()
        assert not state or state.startswith("Z")
    finally:
        if proc.returncode is None:
            os.killpg(proc.pid, 9)
            proc.wait()
