"""Functional local rollout acceptance. Run with root venv and checkout PYTHONPATH.

All persistent writes and server state live under the required, new --output path.
Reuses the provider-boundary replay fixture; no provider request or external send.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


def replay(repo):
    import pytest

    spec = importlib.util.spec_from_file_location(
        "rollout_replay", repo / "tests/run_agent/test_async_delegation.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from tools.delegate_tool import _load_config

    monkey = pytest.MonkeyPatch()
    fixture = module.replay_runtime.__wrapped__(monkey)
    runtime = next(fixture)
    # Use the actual profile config loader, rather than fixture feature defaults.
    monkey.setattr("tools.delegate_tool._load_config", _load_config)
    return module, monkey, fixture, runtime


def flags(home, enabled):
    (home / "config.yaml").write_text(
        f"_config_version: 29\ndelegation:\n  async_enabled: {str(enabled).lower()}\n"
        f"  worktree_isolation: {str(enabled).lower()}\n  max_iterations: 2\n"
    )


def serve(repo, output, home, phase):
    # Real HTTP serving of tracked production bundle; no browser/timing claim.
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    url = f"http://127.0.0.1:{port}"
    assets = {}
    with (output / f"server-{phase}.log").open("w") as log:
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "spark_cli.web_server:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            stdout=log,
            stderr=log,
        )
        try:
            for _ in range(150):
                try:
                    html = urllib.request.urlopen(url, timeout=1).read()
                    break
                except OSError:
                    assert server.poll() is None, (output / f"server-{phase}.log").read_text()
                    time.sleep(0.1)
            else:
                raise AssertionError("Local staging server did not start")
            for path in re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html.decode()):
                data = urllib.request.urlopen(url + path, timeout=5).read()
                assert data == (repo / "src/spark_cli/web_dist" / path.lstrip("/")).read_bytes()
                assets[path] = hashlib.sha256(data).hexdigest()
            assert assets
            status = json.load(urllib.request.urlopen(url + "/api/status", timeout=5))
            assert str(home) in json.dumps(status), status
        finally:
            server.terminate()
            server.wait(timeout=20)
    return {"url": url, "assets": assets, "status_home_verified": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--lost-worker", action="store_true")
    parser.add_argument("--disabled-check", action="store_true")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[3]
    output = args.output.resolve()
    if not args.lost_worker and not args.disabled_check:
        output.mkdir(parents=True, exist_ok=False)
    home = output / "profile"
    home.mkdir(exist_ok=True)
    os.environ["SPARK_HOME"] = str(home)
    os.environ["TERMINAL_ENV"] = "local"
    from core.orchestration.delegation import reconcile_lost_children
    from core.spark_state import SessionDB
    from tools.delegate_tool import delegate_task

    if args.lost_worker:
        module, monkey, fixture, r = replay(repo)
        parent = r.parent("lost-owner", "web")
        accepted = json.loads(
            delegate_task(
                tasks=[r.task("process loss")], mode="async", request_id="lost", parent_agent=parent
            )
        )
        assert r.controls["process loss"]["entered"].wait(5), accepted
        (output / "lost.json").write_text(json.dumps(accepted))
        os._exit(0)  # Actual owner loss while real worker is inside synthetic SDK call.
    if args.disabled_check:
        module, monkey, fixture, r = replay(repo)
        try:
            before_count = len(r.db.list_async_child_jobs())
            denied = json.loads(
                delegate_task(
                    goal="must never execute",
                    mode="async",
                    request_id="disabled",
                    parent_agent=r.parent("disabled-owner"),
                )
            )
            assert "disabled" in denied.get("error", "").lower(), denied
            assert r.captured == []
            assert len(r.db.list_async_child_jobs()) == before_count
            (output / "disabled.json").write_text(json.dumps(denied))
        finally:
            try:
                next(fixture)
            except StopIteration:
                pass
            monkey.undo()
        return
    flags(home, True)
    module, monkey, fixture, r = replay(repo)
    try:
        parent = r.parent("rollout-owner", "web")
        task = r.task("completed before rollback")
        accepted = json.loads(
            delegate_task(tasks=[task], mode="async", request_id="completed", parent_agent=parent)
        )
        handle = accepted["handles"][0]["id"]
        assert r.controls[task["goal"]]["entered"].wait(5)
        r.controls[task["goal"]]["release"].set()
        assert module.wait_terminal(r.db, handle)["status"] == "completed"
        deadline = time.monotonic() + 8
        while parent._active_children and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not parent._active_children
        # Existing real worktree fixture verifies separate checkouts and retained dirty work.
        module.test_delegated_children_use_explicit_worktrees_and_preserve_parent(
            r, output, monkey, "async"
        )
        completed_calls = len(r.captured)
    finally:
        try:
            next(fixture)
        except StopIteration:
            pass
        monkey.undo()
    enabled_server = serve(repo, output, home, "enabled")
    subprocess.run(
        [sys.executable, __file__, "--output", str(output), "--lost-worker"], check=True, timeout=30
    )
    flags(home, False)
    db = SessionDB()
    lost = json.loads((output / "lost.json").read_text())["handles"][0]["id"]
    assert reconcile_lost_children(db) == 1
    assert db.get_subagent_run(lost)["status"] == "uncertain"
    assert db.get_subagent_run(handle)["status"] == "completed"
    db.append_message("rollout-owner", "user", "Schema-compatible rollback read/write probe")
    before = db.list_async_child_jobs()
    db.close()
    db = SessionDB()
    assert reconcile_lost_children(db) == 0
    assert db.list_async_child_jobs() == before
    assert (
        db.get_messages("rollout-owner")[-1]["content"]
        == "Schema-compatible rollback read/write probe"
    )
    db.close()
    subprocess.run(
        [sys.executable, __file__, "--output", str(output), "--disabled-check"],
        check=True,
        timeout=30,
    )
    rollback_server = serve(repo, output, home, "rollback")
    assert rollback_server["assets"] == enabled_server["assets"]
    db = SessionDB()
    assert db.list_async_child_jobs() == before
    assert db.get_subagent_run(lost)["status"] == "uncertain"
    assert db.get_subagent_run(handle)["status"] == "completed"
    report = {
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "platform": platform.platform(),
        "python": sys.version,
        "spark_home": str(home),
        "local_test_instances": {"enabled": enabled_server, "rollback": rollback_server},
        "served_assets_sha256": rollback_server["assets"],
        "schema_version": db._conn.execute("SELECT version FROM schema_version").fetchone()[0],
        "config_version": 29,
        "enabled_flags": {"async_enabled": True, "worktree_isolation": True},
        "rollback_flags": {"async_enabled": False, "worktree_isolation": False},
        "completed_handle": handle,
        "uncertain_handle": lost,
        "completed_transport_calls": completed_calls,
        "attempts": [{"id": j["id"], "state": j["state"]} for j in db.list_async_child_jobs()],
        "checks": [
            "real AIAgent dispatch and worker drain",
            "two real isolated Git child worktrees preserve parent and dirty child work",
            "actual process exit during synthetic SDK call",
            "fresh reopen reconciles once to uncertain",
            "disabled dispatch makes zero SDK calls",
            "completed and uncertain attempts survive server restart without replay",
            "loopback HTTP serves exact tracked hashed assets and isolated status home",
        ],
        "limits": [
            "SDK boundary synthetic; no external provider or send",
            "HTTP functional check, not browser or latency acceptance",
            "current schema-compatible source app only; old datastore compatibility recorded separately",
            "no installed macOS or Windows environment tested",
            "no external staging, production, publishing or user-state writes",
        ],
    }
    db.close()
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
