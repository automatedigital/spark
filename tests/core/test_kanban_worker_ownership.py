"""Real SQLite ownership/lease contracts; external process/provider boundary is fake."""

from __future__ import annotations

import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest

from core import kanban_db as kb
from spark_cli import kanban_dispatch as dispatch


def ready_task(assignee="default"):
    task = kb.create_task(title="Synthetic owned task", assignee=assignee)
    kb.patch_task(task["id"], status="ready")
    return task["id"]


def claim_task(ttl=10):
    tid = ready_task()
    token, run_id = kb.claim_ready_task(tid, profile="default", claim_ttl_seconds=ttl)
    return tid, {"claim_token": token, "run_id": run_id}


def test_heartbeat_extends_lease_and_live_worker_survives_original_ttl(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(kb, "_now", lambda: now[0])
    tid, fence = claim_task()
    kb.set_worker_pid(tid, os.getpid(), **fence)
    now[0] = 105.0
    kb.heartbeat(tid, **fence)
    assert kb.get_task(tid)["claim_expires_at"] == 115.0
    now[0] = 111.0
    assert kb.reclaim_stale_running(claim_ttl_seconds=10) == []
    assert kb.get_task(tid)["claim_token"] == fence["claim_token"]


@pytest.mark.parametrize(
    "operation", ["heartbeat", "complete", "block", "spawn_failure", "pid", "execution"]
)
def test_stale_attempt_cannot_change_replacement_or_append_events(operation):
    tid, old = claim_task()
    kb.patch_task(tid, status="ready")  # explicit human retry, not an automatic reclaim
    token, run_id = kb.claim_ready_task(tid, profile="default", claim_ttl_seconds=10)
    before = kb.get_task_detail(tid)
    events = kb.append_events_since()
    operations = {
        "heartbeat": lambda: kb.heartbeat(tid, **old),
        "complete": lambda: kb.complete_task(tid, summary="stale", **old),
        "block": lambda: kb.block_task(tid, "stale", **old),
        "spawn_failure": lambda: kb.record_spawn_failure(tid, "stale", 5, **old),
        "pid": lambda: kb.set_worker_pid(tid, 123, **old),
        "execution": lambda: kb.record_worker_execution(
            tid, execution={"session_id": "stale"}, **old
        ),
    }
    with pytest.raises(kb.WorkerClaimError):
        operations[operation]()
    assert kb.get_task_detail(tid) == before
    assert kb.append_events_since() == events
    assert kb.get_task(tid)["current_run_id"] == run_id
    assert kb.get_task(tid)["claim_token"] == token


def test_run_id_is_part_of_fence_not_just_token():
    tid, fence = claim_task()
    with pytest.raises(kb.WorkerClaimError):
        kb.complete_task(tid, claim_token=fence["claim_token"], run_id=fence["run_id"] + 1)
    assert kb.get_task(tid)["status"] == "running"


def test_two_sqlite_claimers_cannot_own_same_task():
    tid = ready_task()
    barrier = Barrier(2)

    def claim(_):
        barrier.wait()
        return kb.claim_ready_task(tid, profile="default", claim_ttl_seconds=10)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, range(2)))
    assert sum(result is not None for result in results) == 1
    assert len(kb.get_task_detail(tid)["runs"]) == 1


@pytest.mark.parametrize("state", ["missing", "dead", "ambiguous", "live"])
def test_expired_worker_outcome_is_preserved_for_review_not_redispatched(state, monkeypatch):
    tid, fence = claim_task(ttl=-1)
    if state != "missing":
        kb.set_worker_pid(tid, 1234, **fence)

    def probe(pid, signal):
        if state == "dead":
            raise ProcessLookupError()
        if state == "ambiguous":
            raise PermissionError()

    monkeypatch.setattr(os, "kill", probe)
    assert kb.reclaim_stale_running(claim_ttl_seconds=1) == [tid]
    assert kb.get_task(tid)["status"] == "blocked"
    assert kb.list_ready_for_dispatch() == []
    run = kb.get_task_detail(tid)["runs"][0]
    assert run["outcome"] == ("crashed" if state == "dead" else "uncertain")
    payload = json.loads(kb.append_events_since()[-1]["payload_json"])
    assert payload["worker_state"] == ("ambiguous" if state == "live" else state)
    assert payload["safe_to_retry"] is False


def test_known_spawn_failure_closes_its_attempt_and_remains_retryable():
    tid, fence = claim_task()
    assert (
        kb.record_spawn_failure(tid, "exec failed before process creation", 5, **fence) == "retry"
    )
    assert kb.get_task(tid)["status"] == "ready"
    assert kb.get_task_detail(tid)["runs"][0]["outcome"] == "spawn_failed"


def test_spawn_failure_cannot_rerun_acknowledged_worker():
    tid, fence = claim_task()
    kb.record_worker_execution(tid, execution={"session_id": "real-reference"}, **fence)
    with pytest.raises(kb.WorkerClaimError, match="may have started"):
        kb.record_spawn_failure(tid, "lost spawn reply", 5, **fence)
    assert kb.get_task(tid)["status"] == "running"


def test_execution_refs_survive_completion_metadata():
    tid, fence = claim_task()
    refs = {"session_id": "session-a", "root_run_id": "root-a", "node_id": "node-a"}
    kb.record_worker_execution(tid, execution=refs, **fence)
    kb.complete_task(
        tid, summary="reported", metadata={"execution": {"session_id": "invented"}}, **fence
    )
    meta = json.loads(kb.get_task_detail(tid)["runs"][0]["metadata_json"])
    assert meta["execution"] == refs
    assert kb.get_task(tid)["status"] == "user_review"


@pytest.fixture
def profile_homes(tmp_path, monkeypatch):
    root = tmp_path / "spark-root"
    board = root / "profiles" / "board"
    execution = root / "profiles" / "assignee"
    board.mkdir(parents=True)
    execution.mkdir(parents=True)
    (board / "config.yaml").write_text("model:\n  default: board-model\n  provider: ollama\n")
    (execution / "config.yaml").write_text(
        "model:\n  default: assigned-model\n  provider: ollama\n"
    )
    monkeypatch.setenv("SPARK_HOME", str(board))
    return root, board, execution


def test_two_dispatchers_spawn_one_attempt_and_leave_parent_environment_unchanged(
    profile_homes, monkeypatch
):
    _, board, execution = profile_homes
    tid = ready_task("assignee")
    calls = []

    async def spawn(*args, **kwargs):
        calls.append(kwargs["env"])
        await asyncio.sleep(0)
        return SimpleNamespace(pid=os.getpid())

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(dispatch, "_config", lambda: {})
    before = dict(os.environ)

    async def both():
        return await asyncio.gather(dispatch.run_dispatch_tick(), dispatch.run_dispatch_tick())

    results = asyncio.run(both())
    assert sum(result["claimed"] for result in results) == 1
    assert len(calls) == 1
    assert dict(os.environ) == before
    env = calls[0]
    assert env["SPARK_HOME"] == str(execution)
    assert env["SPARK_KANBAN_BOARD_HOME"] == str(board)
    assert env["SPARK_KANBAN_EXECUTION_HOME"] == str(execution)
    assert env["SPARK_KANBAN_CLAIM_TOKEN"] == kb.get_task(tid)["claim_token"]
    assert int(env["SPARK_KANBAN_RUN_ID"]) == kb.get_task(tid)["current_run_id"]


@pytest.mark.parametrize("assignee", ["../escape", "/tmp/outside", "missing", "symlink"])
def test_invalid_or_escaped_profile_never_spawns(profile_homes, monkeypatch, tmp_path, assignee):
    root, _, _ = profile_homes
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "profiles" / "symlink").symlink_to(outside, target_is_directory=True)
    tid = ready_task(assignee)

    async def forbidden(*args, **kwargs):
        pytest.fail("Invalid profile spawned")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    monkeypatch.setattr(dispatch, "_config", lambda: {})
    assert asyncio.run(dispatch.run_dispatch_tick())["claimed"] == 0
    assert kb.get_task(tid)["status"] == "blocked"
    assert not (outside / "kanban.db").exists()


def test_known_dispatch_spawn_failure_is_retryable(profile_homes, monkeypatch):
    tid = ready_task("assignee")

    async def spawn(*args, **kwargs):
        raise OSError("known exec failure")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(dispatch, "_config", lambda: {})
    asyncio.run(dispatch.run_dispatch_tick())
    assert kb.get_task(tid)["status"] == "ready"
    assert kb.get_task_detail(tid)["runs"][0]["outcome"] == "spawn_failed"


def test_fast_worker_completion_before_pid_registration_is_not_spawn_failure(
    profile_homes, monkeypatch
):
    tid = ready_task("assignee")

    async def spawn(*args, **kwargs):
        env = kwargs["env"]
        kb.complete_task(
            tid,
            summary="fast worker",
            claim_token=env["SPARK_KANBAN_CLAIM_TOKEN"],
            run_id=int(env["SPARK_KANBAN_RUN_ID"]),
        )
        return SimpleNamespace(pid=os.getpid())

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(dispatch, "_config", lambda: {})
    assert asyncio.run(dispatch.run_dispatch_tick())["claimed"] == 1
    assert kb.get_task(tid)["status"] == "user_review"
    assert kb.get_task_detail(tid)["runs"][0]["outcome"] == "completed"


def test_worker_tools_require_token_and_fence_child_writes(monkeypatch):
    from tools import kanban_tool as tools

    tid, fence = claim_task()
    monkeypatch.setenv("SPARK_KANBAN_TASK", tid)
    monkeypatch.setenv("SPARK_KANBAN_BOARD_HOME", os.environ["SPARK_HOME"])
    monkeypatch.setenv("SPARK_KANBAN_RUN_ID", str(fence["run_id"]))
    assert json.loads(tools.kanban_complete("missing fence"))["ok"] is False
    with pytest.raises(kb.WorkerClaimError):
        kb.complete_task(tid, summary="direct unfenced worker")
    monkeypatch.setenv("SPARK_KANBAN_CLAIM_TOKEN", fence["claim_token"])
    assert json.loads(tools.kanban_heartbeat())["ok"] is True
    # Release the valid attempt, then retain its now-stale worker environment.
    with kb.worker_claim(tid, fence["claim_token"], fence["run_id"]):
        kb.patch_task(tid, status="ready")
    # Retain the now-stale worker environment. No new task/comment may be created.
    before = kb.append_events_since()
    assert json.loads(tools.kanban_create_tool("stale child", "default"))["ok"] is False
    assert json.loads(tools.kanban_comment(tid, "stale note"))["ok"] is False
    assert kb.append_events_since() == before


def test_board_contexts_are_independent_without_environment_mutation(tmp_path):
    homes = [tmp_path / "board-a", tmp_path / "board-b"]
    before = dict(os.environ)

    def create(home):
        with kb.board_home(home):
            return kb.create_task(title=home.name)["id"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(create, homes))
    for home, tid in zip(homes, ids):
        with kb.board_home(home):
            assert kb.get_task(tid)["title"] == home.name
            assert kb.get_task(ids[1 - ids.index(tid)]) is None
    assert dict(os.environ) == before


# This script replaces ONLY the provider/runtime boundary. Worker startup,
# profiles/config, lease thread, Kanban tools and SQLite transactions are real.
WORKER_SCRIPT = r"""
import json, os, time
from pathlib import Path
from unittest.mock import patch
from core.spark_constants import get_spark_home
from spark_cli.config import load_config
from spark_cli import kanban_worker
mode = os.environ["KANBAN_TEST_MODE"]
class FakeAgent:
    def __init__(self, **kwargs):
        assert load_config()["model"]["default"] == "assigned-model"
        assert kwargs["model"] == "assigned-model"
        assert kwargs["provider"] == "fixture"
        assert get_spark_home() == Path(os.environ["SPARK_KANBAN_EXECUTION_HOME"])
        assert os.environ["ASSIGNED_ONLY"] == "yes"
        from spark_cli.env_loader import load_spark_dotenv
        load_spark_dotenv(spark_home=get_spark_home())  # same import-time runtime loader
        assert get_spark_home() == Path(os.environ["SPARK_KANBAN_EXECUTION_HOME"])
        assert os.environ["SPARK_KANBAN_CLAIM_TOKEN"] != "must-not-use"
        self.session_id = kwargs["session_id"]
        Path(get_spark_home(), "captured.json").write_text(json.dumps({"model":kwargs["model"],"session_id":self.session_id,"home":str(get_spark_home())}))
        if mode == "startup-failure":
            raise RuntimeError("synthetic startup failure")
    def interrupt(self):
        pass
    def run_conversation(self, *args, **kwargs):
        from tools import kanban_tool as tools
        from core import kanban_db as kb
        assert kb.kanban_db_path() == Path(os.environ["SPARK_KANBAN_BOARD_HOME"], "kanban.db")
        assert json.loads(tools.kanban_show())["ok"]
        assert json.loads(tools.kanban_comment(os.environ["SPARK_KANBAN_TASK"], "written to original board"))["ok"]
        if mode == "slow":
            time.sleep(2)
        if mode == "tool-complete":
            assert json.loads(tools.kanban_complete("reported complete", metadata={"changed_files":["synthetic.txt"],"verification":["fixture"],"verified":True}))["ok"]
        if mode == "failure-result":
            return {"final_response":"diagnostic text", "failed":True, "error":"synthetic failure"}
        return {"final_response":"Synthetic text-only result"}
import sys
from types import SimpleNamespace
with patch.dict(sys.modules, {"core.run_agent": SimpleNamespace(AIAgent=FakeAgent)}), patch("spark_cli.runtime_provider.resolve_runtime_provider", return_value={"provider":"fixture"}):
    raise SystemExit(kanban_worker.main())
"""


def worker_env(profile_homes, mode="text-only", ttl=10):
    root, board, execution = profile_homes
    (execution / ".env").write_text(
        f"ASSIGNED_ONLY=yes\nSPARK_HOME={root / 'forbidden-home'}\nSPARK_KANBAN_CLAIM_TOKEN=must-not-use\n"
    )
    tid = ready_task("assignee")
    token, run_id = kb.claim_ready_task(tid, profile="assignee", claim_ttl_seconds=ttl)
    env = {
        **os.environ,
        "SPARK_HOME": str(execution),
        "SPARK_KANBAN_TASK": tid,
        "SPARK_KANBAN_BOARD_HOME": str(board),
        "SPARK_KANBAN_EXECUTION_HOME": str(execution),
        "SPARK_KANBAN_EXECUTION_PROFILE": "assignee",
        "SPARK_KANBAN_CLAIM_TOKEN": token,
        "SPARK_KANBAN_RUN_ID": str(run_id),
        "SPARK_KANBAN_CLAIM_TTL": str(ttl),
        "KANBAN_TEST_MODE": mode,
    }
    return tid, env


@pytest.mark.allow_spawn
@pytest.mark.parametrize(
    "mode,exit_code,status",
    [
        ("text-only", 0, "user_review"),
        ("tool-complete", 0, "user_review"),
        ("startup-failure", 3, "blocked"),
        ("failure-result", 4, "blocked"),
    ],
)
def test_worker_uses_assigned_model_but_tools_write_original_board(
    profile_homes, mode, exit_code, status
):
    import subprocess
    import sys

    _, board, execution = profile_homes
    tid, env = worker_env(profile_homes, mode)
    before = dict(os.environ)
    result = subprocess.run(
        [sys.executable, "-c", WORKER_SCRIPT], env=env, capture_output=True, text=True, timeout=15
    )
    assert result.returncode == exit_code, result.stderr
    assert dict(os.environ) == before
    assert not (execution / "kanban.db").exists()
    assert not (board.parent.parent / "forbidden-home").exists()
    captured = json.loads((execution / "captured.json").read_text())
    assert captured["model"] == "assigned-model"
    assert kb.get_task(tid)["status"] == status
    detail = kb.get_task_detail(tid)
    metadata = json.loads(detail["runs"][0]["metadata_json"])
    assert metadata["execution"]["profile_home"] == str(execution)
    assert metadata["execution"]["board_home"] == str(board)
    assert metadata["execution"]["profile"] == "assignee"
    if mode != "startup-failure":
        assert metadata["execution"]["session_id"] == captured["session_id"]
        assert detail["comments"][0]["body"] == "written to original board"
    if mode in {"text-only", "tool-complete"}:
        assert metadata["verified"] is False
    if mode == "text-only":
        assert metadata["auto_closed"] is True
        assert metadata["changed_files"] == metadata["verification"] == []
        assert metadata["limitations"]
    assert "root_run_id" not in metadata["execution"]  # no invented linkage


@pytest.mark.allow_spawn
@pytest.mark.slow
def test_worker_automatic_lease_thread_renews_while_provider_is_busy(profile_homes):
    import subprocess
    import sys
    import time

    _, _, execution = profile_homes
    tid, env = worker_env(profile_homes, "slow", ttl=1)
    initial_expiry = kb.get_task(tid)["claim_expires_at"]
    proc = subprocess.Popen(
        [sys.executable, "-c", WORKER_SCRIPT],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 8
        while not (execution / "captured.json").exists():
            assert time.monotonic() < deadline
            assert proc.poll() is None
            time.sleep(0.02)
        time.sleep(1.1)
        assert proc.poll() is None
        assert kb.get_task(tid)["claim_expires_at"] > initial_expiry
        assert kb.reclaim_stale_running(claim_ttl_seconds=1) == []
        stdout, stderr = proc.communicate(timeout=10)
        assert proc.returncode == 0, stderr
        assert kb.get_task(tid)["status"] == "user_review"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()


@pytest.mark.allow_spawn
def test_worker_missing_fence_fails_before_runtime_or_profile_state_write(profile_homes):
    import subprocess
    import sys

    _, _, execution = profile_homes
    tid, env = worker_env(profile_homes)
    env.pop("SPARK_KANBAN_CLAIM_TOKEN")
    result = subprocess.run(
        [sys.executable, "-c", WORKER_SCRIPT], env=env, capture_output=True, text=True, timeout=15
    )
    assert result.returncode == 2
    assert not (execution / "captured.json").exists()
    assert not (execution / "kanban.db").exists()
    assert kb.get_task(tid)["status"] == "running"


def test_dispatch_claim_refuses_changed_assignment():
    tid = ready_task("old-profile")
    kb.patch_task(tid, assignee="new-profile")
    assert kb.claim_ready_task(tid, profile="old-profile", claim_ttl_seconds=10) is None
    assert kb.get_task(tid)["status"] == "ready"
    assert kb.get_task_detail(tid)["runs"] == []


def test_post_spawn_bookkeeping_error_does_not_release_for_retry(profile_homes, monkeypatch):
    tid = ready_task("assignee")

    async def spawn(*args, **kwargs):
        return SimpleNamespace(pid=os.getpid())

    def fail_bookkeeping(*args, **kwargs):
        raise RuntimeError("accepted worker, lost bookkeeping acknowledgement")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(dispatch, "_config", lambda: {})
    monkeypatch.setattr(kb, "set_worker_pid", fail_bookkeeping)
    with pytest.raises(RuntimeError, match="lost bookkeeping"):
        asyncio.run(dispatch.run_dispatch_tick())
    assert kb.get_task(tid)["status"] == "running"
    assert kb.get_task_detail(tid)["runs"][0]["outcome"] == "active"


def test_worker_scope_cannot_complete_another_task():
    other = ready_task("another-profile")
    tid, fence = claim_task()
    with kb.worker_claim(tid, fence["claim_token"], fence["run_id"]):
        with pytest.raises(kb.WorkerClaimError, match="owned task"):
            kb.complete_task(other, summary="must not replace another task")
    assert kb.get_task(other)["status"] == "ready"


def test_known_spawn_failure_limit_remains_blocked_with_closed_run():
    tid, fence = claim_task()
    assert kb.record_spawn_failure(tid, "exec failed", failure_limit=1, **fence) == "gave_up"
    assert kb.get_task(tid)["status"] == "blocked"
    assert kb.get_task_detail(tid)["runs"][0]["outcome"] == "spawn_failed"
    assert [event["kind"] for event in kb.append_events_since()][-2:] == ["spawn_failed", "gave_up"]


def test_worker_provider_arguments_bind_to_real_agent_interface():
    import inspect

    from core.run_agent import AIAgent
    from spark_cli.kanban_worker import _agent_runtime_kwargs

    runtime = {"provider": "acp", "command": "fixture-harness", "args": ["--stdio"],
               "api_key": "fixture", "ignored_provider_metadata": "not-a-constructor-argument"}
    kwargs = _agent_runtime_kwargs(runtime)
    # Validate against the actual consumer instead of a permissive fake's **kwargs.
    bound = inspect.signature(AIAgent).bind_partial(**kwargs)
    assert bound.arguments["acp_command"] == "fixture-harness"
    assert bound.arguments["acp_args"] == ["--stdio"]
