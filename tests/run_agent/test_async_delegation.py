"""Provider-boundary replay with real AIAgent, callbacks, receipts and SQLite."""

import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.orchestration.delegation import deliver_results_at_turn_boundary, reconcile_lost_children
from core.run_agent import AIAgent
from core.spark_state import SessionDB
from tools.delegate_tool import delegate_task


@pytest.fixture
def replay_runtime(monkeypatch):
    from tools import delegate_tool, interrupt

    # Some parents have never entered run_conversation, so interrupt() targets
    # this test's thread. Keep real interrupt behavior inside the replay without
    # leaving cancellation flags on the next test's local shell operations.
    monkeypatch.setattr(interrupt, "_interrupted_threads", set())

    monkeypatch.setattr("core.run_agent.get_tool_definitions", lambda **kw: [])
    monkeypatch.setattr("core.run_agent.check_toolset_requirements", lambda: {})
    monkeypatch.setattr("core.run_agent.OpenAI", lambda **kw: MagicMock())
    monkeypatch.setattr("agent.context_compressor.get_model_context_length", lambda *a, **kw: 128_000)
    monkeypatch.setattr(AIAgent, "_build_system_prompt", lambda *a, **kw: "fixture system")
    monkeypatch.setattr(delegate_tool, "_load_config", lambda: {"async_enabled": True, "max_iterations": 2})
    monkeypatch.setattr(delegate_tool, "_resolve_subagent_credentials", lambda *a: {
        "model": None, "provider": None, "base_url": None, "api_key": None, "api_mode": None})
    controls = {}
    captured = []
    db = SessionDB()
    parents = []

    def response(text):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=text, tool_calls=None, refusal=None), finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2, total_tokens=12), model="fixture-model",
        )

    def transport(agent, kwargs, *args, **kw):
        captured.append((agent.session_id, kwargs))
        if agent._delegate_depth:
            goal = str(kwargs["messages"][-1]["content"])
            control = controls[goal]
            control["entered"].set()
            if agent.tool_progress_callback:
                agent.tool_progress_callback("tool.started", "fixture_tool", "fixture progress")
            deadline = time.monotonic() + 8
            while not control["release"].wait(0.01):
                if agent._interrupt_requested:
                    raise InterruptedError("fixture cancellation acknowledged")
                if time.monotonic() > deadline:
                    raise AssertionError("Fixture child was not released")
            if control.get("provider_error"):
                raise RuntimeError("fixture provider failure")
            if control.get("failure"):
                raise InterruptedError("fixture stopped")
            return response("result: " + goal)
        return response("parent response")

    monkeypatch.setattr(AIAgent, "_interruptible_api_call", transport)
    monkeypatch.setattr(AIAgent, "_interruptible_streaming_api_call", transport)

    def make_parent(sid="parent", platform="cli"):
        parent = AIAgent(
            api_key="fixture", base_url="http://localhost:1/v1", model="fixture-model", provider="custom",
            max_iterations=2, quiet_mode=True, skip_context_files=True, skip_memory=True,
            enabled_toolsets=["file"], session_db=db, session_id=sid, platform=platform,
        )
        parent._root_run_id = "fixture-root-turn"
        parents.append(parent)
        return parent

    def task(goal):
        controls[goal] = {"entered": threading.Event(), "release": threading.Event()}
        return {"goal": goal}

    yield SimpleNamespace(db=db, parent=make_parent, task=task, controls=controls, captured=captured)
    for control in controls.values():
        control["release"].set()
    deadline = time.monotonic() + 8
    while any(p._active_children for p in parents) and time.monotonic() < deadline:
        time.sleep(0.01)
    for parent in parents:
        parent.close()
    db.close()


def wait_terminal(db, handle):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        run = db.get_subagent_run(handle)
        if run["status"] in {"completed", "failed", "interrupted", "uncertain"}:
            return run
        time.sleep(0.01)
    raise AssertionError(f"Child {handle} did not become terminal")


@pytest.mark.parametrize("platform", ["cli", "web", "telegram"])
def test_two_children_reverse_completion_safe_parent_boundary_and_restart(replay_runtime, platform):
    r = replay_runtime
    parent = r.parent("parent-" + platform, platform)
    r.db.upsert_web_turn_projection("fixture-root-turn", parent.session_id, {"status": "running"})
    tasks = [r.task("first"), r.task("second")]
    accepted = json.loads(delegate_task(tasks=tasks, parent_agent=parent, mode="async", request_id="dispatch-1"))
    assert accepted["status"] == "accepted"
    handles = [h["id"] for h in accepted["handles"]]
    assert all(control["entered"].wait(5) for control in r.controls.values())
    # Simulate a disconnected parent/switch away. Neither worker starts a new turn.
    r.controls["second"]["release"].set()
    assert wait_terminal(r.db, handles[1])["status"] == "completed"
    assert r.db.get_subagent_run(handles[0])["status"] not in {"completed", "failed"}
    assert r.db.get_latest_web_turn_projection(parent.session_id)["projection"]["status"] == "running"
    r.controls["first"]["release"].set()
    assert wait_terminal(r.db, handles[0])["status"] == "completed"
    retry = json.loads(delegate_task(tasks=tasks, parent_agent=parent, mode="async", request_id="dispatch-1"))
    assert retry == accepted
    assert len(r.db.list_subagent_runs(parent.session_id)) == 2
    assert r.db.get_messages(parent.session_id) == []
    # Next explicit turn uses the common boundary for CLI, web and gateway.
    outcome = parent.run_conversation("inspect completed children")
    assert outcome["final_response"] == "parent response"
    messages = r.db.get_messages(parent.session_id)
    delivered = [m for m in messages if "Delivery child-result:" in (m["content"] or "")]
    assert len(delivered) == 2
    assert "second" in delivered[0]["content"]
    assert "first" in delivered[1]["content"]
    assert parent._cached_system_prompt == "fixture system"
    parent.run_conversation("continue")
    assert len([m for m in r.db.get_messages(parent.session_id) if "Delivery child-result:" in (m["content"] or "")]) == 2
    reopened = SessionDB(r.db.db_path)
    assert reopened.deliver_async_child_results(parent.session_id) == []
    assert len(reopened.list_async_child_jobs(parent.session_id)) == 2
    reopened.close()


def test_cancel_one_child_preserves_sibling_and_duplicate_acceptance(replay_runtime):
    r = replay_runtime
    parent = r.parent()
    tasks = [r.task("cancel-me"), r.task("keep-running")]
    accepted = json.loads(delegate_task(tasks=tasks, parent_agent=parent, mode="async", request_id="dispatch"))
    handles = [h["id"] for h in accepted["handles"]]
    assert all(c["entered"].wait(5) for c in r.controls.values())
    cancel = json.loads(delegate_task(parent_agent=parent, mode="cancel", handle=handles[0], request_id="cancel-1"))
    assert cancel["status"] == "stopping"
    assert wait_terminal(r.db, handles[0])["status"] == "interrupted"
    assert json.loads(delegate_task(parent_agent=parent, mode="cancel", handle=handles[0], request_id="cancel-1")) == cancel
    assert r.db.get_subagent_run(handles[1])["status"] not in {"interrupted", "completed"}
    parent.interrupt("stop parent")
    assert wait_terminal(r.db, handles[1])["status"] == "interrupted"
    assert r.db.get_session(parent.session_id)["ended_at"] is None


def test_profile_bound_and_payload_conflict_create_no_extra_attempt(replay_runtime):
    r = replay_runtime
    p1, p2 = r.parent("one"), r.parent("two")
    accepted = json.loads(delegate_task(tasks=[r.task("a"), r.task("b")], mode="async", request_id="one", parent_agent=p1))
    assert r.controls["a"]["entered"].wait(5)
    rejected = json.loads(delegate_task(tasks=[r.task("c"), r.task("d")], mode="async", request_id="two", parent_agent=p2))
    assert "concurrent child limit" in str(rejected)
    assert len(r.db.list_subagent_runs(p2.session_id)) == 0
    mismatch = json.loads(delegate_task(goal="changed", mode="async", request_id="one", parent_agent=p1))
    assert "different payload" in str(mismatch)
    alien = json.loads(delegate_task(mode="status", handle=accepted["handles"][0]["id"], parent_agent=p2))
    assert "Owned child not found" in str(alien)


def test_lost_worker_is_uncertain_fenced_and_never_replayed(replay_runtime, monkeypatch):
    r = replay_runtime
    parent = r.parent()
    tasks = [r.task("uncertain")]
    accepted = json.loads(delegate_task(tasks=tasks, mode="async", request_id="lost", parent_agent=parent))
    handle = accepted["handles"][0]["id"]
    assert r.controls["uncertain"]["entered"].wait(5)
    monkeypatch.setattr("gateway.status._is_process_alive", lambda pid: False)
    assert reconcile_lost_children(r.db) == 1
    assert reconcile_lost_children(r.db) == 0
    assert r.db.get_subagent_run(handle)["status"] == "uncertain"
    run = r.db.get_subagent_run(handle)
    with pytest.raises(ValueError, match="no longer owns"):
        r.db.commit_subagent_lifecycle({**run, "worker_token": "stale", "status": "completed"},
                                      {"event_id": "stale-finish", "event": "completed"})
    # Even the old owner's late completion cannot replace an uncertain outcome.
    r.controls["uncertain"]["release"].set()
    deadline = time.monotonic() + 5
    while parent._active_children and time.monotonic() < deadline:
        time.sleep(0.01)
    assert r.db.get_subagent_run(handle)["status"] == "uncertain"
    assert json.loads(delegate_task(tasks=tasks, mode="async", request_id="lost", parent_agent=parent)) == accepted
    messages = []
    deliver_results_at_turn_boundary(parent, messages)
    assert len(messages) == 1 and "uncertain" in messages[0]["content"]
    assert len([sid for sid, _ in r.captured if sid != parent.session_id]) == 1


def test_feature_off_does_not_construct_or_dispatch(replay_runtime, monkeypatch):
    r = replay_runtime
    parent = r.parent()
    monkeypatch.setattr("tools.delegate_tool._load_config", lambda: {})
    result = json.loads(delegate_task(goal="disabled", mode="async", request_id="r", parent_agent=parent))
    assert "disabled" in str(result)
    assert r.db.list_async_child_jobs() == []
    assert not parent._active_children


def test_real_process_loss_after_acceptance_is_uncertain_on_restart(tmp_path):
    import os
    import subprocess
    import sys

    path = tmp_path / "restart.db"
    script = """
import os, sys
from pathlib import Path
from core.spark_state import SessionDB
from gateway.status import _get_process_start_time
db = SessionDB(Path(sys.argv[1]))
db.create_session('owner', 'cli')
run = {'id': 'lost-child', 'parent_session_id': 'owner', 'status': 'created',
       'execution_mode': 'async', 'worker_token': 'worker-1', 'attempt_id': 'attempt-1'}
db.accept_runtime_command('owner', 'subagent.dispatch', 'request-1', {'goal': 'fixture'},
                          {'handles': [{'id': 'lost-child'}]}, {'dispatch': 'lost-child'},
                          children=[{'run': run, 'task': {'goal': 'fixture'}, 'owner_pid': os.getpid(),
                                     'owner_start': str(_get_process_start_time(os.getpid()))}])
db.close()
"""
    completed = subprocess.run([sys.executable, "-c", script, str(path)], env=dict(os.environ),
                               capture_output=True, text=True, timeout=15)
    assert completed.returncode == 0, completed.stderr
    db = SessionDB(path)
    assert reconcile_lost_children(db) == 1
    assert db.get_subagent_run("lost-child")["status"] == "uncertain"
    assert db.list_async_child_jobs()[0]["state"] == "uncertain"
    assert db.get_runtime_command("owner", "subagent.dispatch", "request-1", {"goal": "fixture"})["state"] == "uncertain"
    db.close()
    db = SessionDB(path)
    assert reconcile_lost_children(db) == 0
    assert len(db.list_subagent_runs("owner")) == 1
    db.close()


def test_delivery_is_atomic_concurrent_and_follows_compression(replay_runtime):
    from concurrent.futures import ThreadPoolExecutor

    r = replay_runtime
    parent = r.parent()
    accepted = json.loads(delegate_task(tasks=[r.task("deliver")], mode="async", request_id="delivery", parent_agent=parent))
    assert r.controls["deliver"]["entered"].wait(5)
    r.controls["deliver"]["release"].set()
    wait_terminal(r.db, accepted["handles"][0]["id"])
    r.db.create_session("compressed-parent", "web", parent_session_id=parent.session_id)
    r.db._conn.execute("UPDATE sessions SET end_reason='compression' WHERE id=?", (parent.session_id,))
    r.db._conn.execute("""CREATE TRIGGER fail_delivery BEFORE INSERT ON messages
        WHEN NEW.session_id='compressed-parent' BEGIN SELECT RAISE(ABORT, 'delivery crash'); END""")
    with pytest.raises(Exception, match="delivery crash"):
        r.db.deliver_async_child_results("compressed-parent")
    assert r.db.list_async_child_jobs()[0]["delivered_message_id"] is None
    r.db._conn.execute("DROP TRIGGER fail_delivery")
    clients = [SessionDB(r.db.db_path) for _ in range(2)]
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            delivered = list(pool.map(lambda db: db.deliver_async_child_results("compressed-parent"), clients))
        assert sum(len(messages) for messages in delivered) == 1
        assert r.db.deliver_async_child_results(parent.session_id) == []
        assert len(r.db.get_messages("compressed-parent")) == 1
    finally:
        for client in clients:
            client.close()


def test_explicit_retry_has_new_attempt_and_original_receipt(replay_runtime):
    r = replay_runtime
    parent = r.parent()
    accepted = json.loads(delegate_task(tasks=[r.task("retry-me")], mode="async", request_id="source", parent_agent=parent))
    original = accepted["handles"][0]["id"]
    assert r.controls["retry-me"]["entered"].wait(5)
    delegate_task(mode="cancel", handle=original, request_id="stop", parent_agent=parent)
    assert wait_terminal(r.db, original)["status"] == "interrupted"
    retry = json.loads(delegate_task(mode="retry", handle=original, request_id="retry-1", parent_agent=parent))
    replacement = retry["handles"][0]["id"]
    assert replacement != original
    assert retry["handles"][0]["attempt_id"] != accepted["handles"][0]["attempt_id"]
    assert r.db.get_subagent_run(replacement)["retry_of"] == original
    assert json.loads(delegate_task(mode="retry", handle=original, request_id="retry-1", parent_agent=parent)) == retry
    r.controls["retry-me"]["release"].set()
    assert wait_terminal(r.db, replacement)["status"] == "completed"
    assert r.db.get_subagent_run(original)["status"] == "interrupted"


@pytest.mark.asyncio
async def test_gateway_message_transport_fixture_delivers_once_without_external_send(replay_runtime, monkeypatch):
    import asyncio

    from gateway.config import Platform
    from gateway.run import GatewayRunner
    from tests.gateway.test_session_race_guard import _make_event, _make_runner

    r = replay_runtime
    parent = r.parent("gateway-fixture", "telegram")
    accepted = json.loads(delegate_task(tasks=[r.task("gateway-child")], mode="async", request_id="gateway", parent_agent=parent))
    assert r.controls["gateway-child"]["entered"].wait(5)
    r.controls["gateway-child"]["release"].set()
    wait_terminal(r.db, accepted["handles"][0]["id"])
    runner = _make_runner()
    sends = []
    async def fake_send(*args, **kw):
        sends.append(args)
        raise AssertionError("External messaging is disabled in this fixture")
    runner.adapters[Platform.TELEGRAM].send = fake_send
    async def run_agent_boundary(self, event, source, session_key):
        result = await asyncio.to_thread(parent.run_conversation, event.text)
        return result["final_response"]
    monkeypatch.setattr(GatewayRunner, "_handle_message_with_agent", run_agent_boundary)
    assert await runner._handle_message(_make_event("next explicit message")) == "parent response"
    assert await runner._handle_message(_make_event("continue")) == "parent response"
    assert len([m for m in r.db.get_messages(parent.session_id) if "Delivery child-result:" in (m["content"] or "")]) == 1
    assert sends == []


def test_concurrent_dispatch_retry_constructs_one_child(replay_runtime):
    from concurrent.futures import ThreadPoolExecutor

    r = replay_runtime
    parent = r.parent()
    tasks = [r.task("concurrent")]
    def dispatch(_):
        return json.loads(delegate_task(tasks=tasks, mode="async", request_id="same", parent_agent=parent))
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(dispatch, range(4)))
    assert all(result == results[0] for result in results)
    assert r.controls["concurrent"]["entered"].wait(5)
    assert len(parent._active_children) == 1
    assert len(r.db.list_async_child_jobs()) == 1
    r.controls["concurrent"]["release"].set()
    wait_terminal(r.db, results[0]["handles"][0]["id"])


def test_setup_failure_is_stored_without_completing_parent(replay_runtime, monkeypatch):
    r = replay_runtime
    parent = r.parent()
    def fail_setup(**kw):
        raise ValueError("fixture setup failure")
    monkeypatch.setattr("tools.delegate_tool._build_child_agent", fail_setup)
    accepted = json.loads(delegate_task(tasks=[r.task("setup")], mode="async", request_id="setup", parent_agent=parent))
    handle = accepted["handles"][0]["id"]
    assert r.db.get_subagent_run(handle)["status"] == "failed"
    assert "fixture setup failure" in r.db.get_subagent_run(handle)["error"]
    assert r.db.get_session(parent.session_id)["ended_at"] is None
    assert r.captured == []


def test_busy_and_stopped_parent_keep_cached_prefix_and_deliver_on_explicit_resume(replay_runtime):
    import copy

    r = replay_runtime
    parent = r.parent()
    parent.run_conversation("baseline turn")
    prefix = copy.deepcopy(parent._session_messages)
    system = parent._cached_system_prompt
    accepted = json.loads(delegate_task(tasks=[r.task("later")], mode="async", request_id="later", parent_agent=parent))
    handle = accepted["handles"][0]["id"]
    assert r.controls["later"]["entered"].wait(5)
    # A busy parent's next model call sees only the state available at its boundary.
    parent.run_conversation("busy before completion")
    assert len([m for m in r.db.get_messages(parent.session_id) if "Delivery child-result:" in (m["content"] or "")]) == 0
    parent.interrupt("stop")
    assert wait_terminal(r.db, handle)["status"] == "interrupted"
    assert parent._session_messages[:len(prefix)] == prefix
    assert parent._cached_system_prompt == system
    # No synthetic root run starts while stopped/idle.
    assert r.db.list_async_child_jobs()[0]["delivered_message_id"] is None
    parent.run_conversation("explicit resume")
    assert len([m for m in r.db.get_messages(parent.session_id) if "Delivery child-result:" in (m["content"] or "")]) == 1
    assert parent._session_messages[:len(prefix)] == prefix
    assert parent._cached_system_prompt == system


def test_cancel_before_worker_start_survives_parent_resume(replay_runtime, monkeypatch):
    r = replay_runtime
    parent = r.parent()
    queued = []
    runtime = SimpleNamespace(submit_named=lambda *args: queued.append(args))
    monkeypatch.setattr("core.async_runtime.get_async_runtime", lambda: runtime)
    accepted = json.loads(delegate_task(tasks=[r.task("queued")], mode="async", request_id="queued", parent_agent=parent))
    handle = accepted["handles"][0]["id"]
    parent.interrupt("stop queued children")
    parent.clear_interrupt()
    # A newly resumed parent must not erase its already accepted child's Stop.
    pool, limit, worker, *args = queued[0]
    worker(*args)
    assert r.db.get_subagent_run(handle)["status"] == "interrupted"
    assert r.captured == []


def test_composite_child_toolsets_cannot_reenable_blocked_tools(replay_runtime, monkeypatch):
    from core.model_tools import get_tool_definitions
    from tools.delegate_tool import DELEGATE_BLOCKED_TOOLS

    r = replay_runtime
    parent = r.parent()
    parent.enabled_toolsets = ["spark-cli"]
    monkeypatch.setattr("core.run_agent.get_tool_definitions", get_tool_definitions)
    accepted = json.loads(delegate_task(tasks=[r.task("permissions")], mode="async", request_id="permissions", parent_agent=parent))
    assert r.controls["permissions"]["entered"].wait(5)
    child = parent._active_children[0]
    assert not (child.valid_tool_names & DELEGATE_BLOCKED_TOOLS)
    child._assert_tool_surface_stable()
    blocked = json.loads(child._invoke_tool("memory", {"action": "add", "content": "blocked"}, "fixture"))
    assert "blocked" in blocked["error"]
    r.controls["permissions"]["release"].set()
    assert wait_terminal(r.db, accepted["handles"][0]["id"])["status"] == "completed"


def test_provider_failure_stays_child_failure_and_does_not_finish_root(replay_runtime, monkeypatch):
    r = replay_runtime
    parent = r.parent()
    r.db.upsert_web_turn_projection("fixture-root-turn", parent.session_id, {"status": "running"})
    tasks = [r.task("provider-failure")]
    r.controls["provider-failure"]["provider_error"] = True
    r.controls["provider-failure"]["release"].set()
    monkeypatch.setattr("core.run_agent.turn_loop.jittered_backoff", lambda *a, **kw: 0)
    accepted = json.loads(delegate_task(tasks=tasks, mode="async", request_id="provider-failure", parent_agent=parent))
    handle = accepted["handles"][0]["id"]
    assert wait_terminal(r.db, handle)["status"] == "failed"
    assert r.db.get_latest_web_turn_projection(parent.session_id)["projection"]["status"] == "running"
    assert r.db.list_async_child_jobs()[0]["result"]["status"] == "failed"


def test_explicit_child_working_dir_controls_prompt_and_relative_tools(replay_runtime, tmp_path, monkeypatch):
    from tools.delegate_tool import _build_child_agent

    r = replay_runtime
    parent = r.parent()
    inherited = tmp_path / "parent"
    isolated = tmp_path / "child"
    inherited.mkdir()
    isolated.mkdir()
    monkeypatch.setenv("TERMINAL_CWD", str(inherited))
    child = _build_child_agent(0, "path fixture", None, ["file"], None, 2, parent,
                               working_dir=str(isolated))
    try:
        assert child.working_dir == str(isolated)
        assert str(isolated) in child.ephemeral_system_prompt
        assert str(inherited) not in child.ephemeral_system_prompt
        assert child._inject_working_dir("terminal", {"command": "pwd"})["workdir"] == str(isolated)
    finally:
        parent._active_children.remove(child)
        child.close()


def _worktree_fixture_repository(tmp_path):
    import subprocess
    repo = tmp_path / "parent-project"
    repo.mkdir()
    for args in (["init", "-q"], ["config", "user.name", "Fixture"],
                 ["config", "user.email", "fixture@example.invalid"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    (repo / "same.txt").write_text("baseline")
    subprocess.run(["git", "-C", str(repo), "add", "same.txt"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "baseline"], check=True, capture_output=True)
    (repo / "same.txt").write_text("parent unsaved changes")
    return repo


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_delegated_children_use_explicit_worktrees_and_preserve_parent(replay_runtime, tmp_path, monkeypatch, mode):
    from pathlib import Path
    from tools.subagent_worktree import get_subagent_worktree

    r = replay_runtime
    parent = r.parent("isolated-" + mode)
    repo = _worktree_fixture_repository(tmp_path)
    parent.working_dir = str(repo)
    monkeypatch.setenv("TERMINAL_ENV", "local")
    monkeypatch.setenv("TERMINAL_CWD", str(repo))
    original_transport = AIAgent._interruptible_api_call
    observed = []
    def transport(agent, kwargs, *args, **kw):
        if agent._delegate_depth:
            path = Path(agent.working_dir)
            assert path != repo
            assert (path / "same.txt").read_text() == "baseline"
            assert str(path) in agent.ephemeral_system_prompt
            from tools.file_tools import write_file_tool
            args = agent._inject_working_dir("write_file", {"path": "same.txt", "content": agent.session_id})
            result = json.loads(write_file_tool(**args, task_id=agent.session_id))
            assert "error" not in result
            observed.append(path)
        return original_transport(agent, kwargs, *args, **kw)
    monkeypatch.setattr(AIAgent, "_interruptible_api_call", transport)
    monkeypatch.setattr(AIAgent, "_interruptible_streaming_api_call", transport)
    tasks = [r.task("isolate first"), r.task("isolate second")]
    for control in r.controls.values():
        control["release"].set()
    accepted = json.loads(delegate_task(tasks=tasks, parent_agent=parent, mode=mode,
                                      request_id="isolated-request", isolation="worktree"))
    if mode == "async":
        for handle in accepted["handles"]:
            assert wait_terminal(r.db, handle["id"])["status"] == "completed"
    else:
        assert all(result["status"] == "completed" for result in accepted["results"])
    deadline = time.monotonic() + 5
    runs = r.db.list_subagent_runs(parent.session_id)
    while any(get_subagent_worktree(run["id"]).active for run in runs) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(observed) == 2
    assert observed[0] != observed[1]
    assert (repo / "same.txt").read_text() == "parent unsaved changes"
    for run in runs:
        record = get_subagent_worktree(run["id"])
        assert record.active is False
        assert run["worktree"]["path"] == record.path
        assert (Path(record.path) / "same.txt").read_text() == run["child_session_id"]


def test_requested_remote_worktree_isolation_never_runs_in_shared_directory(replay_runtime, tmp_path, monkeypatch):
    r = replay_runtime
    parent = r.parent("remote-isolation")
    parent.working_dir = str(_worktree_fixture_repository(tmp_path))
    monkeypatch.setenv("TERMINAL_ENV", "ssh")
    task = r.task("must not run")
    result = json.loads(delegate_task(tasks=[task], parent_agent=parent, isolation="worktree"))
    assert "unsupported" in result["error"].lower()
    assert not r.controls["must not run"]["entered"].is_set()
    assert not parent._active_children
