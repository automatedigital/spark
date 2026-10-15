"""P09 HTTP-boundary replays. Never replace the agent, delegate, DB or callbacks.

Only HTTP I/O is substituted; SDK serialization/parsing, real file tools, child
workers, receipts, lifecycle callbacks, SQLite and web fanout remain production
code. Event gates order external responses without sleep-based race assertions.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
import yaml

from core.orchestration.delegation import reconcile_lost_children
from core.run_agent import AIAgent
from core.spark_state import SessionDB
from spark_cli.sidebar_metadata import SettleBlocked, SidebarMetadata
from tools.delegate_tool import DELEGATE_BLOCKED_TOOLS, delegate_task

FIXTURE = Path(__file__).parents[1] / "fixtures/app_upgrade/replay/transport-v1.json"
pytestmark = pytest.mark.serial


def eventually(predicate, description):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        threading.Event().wait(0.01)
    raise AssertionError(f"Timed out waiting for {description}")


class Gate:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()

    def wait(self):
        self.entered.set()
        assert self.release.wait(8), "HTTP fixture gate was never released"


class HTTPReplay:
    """Script at HTTPTransport.handle_request, below the unmodified OpenAI SDK."""

    def __init__(self, script, directory):
        self.script = script
        self.path = directory / "input.txt"
        self.path.write_text(script["file_content"])
        self.calls = []
        self.lock = threading.Lock()
        self.root = Gate()
        self.children = {goal: Gate() for goal in script["children"]}
        self.errors = set()
        self.transports = {}
        self.decide = False
        self.reject_stream = False

    def response(self, request, message, reason="stop"):
        body = {
            "id": "synthetic-response", "object": "chat.completion", "created": 1,
            "model": self.script["model"],
            "choices": [{"index": 0, "message": {"role": "assistant", **message},
                         "finish_reason": reason}],
            "usage": {"prompt_tokens": 80, "completion_tokens": 12, "total_tokens": 92},
        }
        if json.loads(request.content).get("stream"):
            delta = dict(message)
            if delta.get("tool_calls"):
                delta["tool_calls"] = [{"index": i, **tc} for i, tc in enumerate(delta["tool_calls"])]
            chunk = {**body, "object": "chat.completion.chunk", "choices": [
                {"index": 0, "delta": {"role": "assistant", **delta}, "finish_reason": None}]}
            end = {**body, "object": "chat.completion.chunk", "choices": [
                {"index": 0, "delta": {}, "finish_reason": reason}]}
            data = "".join("data: " + json.dumps(x) + "\n\n" for x in (chunk, end))
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=(data + "data: [DONE]\n\n").encode(), request=request)
        return httpx.Response(200, json=body, request=request)

    @staticmethod
    def tool(name, arguments, call_id):
        return {"content": None, "tool_calls": [{"id": call_id, "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)}}]}

    def handle(self, request):
        # Catch accidental auxiliary/provider/network calls too; no real socket.
        assert request.url.host == "provider-replay.invalid", str(request.url)
        assert request.url.path == "/v1/chat/completions", str(request.url)
        body = json.loads(request.content)
        with self.lock:
            self.calls.append(copy.deepcopy(body))
        if self.reject_stream and body.get("stream"):
            return httpx.Response(400, json={"error": {"message": "stream is not supported",
                                  "type": "invalid_request_error"}}, request=request)
        users = [m["content"] for m in body["messages"] if m["role"] == "user"]
        first = users[0]
        if first in self.children:
            goal = first
            if body["messages"][-1]["role"] != "tool":
                return self.response(request, self.tool("read_file", {"path": str(self.path)}, "read-1"), "tool_calls")
            assert self.script["file_content"].strip() in body["messages"][-1]["content"]
            self.children[goal].wait()
            if goal in self.errors:
                error = self.script["provider_error"]
                return httpx.Response(error["status"], json=error["body"], request=request)
            return self.response(request, {"content": self.script["children"][goal]})
        if users[-1] == self.script["root_prompt"] and body["messages"][-1]["role"] != "tool":
            return self.response(request, self.tool("delegate_task", self.script["dispatch"], "dispatch-1"), "tool_calls")
        if body["messages"][-1]["role"] == "tool":
            if body["messages"][-1]["tool_call_id"] == "dispatch-1":
                self.root.wait()
                if self.decide:
                    return self.response(request, self.tool("clarify", {
                        "question": "Synthetic decision?", "choices": ["Continue", "Wait"]}, "decision-1"), "tool_calls")
        return self.response(request, {"content": self.script["root_result"]})

    def release_all(self):
        self.root.release.set()
        for gate in self.children.values():
            gate.release.set()


class RuntimeReplay:
    def __init__(self, script, wire, db, loop, web):
        self.script, self.wire, self.db, self.loop, self.web = script, wire, db, loop, web
        self.parents = []
        self.executor = ThreadPoolExecutor(max_workers=3)
        self.futures = []
        self.events = []
        self.callbacks = {}
        self.transport_lock = threading.Lock()

    def parent(self, sid="replay-parent", *, web=True):
        callbacks = {}
        if web:
            c = self.web._make_web_chat_callbacks(sid, asyncio.Queue(), self.loop)
            callback = c[6]
            self.callbacks[sid] = callback

            def record(event):
                with self.transport_lock:
                    self.events.append(copy.deepcopy(event))
                callback(event)

            callbacks = {"subagent_event_callback": record, "tool_start_callback": c[1],
                         "tool_complete_callback": c[2], "session_migrated_callback": c[5]}
        parent = AIAgent(
            api_key="synthetic-no-credentials", base_url=self.script["origin"],
            model=self.script["model"], provider="custom", api_mode="chat_completions",
            max_iterations=5, quiet_mode=True, skip_context_files=True, skip_memory=True,
            enabled_toolsets=["file", "delegation", "clarify"], working_dir=str(self.wire.path.parent),
            session_db=self.db, session_id=sid, platform="web" if web else "cli", **callbacks,
        )
        parent._root_run_id = "root-" + sid
        parent._execution_node_id = "node-" + sid
        self.db.upsert_web_turn_projection(parent._root_run_id, sid, {"status": "running", "turn_active": True})
        self.parents.append(parent)
        return parent

    def start_root(self, parent):
        future = self.executor.submit(parent.run_conversation, self.script["root_prompt"])
        self.futures.append(future)
        assert self.wire.root.entered.wait(8), future.exception() if future.done() else "root HTTP gate missing"
        assert all(g.entered.wait(8) for g in self.wire.children.values())
        return future

    def runs(self, parent):
        return {r["task"]: r for r in self.db.list_subagent_runs(parent.session_id)}

    def terminal(self, run, status="completed"):
        return eventually(lambda: (r if (r := self.db.get_subagent_run(run["id"]))["status"] == status else None),
                          f"{run['id']} {status}")

    def drain(self):
        self.loop.run_until_complete(asyncio.sleep(0))


@pytest.fixture
def replay(monkeypatch, tmp_path, request):
    from spark_cli import web_server as web

    script = json.loads(FIXTURE.read_text())
    assert script["schema"] == "spark.test.provider-transport-replay.v1"
    home = Path(os.environ["SPARK_HOME"])
    # Real file/config boundary. No config, prompt, tools or model resolution mocks.
    config = {
        "model": {"context_length": 128000}, "compression": {"enabled": False},
        "delegation": {"async_enabled": True, "max_iterations": 4, "max_concurrent_children": 3},
        "memory": {"memory_enabled": False, "user_profile_enabled": False},
        "agent": {"tool_use_enforcement": False},
        "auxiliary": {"compression": {"provider": "custom", "base_url": script["origin"],
                      "api_key": "synthetic-no-credentials", "model": script["model"]}},
    }
    config["compression"].update(getattr(request, "param", {}))
    (home / "config.yaml").write_text(yaml.safe_dump(config))
    wire = HTTPReplay(script, tmp_path)
    def handle(transport, request):
        body = json.loads(request.content)
        users = [m["content"] for m in body["messages"] if m["role"] == "user"]
        if users[0] in wire.children and body["messages"][-1]["role"] == "tool":
            wire.transports[users[0]] = transport
        return wire.handle(request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)
    loop = asyncio.new_event_loop()
    monkeypatch.setattr(web, "_web_event_loop", loop)
    monkeypatch.setattr(web, "_event_subscribers", set())
    monkeypatch.setattr(web, "_web_active_turns", {})
    monkeypatch.setattr(web, "_web_turn_aliases", {})
    monkeypatch.setattr(web, "_pending_token_events", {})
    monkeypatch.setattr(web, "_pending_token_gap_sessions", set())
    monkeypatch.setattr(web, "_token_flush_scheduled", False)
    monkeypatch.setattr(web, "_web_input_queues", {})
    db = SessionDB(home / "state.db")
    runtime = RuntimeReplay(script, wire, db, loop, web)
    try:
        yield runtime
    finally:
        for queue in web._web_input_queues.values():
            if queue.empty():
                queue.put_nowait(web._WEB_INPUT_CANCELLED)
        wire.release_all()
        runtime.executor.shutdown(wait=True)
        eventually(lambda: all(not p._active_children for p in runtime.parents), "child worker cleanup")
        runtime.drain()
        for parent in runtime.parents:
            parent.close()
        db.close()
        loop.close()


@pytest.mark.parametrize("order", [("alpha", "beta"), ("beta", "alpha")])
@pytest.mark.parametrize("streaming", [False, True])
def test_two_http_children_finish_in_either_order_while_real_root_stays_busy(replay, order, streaming):
    r = replay
    parent = r.parent()
    # Exercise both existing transport modes; this is provider capability state,
    # not a substituted transport/agent method. Children still negotiate normally.
    parent._disable_streaming = not streaming
    if streaming:
        # Public consumer enables the actual SDK SSE parsing path for the root.
        parent.stream_delta_callback = lambda text: None
    root = r.start_root(parent)
    runs = r.runs(parent)
    prefix = copy.deepcopy(r.wire.calls[0]["messages"])
    system, tools = parent._cached_system_prompt, copy.deepcopy(parent.tools)
    for name in order:
        goal = "REPLAY: " + name
        r.wire.children[goal].release.set()
        run = r.terminal(runs[goal])
        assert run["root_run_id"] == parent._root_run_id
        assert run["parent_node_id"] == parent._execution_node_id
        assert run["attempt_id"] and run["node_id"]
        assert not root.done()
        assert r.db.get_latest_web_turn_projection(parent.session_id)["projection"]["status"] == "running"
        assert r.db.get_session(parent.session_id)["ended_at"] is None
    assert all(j["delivered_message_id"] is None for j in r.db.list_async_child_jobs())
    assert parent._cached_system_prompt == system and parent.tools == tools
    assert any(not call.get("stream") for call in r.wire.calls) == (not streaming)
    # SDK tool serialization and real read_file callbacks were exercised.
    for run in runs.values():
        events = r.db.get_subagent_events(run["id"])
        assert {"started", "tool_started", "tool_completed", "completed"} <= {e["event_type"] for e in events}
        assert not (set(run["blocked_tools"]) - DELEGATE_BLOCKED_TOOLS)
    r.wire.root.release.set()
    assert root.result(8)["final_response"] == r.script["root_result"]
    assert r.wire.calls[0]["messages"] == prefix
    parent.run_conversation("REPLAY: explicit follow-up")
    messages = r.db.get_messages(parent.session_id)
    deliveries = [m for m in messages if "Delivery child-result:" in (m["content"] or "")]
    assert len(deliveries) == 2
    assert r.script["children"]["REPLAY: " + order[0]] in deliveries[0]["content"]
    parent.run_conversation("REPLAY: second follow-up")
    assert len([m for m in r.db.get_messages(parent.session_id) if "Delivery child-result:" in (m["content"] or "")]) == 2
    assert parent._cached_system_prompt == system and parent.tools == tools


def test_http_dispatch_response_loss_retry_and_two_clients_return_original_acceptance(replay):
    r = replay
    parent = r.parent()
    root = r.start_root(parent)
    original = next(m for m in r.wire.calls if m["messages"][-1]["role"] == "tool"
                    and m["messages"][-1]["tool_call_id"] == "dispatch-1")
    acceptance = json.loads(original["messages"][-1]["content"])
    # Caller loses acceptance, then two clients retry the same command. No new SDK request.
    with ThreadPoolExecutor(max_workers=2) as clients:
        retries = list(clients.map(lambda _: json.loads(delegate_task(parent_agent=parent, **r.script["dispatch"])), range(2)))
    assert retries == [acceptance, acceptance]
    assert len(r.db.list_async_child_jobs()) == 2
    conflict = json.loads(delegate_task(parent_agent=parent, mode="async", goal="changed",
                                      request_id=r.script["dispatch"]["request_id"]))
    assert "different payload" in conflict["error"]
    assert len(r.runs(parent)) == 2
    r.wire.release_all()
    assert root.result(8)["completed"]


def test_duplicate_and_delayed_real_web_callbacks_do_not_regress_or_duplicate(replay):
    r = replay
    parent = r.parent()
    subscriber = asyncio.Queue()
    r.web._event_subscribers.add(subscriber)
    root = r.start_root(parent)
    runs = r.runs(parent)
    r.wire.children["REPLAY: alpha"].release.set()
    terminal = r.terminal(runs["REPLAY: alpha"])
    callback = r.callbacks[parent.session_id]
    captured = [e for e in r.events if e["run_id"] == terminal["id"]]
    completed = next(e for e in captured if e["event"] == "completed")
    started = next(e for e in captured if e["event"] == "started")
    before = len(r.db.get_subagent_events(terminal["id"]))
    callback(copy.deepcopy(completed))
    callback(copy.deepcopy(started))
    assert len(r.db.get_subagent_events(terminal["id"])) == before
    # A previously unseen delayed progress delivery may be logged, but its
    # committed projection and published snapshot must retain the terminal state.
    delayed = {**copy.deepcopy(started), "event_id": "synthetic-late-start"}
    callback(delayed)
    assert r.db.get_subagent_run(terminal["id"])["status"] == "completed"
    r.drain()
    envelopes = []
    while not subscriber.empty():
        envelopes.append(subscriber.get_nowait())
    child_events = [e for e in envelopes if e["topic"].startswith("chat.subagent.")
                    and e["data"].get("id") == terminal["id"]]
    assert sum(e["topic"] == "chat.subagent.completed" for e in child_events) == 1
    assert child_events[-1]["data"]["subagent"]["status"] == "completed"
    assert all(e["sequence"] > 0 and e["server_epoch"] for e in child_events)
    durable = [e for e in r.db.get_session_events(parent.session_id)
               if e["payload"].get("subagent_run", {}).get("id") == terminal["id"]]
    assert len(durable) == before + 1
    assert len({e["payload"]["event_id"] for e in durable}) == len(durable)
    assert [e["sequence"] for e in durable] == sorted({e["sequence"] for e in durable})
    assert not root.done()
    reopened = SessionDB(r.db.db_path)
    try:
        assert reopened.get_subagent_run(terminal["id"])["status"] == "completed"
        assert len(reopened.get_subagent_events(terminal["id"])) == before + 1
        assert [e for e in reopened.get_session_events(parent.session_id)
                if e["payload"].get("subagent_run", {}).get("id") == terminal["id"]] == durable
    finally:
        reopened.close()


def test_cancel_receipt_precedes_terminal_transport_ack_and_leaves_sibling_running(replay, monkeypatch):
    r = replay
    parent = r.parent()
    root = r.start_root(parent)
    runs = r.runs(parent)
    goal = "REPLAY: alpha"
    closing = Gate()
    real_close = httpx.HTTPTransport.close

    def close(transport):
        if transport is r.wire.transports[goal]:
            closing.wait()
        real_close(transport)

    monkeypatch.setattr(httpx.HTTPTransport, "close", close)
    try:
        ack = json.loads(delegate_task(parent_agent=parent, mode="cancel", handle=runs[goal]["id"], request_id="stop-1"))
        assert ack["status"] == "stopping"
        # Hold external HTTP close acknowledgement, not a runtime/callback method.
        assert closing.entered.wait(5)
        assert r.db.get_subagent_run(runs[goal]["id"])["status"] == "stopping"
        assert r.db.list_async_child_jobs()[0]["result"] is None
        assert r.db.get_subagent_run(runs["REPLAY: beta"]["id"])["status"] == "running"
        assert not root.done()
        assert json.loads(delegate_task(parent_agent=parent, mode="cancel", handle=runs[goal]["id"], request_id="stop-1")) == ack
    finally:
        closing.release.set()
    r.terminal(runs[goal], "interrupted")
    # Releasing the old blocked HTTP response cannot change the terminal result.
    r.wire.children[goal].release.set()
    r.wire.children["REPLAY: beta"].release.set()
    r.terminal(runs["REPLAY: beta"])
    assert r.db.get_subagent_run(runs[goal]["id"])["status"] == "interrupted"
    assert not root.done()


def test_external_http_provider_error_is_child_failure_without_root_completion(replay):
    r = replay
    r.wire.errors.add("REPLAY: alpha")
    parent = r.parent()
    root = r.start_root(parent)
    runs = r.runs(parent)
    r.wire.children["REPLAY: alpha"].release.set()
    failed = r.terminal(runs["REPLAY: alpha"], "failed")
    assert "Synthetic provider rejected" in str(failed)
    assert r.db.get_latest_web_turn_projection(parent.session_id)["projection"]["status"] == "running"
    assert r.db.get_subagent_run(runs["REPLAY: beta"]["id"])["status"] == "running"
    assert not root.done()
    job = next(j for j in r.db.list_async_child_jobs() if j["id"] == failed["id"])
    assert job["result"]["status"] == "failed" and job["delivered_message_id"] is None


def test_actual_process_loss_after_http_dispatch_is_uncertain_and_never_redispatched(replay):
    r = replay
    child_process = subprocess.run(
        [sys.executable, str(FIXTURE.with_name("process_loss.py")), str(r.db.db_path), str(r.wire.path.parent)],
        capture_output=True, text=True, env=dict(os.environ), timeout=15,
    )
    assert child_process.returncode == 73, child_process.stdout + child_process.stderr
    line = next(line for line in child_process.stdout.splitlines() if line.startswith("REPLAY_ACCEPTED="))
    acceptance = json.loads(line.split("=", 1)[1])
    assert len(acceptance["handles"]) == 2
    assert reconcile_lost_children(r.db) == 2
    assert reconcile_lost_children(r.db) == 0
    parent = r.parent("lost-process", web=False)
    assert {j["state"] for j in r.db.list_async_child_jobs()} == {"uncertain"}
    assert r.wire.calls == []  # Restart did not rerun inference or start a root.
    assert json.loads(delegate_task(parent_agent=parent, **r.script["dispatch"])) == acceptance
    assert r.wire.calls == []
    rejected = json.loads(delegate_task(parent_agent=parent, mode="retry", handle=acceptance["handles"][0]["id"], request_id="unsafe-retry"))
    assert "uncertain effects need review" in rejected["error"]
    receipt = r.db.get_runtime_command("lost-process", "subagent.dispatch", r.script["dispatch"]["request_id"], {
        "goal": None, "context": None, "toolsets": None, "tasks": r.script["dispatch"]["tasks"],
        "max_iterations": None, "acp_command": None, "acp_args": None, "isolation": None,
    })
    assert receipt["state"] == "uncertain"
    parent.run_conversation("REPLAY: explicit recovery")
    deliveries = [m for m in r.db.get_messages(parent.session_id) if "Delivery child-result:" in (m["content"] or "")]
    assert len(deliveries) == 2 and all("uncertain" in m["content"] for m in deliveries)


def test_real_clarify_decision_remains_pending_after_both_children_complete(replay):
    r = replay
    parent = r.parent()
    now = time.time()
    r.web._web_active_turns[parent.session_id] = r.web.WebActiveTurn(
        started_at=now, last_event_at=now, status="Running", interrupt_requested=False,
        active_agent_session_id=parent.session_id, phase="streaming", turn_id=parent._root_run_id,
    )
    parent.clarify_callback = lambda question, choices: r.web._web_clarify_callback(question, choices, session_id=parent.session_id)
    r.wire.decide = True
    r.wire.root.release.set()
    root = r.start_root(parent)
    actions = eventually(lambda: r.db.list_web_pending_actions(parent.session_id), "durable clarify action")
    action = actions[0]
    r.wire.release_all()
    for run in r.runs(parent).values():
        r.terminal(run)
    attention = SidebarMetadata(r.db).attention()[parent.session_id]
    assert attention["pending_decision"] and attention["running"]
    assert not root.done()
    assert r.db.get_web_pending_action(action["action_id"])["status"] == "pending"
    with pytest.raises(SettleBlocked, match="pending decision"):
        SidebarMetadata(r.db).patch(parent.session_id, 0, {"settled": True})
    reopened = SessionDB(r.db.db_path)
    try:
        assert reopened.get_web_pending_action(action["action_id"])["action_id"] == action["action_id"]
    finally:
        reopened.close()
    _, changed = r.web._resolve_web_pending_action(parent.session_id, action["action_id"], "Continue")
    assert changed
    r.web._web_input_queues[action["action_id"]].put_nowait("Continue")
    assert root.result(8)["completed"]
    assert not SidebarMetadata(r.db).attention()[parent.session_id]["pending_decision"]


def test_stream_unsupported_http_response_falls_back_in_same_explicit_turn(replay):
    r = replay
    r.wire.reject_stream = True
    parent = r.parent()
    result = parent.run_conversation("REPLAY: provider lacks streaming")
    assert result["final_response"] == r.script["root_result"]
    assert any(not c.get("stream") for c in r.wire.calls)


def test_failed_sqlite_terminal_commit_never_publishes_completed_success(replay):
    r = replay
    parent = r.parent()
    subscriber = asyncio.Queue()
    r.web._event_subscribers.add(subscriber)
    root = r.start_root(parent)
    run = r.runs(parent)["REPLAY: alpha"]
    r.db._conn.execute("""CREATE TRIGGER reject_terminal_commit BEFORE INSERT ON session_events
        WHEN NEW.event_type='subagent.completed'
        BEGIN SELECT RAISE(ABORT, 'synthetic disk commit failure'); END""")
    r.wire.children["REPLAY: alpha"].release.set()
    failed = r.terminal(run, "failed")
    assert "synthetic disk commit failure" in str(failed)
    assert "completed" not in {e["event_type"] for e in r.db.get_subagent_events(run["id"])}
    r.drain()
    envelopes = []
    while not subscriber.empty():
        envelopes.append(subscriber.get_nowait())
    assert not any(e["topic"] == "chat.subagent.completed" for e in envelopes)
    assert not root.done()
    r.db._conn.execute("DROP TRIGGER reject_terminal_commit")


@pytest.mark.parametrize("replay", [{"checkpoint_mode": "legacy"}, {"checkpoint_mode": "typed"}], indirect=True)
def test_real_compression_preserves_child_identity_and_delivers_at_new_boundary(replay):
    r = replay
    parent = r.parent(web=False)
    # Establish a real cached prefix before dispatch. Completions must not alter it.
    parent.run_conversation("REPLAY: before compression")
    system = parent._cached_system_prompt
    accepted = json.loads(delegate_task(parent_agent=parent, **r.script["dispatch"]))
    assert all(g.entered.wait(8) for g in r.wire.children.values())
    original_sid = parent.session_id
    # A large, synthetic conversation forces the REAL compressor to summarize
    # via the same HTTP boundary; no fabricated lineage or compressor return.
    history = [{"role": "user" if i % 2 == 0 else "assistant",
                "content": f"History {i}. " + ("replay narrative " * 600)} for i in range(40)]
    parent._flush_messages_to_session_db(history, [])
    compressed, new_system = parent._compress_context(history, None, approx_tokens=100000)
    parent._session_messages = compressed
    assert parent.context_compressor.compression_count == 1
    assert len(compressed) < len(history)
    assert new_system and system
    assert any("History 3." in str(c["messages"]) for c in r.wire.calls)
    if parent.context_compressor.checkpoint_mode == "legacy":
        assert parent.session_id != original_sid
        assert r.db.get_session(original_sid)["end_reason"] == "compression"
    else:
        assert parent.session_id == original_sid
    for handle in accepted["handles"]:
        status = json.loads(delegate_task(parent_agent=parent, mode="status", handle=handle["id"]))
        assert status["subagent"]["attempt_id"] == handle["attempt_id"]
    r.wire.release_all()
    for handle in accepted["handles"]:
        r.terminal(handle)
    assert all(j["delivered_message_id"] is None for j in r.db.list_async_child_jobs())
    parent.run_conversation("REPLAY: after compression")
    deliveries = [m for m in r.db.get_messages(parent.session_id) if "Delivery child-result:" in (m["content"] or "")]
    assert len(deliveries) == 2
    assert {run["id"] for run in r.runs(parent).values()} == {h["id"] for h in accepted["handles"]}
    if parent.session_id != original_sid:
        assert not any("Delivery child-result:" in (m["content"] or "") for m in r.db.get_messages(original_sid))


def test_two_real_profile_databases_reuse_request_key_without_reading_other_profile(replay, monkeypatch, tmp_path):
    r = replay
    first = r.parent(web=False)
    original = json.loads(delegate_task(parent_agent=first, **r.script["dispatch"]))
    assert all(g.entered.wait(8) for g in r.wire.children.values())
    r.wire.release_all()
    for handle in original["handles"]:
        r.terminal(handle)
    eventually(lambda: not first._active_children, "profile one worker cleanup")
    home_one = Path(os.environ["SPARK_HOME"])
    home_two = tmp_path / "profile-two"
    home_two.mkdir()
    (home_two / "config.yaml").write_text((home_one / "config.yaml").read_text())
    monkeypatch.setenv("SPARK_HOME", str(home_two))
    monkeypatch.setattr("core.spark_state.DEFAULT_DB_PATH", home_two / "state.db")
    other = SessionDB()
    second = AIAgent(
        api_key="synthetic-no-credentials", base_url=r.script["origin"], model=r.script["model"],
        provider="custom", max_iterations=4, quiet_mode=True, skip_context_files=True, skip_memory=True,
        session_db=other, session_id=first.session_id, enabled_toolsets=["file", "delegation"],
        working_dir=str(tmp_path),
    )
    try:
        assert other.db_path != r.db.db_path
        alien = json.loads(delegate_task(parent_agent=second, mode="status", handle=original["handles"][0]["id"]))
        assert "Owned child not found" in alien["error"]
        accepted = json.loads(delegate_task(parent_agent=second, **r.script["dispatch"]))
        assert accepted["status"] == "accepted"
        assert {h["id"] for h in accepted["handles"]}.isdisjoint(h["id"] for h in original["handles"])
        eventually(lambda: all(other.get_subagent_run(h["id"])["status"] == "completed" for h in accepted["handles"]), "profile two children")
        assert len(other.list_async_child_jobs()) == len(r.db.list_async_child_jobs()) == 2
        second.run_conversation("REPLAY: profile two explicit delivery")
        assert any("Delivery child-result:" in (m["content"] or "") for m in other.get_messages(second.session_id))
        assert all(j["delivered_message_id"] is None for j in r.db.list_async_child_jobs())
        assert r.db.get_messages(first.session_id) == []
    finally:
        eventually(lambda: not second._active_children, "profile two worker cleanup")
        second.close()
        other.close()


@pytest.mark.parametrize("replay", [{"checkpoint_mode": "legacy"}], indirect=True)
def test_lost_dispatch_ack_retry_after_real_compression_reuses_original_receipt(replay):
    r = replay
    parent = r.parent(web=False)
    accepted = json.loads(delegate_task(parent_agent=parent, **r.script["dispatch"]))
    assert all(g.entered.wait(8) for g in r.wire.children.values())
    r.wire.release_all()
    for handle in accepted["handles"]:
        r.terminal(handle)
    history = [{"role": "user" if i % 2 == 0 else "assistant",
                "content": f"History {i}. " + ("replay narrative " * 600)} for i in range(40)]
    original_sid = parent.session_id
    parent._session_messages, _ = parent._compress_context(history, None, approx_tokens=100000)
    assert parent.session_id != original_sid
    retry = json.loads(delegate_task(parent_agent=parent, **r.script["dispatch"]))
    assert retry == accepted
    assert len(r.db.list_async_child_jobs()) == 2


def test_parent_stop_cascades_to_two_http_children_without_delivering_or_reexecuting(replay):
    r = replay
    parent = r.parent()
    root = r.start_root(parent)
    runs = r.runs(parent)
    parent.interrupt("Synthetic parent Stop")
    assert root.result(8)["interrupted"]
    for run in runs.values():
        r.terminal(run, "interrupted")
    assert all(job["delivered_message_id"] is None for job in r.db.list_async_child_jobs())
    assert r.db.get_session(parent.session_id)["ended_at"] is None
    # Late HTTP replies cannot convert stopped children to successful work.
    r.wire.release_all()
    eventually(lambda: not parent._active_children, "stopped children cleanup")
    assert {run["status"] for run in r.runs(parent).values()} == {"interrupted"}
    before = copy.deepcopy(parent._session_messages)
    parent.run_conversation("REPLAY: explicit resume after Stop")
    assert parent._session_messages[:len(before)] == before
    assert all(job["delivered_message_id"] is not None for job in r.db.list_async_child_jobs())
