"""Tests for web UI SSE event bus and conversation control endpoints."""

import asyncio
import json
import time
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def web_client(monkeypatch, tmp_path):
    try:
        from starlette.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi/starlette not installed")

    monkeypatch.setenv("SPARK_HOME", str(tmp_path / ".spark"))
    (tmp_path / ".spark").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".spark" / "config.yaml").write_text(
        "model:\n"
        "  default: test-model\n"
        "  provider: ollama\n"
        "  base_url: http://localhost:11434/v1\n"
    )

    import spark_cli.web_server as web_server

    monkeypatch.setattr(web_server, "_web_event_loop", asyncio.get_event_loop())
    web_server._event_subscribers.clear()
    web_server._web_active_turns.clear()
    web_server._web_turn_aliases.clear()
    web_server._web_agents.clear()
    web_server._web_agent_signatures.clear()
    web_server._web_agent_last_used.clear()
    web_server._web_warm_inflight.clear()
    web_server._web_warm_recent.clear()
    web_server._web_queues.clear()

    return TestClient(web_server.app)


def _wait_for(predicate, timeout: float = 2.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


def test_session_messages_accept_db_prefixed_before_id(web_client):
    from core.spark_state import SessionDB

    db = SessionDB()
    try:
        db.create_session("history-page", source="web")
        first = db.append_message("history-page", "user", "one")
        second = db.append_message("history-page", "assistant", "two")
        third = db.append_message("history-page", "user", "three")
    finally:
        db.close()

    res = web_client.get(f"/api/sessions/history-page/messages?limit=2&before_id=db:{third}")

    assert res.status_code == 200
    body = res.json()
    assert [m["id"] for m in body["messages"]] == [first, second]
    assert body["has_earlier"] is False
    assert body["page_start_index"] == 0
    assert body["page_end_index"] == 1
    assert body["next_before_id"] is None


def test_session_messages_page_large_thread_from_recent_tail(web_client):
    from core.spark_state import SessionDB

    db = SessionDB()
    try:
        db.create_session("long-history-page", source="web")
        ids = []
        for idx in range(1000):
            role = "user" if idx % 2 == 0 else "assistant"
            ids.append(db.append_message("long-history-page", role, content=f"message {idx}"))
    finally:
        db.close()

    tail = web_client.get("/api/sessions/long-history-page/messages?limit=50")
    assert tail.status_code == 200
    body = tail.json()
    assert body["total"] == 1000
    assert len(body["messages"]) == 50
    assert body["messages"][0]["content"] == "message 950"
    assert body["messages"][-1]["content"] == "message 999"
    assert body["has_earlier"] is True
    assert body["page_start_index"] == 950
    assert body["page_end_index"] == 999
    assert str(body["next_before_id"]) == str(ids[950])

    older = web_client.get(
        f"/api/sessions/long-history-page/messages?limit=50&before_id=db:{ids[950]}"
    )
    assert older.status_code == 200
    older_body = older.json()
    assert len(older_body["messages"]) == 50
    assert older_body["messages"][0]["content"] == "message 900"
    assert older_body["messages"][-1]["content"] == "message 949"
    assert older_body["has_earlier"] is True
    assert older_body["page_start_index"] == 900
    assert older_body["page_end_index"] == 949

    first_page = web_client.get(
        f"/api/sessions/long-history-page/messages?limit=50&before_id=db:{ids[50]}"
    )
    assert first_page.status_code == 200
    first_body = first_page.json()
    assert first_body["messages"][0]["content"] == "message 0"
    assert first_body["messages"][-1]["content"] == "message 49"
    assert first_body["has_earlier"] is False
    assert first_body["next_before_id"] is None


def test_session_messages_10k_page_never_uses_full_history_loader(web_client, monkeypatch):
    from core.spark_state import SessionDB

    db = SessionDB()
    try:
        db.create_session("bounded-route-10k", source="web")
        db._conn.executemany(
            """INSERT INTO messages (session_id, role, content, timestamp)
               VALUES ('bounded-route-10k', ?, ?, ?)""",
            (
                ("user" if index % 2 == 0 else "assistant", f"message {index}", float(index))
                for index in range(10_000)
            ),
        )
        db._conn.execute(
            "UPDATE sessions SET message_count = 10000 WHERE id = 'bounded-route-10k'"
        )
    finally:
        db.close()

    def fail_full_history(*_args, **_kwargs):
        raise AssertionError("web history route must not call get_messages")

    monkeypatch.setattr(SessionDB, "get_messages", fail_full_history)

    response = web_client.get("/api/sessions/bounded-route-10k/messages?limit=50")

    assert response.status_code == 200
    body = response.json()
    assert len(body["messages"]) == 50
    assert body["messages"][0]["content"] == "message 9950"
    assert body["messages"][-1]["content"] == "message 9999"


def test_session_messages_matching_etag_skips_page_materialization(web_client, monkeypatch):
    from core.spark_state import SessionDB

    db = SessionDB()
    try:
        db.create_session("etag-history", source="web")
        db.append_message("etag-history", "user", "hello")
        db.append_message("etag-history", "assistant", "hi")
    finally:
        db.close()

    first = web_client.get("/api/sessions/etag-history/messages?limit=50")
    assert first.status_code == 200
    etag = first.headers["etag"]

    def fail_page_load(*_args, **_kwargs):
        raise AssertionError("matching ETag must return before page materialization")

    monkeypatch.setattr(SessionDB, "get_web_message_page", fail_page_load)
    cached = web_client.get(
        "/api/sessions/etag-history/messages?limit=50",
        headers={"If-None-Match": etag},
    )

    assert cached.status_code == 304
    assert cached.content == b""


def test_session_messages_preserves_compression_leaf_contract(web_client):
    from core.spark_state import SessionDB

    db = SessionDB()
    try:
        db.create_session("history-parent", source="web")
        db.append_message("history-parent", "user", "old transcript")
        db.create_session(
            "history-leaf", source="web", parent_session_id="history-parent"
        )
        db.append_message("history-leaf", "assistant", "compressed transcript")
        db.end_session("history-parent", end_reason="compression")
    finally:
        db.close()

    response = web_client.get("/api/sessions/history-parent/messages?limit=50")

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "history-leaf"
    assert body["migrated_from"] == "history-parent"
    assert [message["content"] for message in body["messages"]] == ["compressed transcript"]


def test_session_messages_hide_empty_assistant_placeholders(web_client):
    from core.spark_state import SessionDB

    db = SessionDB()
    try:
        db.create_session("empty_placeholder_web", source="web")
        db.append_message("empty_placeholder_web", "user", content="use a tool")
        db.append_message("empty_placeholder_web", "assistant", content="")
        db.append_message(
            "empty_placeholder_web",
            "assistant",
            content="",
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
        )
        db.append_message("empty_placeholder_web", "tool", content="{}", tool_call_id="call_1")
        db.append_message("empty_placeholder_web", "assistant", content="done")
    finally:
        db.close()

    res = web_client.get("/api/sessions/empty_placeholder_web/messages")

    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 4
    assert [(m["role"], m.get("content")) for m in body["messages"]] == [
        ("user", "use a tool"),
        ("assistant", ""),
        ("tool", "{}"),
        ("assistant", "done"),
    ]


def test_session_source_patch_moves_chat_between_project_and_chats(web_client):
    from core.spark_state import SessionDB
    from spark_cli.config import get_spark_home

    (get_spark_home() / "workspace" / "alpha").mkdir(parents=True)
    db = SessionDB()
    try:
        db.create_session("move-me", source="web")
    finally:
        db.close()

    moved = web_client.patch(
        "/api/sessions/move-me/source",
        json={"source": "workspace:alpha"},
    )
    assert moved.status_code == 200
    assert moved.json()["source"] == "workspace:alpha"

    db = SessionDB()
    try:
        assert db.get_session("move-me")["source"] == "workspace:alpha"
    finally:
        db.close()

    unfiled = web_client.patch("/api/sessions/move-me/source", json={"source": None})
    assert unfiled.status_code == 200
    assert unfiled.json()["source"] == "web"

    db = SessionDB()
    try:
        assert db.get_session("move-me")["source"] == "web"
    finally:
        db.close()


def test_create_conversation_can_preclaim_workspace_source(web_client, monkeypatch):
    import spark_cli.web_server as web_server
    from core.spark_state import SessionDB
    from spark_cli.config import get_spark_home

    (get_spark_home() / "workspace" / "particles").mkdir(parents=True)
    created_tasks = []
    monkeypatch.setattr(web_server.asyncio, "create_task", lambda coro: created_tasks.append(coro))

    try:
        resp = web_client.post(
            "/api/conversations",
            json={"message": "What is this project?", "source": "workspace:particles"},
        )
        assert resp.status_code == 200
        session_id = resp.json()["session_id"]

        db = SessionDB()
        try:
            row = db.get_session(session_id)
            assert row is not None
            assert row["source"] == "workspace:particles"
        finally:
            db.close()
    finally:
        for coro in created_tasks:
            coro.close()


def test_fake_stream_endpoint_is_disabled_by_default(web_client, monkeypatch):
    monkeypatch.delenv("SPARK_WEB_FAKE_STREAMS", raising=False)

    resp = web_client.post(
        "/api/dev/fake-streams",
        json={
            "session_id": "fake_disabled",
            "message": "hello",
            "events": [{"type": "token", "text": "nope"}],
        },
    )

    assert resp.status_code == 404


def test_fake_stream_routes_through_turn_status_snapshot_and_persistence(web_client, monkeypatch):
    import spark_cli.web_server as web_server
    from core.spark_state import SessionDB
    from spark_cli.config import get_spark_home

    monkeypatch.setenv("SPARK_WEB_FAKE_STREAMS", "1")
    (get_spark_home() / "workspace" / "particles").mkdir(parents=True)
    events = []
    original_publish = web_server._publish_event

    def capture_event(topic, data, session_id=None):
        events.append((topic, data, session_id))
        return original_publish(topic, data, session_id)

    monkeypatch.setattr(web_server, "_publish_event", capture_event)

    resp = web_client.post(
        "/api/dev/fake-streams",
        json={
            "session_id": "fake_stream_alpha",
            "message": "fake hello",
            "source": "workspace:particles",
            "events": [
                {"type": "status", "kind": "initializing_agent", "text": "Preparing fake agent"},
                {"type": "reasoning", "text": "Thinking in test mode"},
                {"type": "tool_start", "tool_call_id": "tool_1", "name": "fake_lookup", "args": {"q": "spark"}},
                {"type": "tool_end", "tool_call_id": "tool_1", "name": "fake_lookup", "result": {"ok": True}},
                {"type": "token", "text": "Alpha "},
                {"type": "stall", "text": "Holding open", "phase": "api"},
                {"type": "token", "text": "done", "delay_ms": 120},
            ],
        },
    )
    assert resp.status_code == 200

    assert _wait_for(
        lambda: web_client.get("/api/conversations/fake_stream_alpha/stream-snapshot").json()[
            "stream_text"
        ]
        == "Alpha "
    )
    snapshot = web_client.get("/api/conversations/fake_stream_alpha/stream-snapshot").json()
    status = web_client.get("/api/conversations/fake_stream_alpha/turn-status").json()
    assert snapshot["turn_active"] is True
    assert snapshot["state"] in {"streaming", "running"}
    assert status["turn_active"] is True
    assert status["timings"]["relative_seconds"]["turn_registered"] == 0.0

    assert _wait_for(
        lambda: web_client.get("/api/conversations/fake_stream_alpha/turn-status").json()[
            "turn_active"
        ]
        is False
    )
    db = SessionDB()
    try:
        row = db.get_session("fake_stream_alpha")
        messages = db.get_messages("fake_stream_alpha")
    finally:
        db.close()

    assert row["source"] == "workspace:particles"
    assert [(m["role"], m["content"]) for m in messages] == [
        ("user", "fake hello"),
        ("assistant", "Alpha done"),
    ]
    assert any(event[0] == "sessions.changed" for event in events)
    done = [event for event in events if event[0] == "chat.turn_done"]
    assert done
    assert done[-1][1]["backend_error_class"] is None


def test_fake_stream_compaction_failure_clears_active_turn(web_client, monkeypatch):
    import spark_cli.web_server as web_server
    from core.spark_state import SessionDB

    monkeypatch.setenv("SPARK_WEB_FAKE_STREAMS", "1")
    events = []
    original_publish = web_server._publish_event

    def capture_event(topic, data, session_id=None):
        events.append((topic, data, session_id))
        return original_publish(topic, data, session_id)

    monkeypatch.setattr(web_server, "_publish_event", capture_event)

    resp = web_client.post(
        "/api/dev/fake-streams",
        json={
            "session_id": "fake_compaction_failure",
            "message": "long thread trigger",
            "events": [
                {"type": "token", "text": "Before compaction. "},
                {
                    "type": "compact_fail",
                    "kind": "context_compression",
                    "name": "ContextCompactionError",
                    "text": "Context compression failed; retry this message to continue.",
                },
            ],
        },
    )
    assert resp.status_code == 200

    assert _wait_for(
        lambda: web_client.get("/api/conversations/fake_compaction_failure/turn-status").json()[
            "turn_active"
        ]
        is False
    )
    status = web_client.get("/api/conversations/fake_compaction_failure/turn-status").json()
    assert status["state"] == "not_found"

    compact_events = [event for event in events if event[0] == "chat.compaction"]
    assert compact_events
    assert compact_events[-1][1]["status"] == "failed"
    assert compact_events[-1][1]["reason"] == "context_compression"
    done = [event for event in events if event[0] == "chat.turn_done"]
    assert done
    assert done[-1][1]["backend_error_class"] == "ContextCompactionError"

    db = SessionDB()
    try:
        messages = db.get_messages("fake_compaction_failure")
    finally:
        db.close()
    assert [(m["role"], m["content"]) for m in messages] == [
        ("user", "long thread trigger"),
        (
            "assistant",
            "Before compaction. \n\nContext compression failed; retry this message to continue.",
        ),
    ]


def test_fake_stream_supports_multiple_simultaneous_sessions(web_client, monkeypatch):
    monkeypatch.setenv("SPARK_WEB_FAKE_STREAMS", "1")

    session_events = {
        "fake_multi_a": ["A1 ", "A2"],
        "fake_multi_b": ["B1 ", "B2"],
        "fake_multi_c": ["C1 ", "C2"],
    }
    for session_id, chunks in session_events.items():
        resp = web_client.post(
            "/api/dev/fake-streams",
            json={
                "session_id": session_id,
                "message": f"start {session_id}",
                "events": [
                    {"type": "token", "text": chunks[0]},
                    {"type": "token", "text": chunks[1], "delay_ms": 500},
                ],
            },
        )
        assert resp.status_code == 200

    for session_id, chunks in session_events.items():
        assert _wait_for(
            lambda sid=session_id, first=chunks[0]: web_client.get(
                f"/api/conversations/{sid}/stream-snapshot"
            ).json()["stream_text"].startswith(first)
        )
        snapshot = web_client.get(f"/api/conversations/{session_id}/stream-snapshot").json()
        assert snapshot["turn_active"] is True

    assert _wait_for(
        lambda: all(
            web_client.get(f"/api/conversations/{session_id}/turn-status").json()[
                "turn_active"
            ]
            is False
            for session_id in session_events
        )
    )

    from core.spark_state import SessionDB

    db = SessionDB()
    try:
        for session_id, chunks in session_events.items():
            messages = db.get_messages(session_id)
            assert messages[-1]["role"] == "assistant"
            assert messages[-1]["content"] == "".join(chunks)
    finally:
        db.close()


class TestEventBus:
    def test_publish_event_delivers_to_subscriber(self, web_client, monkeypatch):
        import spark_cli.web_server as web_server

        async def run():
            loop = asyncio.get_running_loop()
            web_server._web_event_loop = loop
            q: asyncio.Queue = asyncio.Queue()
            web_server._event_subscribers.add(q)
            web_server._publish_event("chat.token", {"t": "hi"}, "sess1")
            return await asyncio.wait_for(q.get(), timeout=2.0)

        env = asyncio.run(run())
        assert env["topic"] == "chat.token"
        assert env["session_id"] == "sess1"
        assert env["data"]["t"] == "hi"

    def test_priority_turn_done_survives_full_subscriber_queue(self, web_client):
        import spark_cli.web_server as web_server

        async def run():
            loop = asyncio.get_running_loop()
            web_server._web_event_loop = loop
            q: asyncio.Queue = asyncio.Queue(maxsize=2)
            web_server._event_subscribers.add(q)
            try:
                web_server._publish_event("chat.token", {"t": "a"}, "sess1")
                web_server._publish_event("chat.token", {"t": "b"}, "sess1")
                web_server._publish_event("chat.turn_done", {"ok": True}, "sess1")
                await asyncio.sleep(0.05)
                items = []
                while not q.empty():
                    items.append(q.get_nowait())
                return items
            finally:
                web_server._event_subscribers.discard(q)

        items = asyncio.run(run())
        assert any(item["topic"] == "chat.turn_done" for item in items)
        assert len(items) <= 2

    def test_tool_callback_emits_status_event(self, web_client):
        import spark_cli.web_server as web_server

        async def run():
            loop = asyncio.get_running_loop()
            web_server._web_event_loop = loop
            q: asyncio.Queue = asyncio.Queue()
            web_server._event_subscribers.add(q)
            try:
                web_server._mark_web_turn_active("sess_status")
                callbacks = web_server._make_web_chat_callbacks("sess_status", asyncio.Queue(), loop)
                tool_start = callbacks[1]
                tool_start("tid_1", "terminal", {"command": "echo ok"})
                items = []
                for _ in range(2):
                    items.append(await asyncio.wait_for(q.get(), timeout=2.0))
                return items
            finally:
                web_server._event_subscribers.discard(q)
                web_server._clear_web_turn("sess_status")

        events = asyncio.run(run())
        status = next(item for item in events if item["topic"] == "chat.status")
        assert status["session_id"] == "sess_status"
        assert status["data"]["kind"] == "tool_running"
        assert status["data"]["message"] == "Tool running: terminal"

    def test_tool_callbacks_emit_backend_duration_seconds(self, web_client, monkeypatch):
        import spark_cli.web_server as web_server

        class FakeClock:
            def __init__(self):
                self._times = [1000.0, 1000.1, 1012.5, 1012.6]
                self._monotonic = [50.0, 62.5]

            def time(self):
                return self._times.pop(0) if self._times else 1012.6

            def monotonic(self):
                return self._monotonic.pop(0) if self._monotonic else 62.5

        monkeypatch.setattr(web_server, "time", FakeClock())

        async def run():
            loop = asyncio.get_running_loop()
            web_server._web_event_loop = loop
            q: asyncio.Queue = asyncio.Queue()
            web_server._event_subscribers.add(q)
            try:
                web_server._mark_web_turn_active("sess_duration")
                callbacks = web_server._make_web_chat_callbacks("sess_duration", asyncio.Queue(), loop)
                tool_start = callbacks[1]
                tool_complete = callbacks[2]
                tool_start("tid_1", "web_extract", {"urls": ["https://example.com"]})
                tool_complete("tid_1", "web_extract", {"urls": ["https://example.com"]}, "{}")
                items = []
                while len(items) < 4:
                    items.append(await asyncio.wait_for(q.get(), timeout=2.0))
                return items
            finally:
                web_server._event_subscribers.discard(q)
                web_server._clear_web_turn("sess_duration")

        events = asyncio.run(run())
        start = next(item for item in events if item["topic"] == "chat.tool_start")
        end = next(item for item in events if item["topic"] == "chat.tool_end")
        assert isinstance(start["data"]["started_at"], float)
        assert isinstance(end["data"]["ended_at"], float)
        assert end["data"]["duration_seconds"] == 12.5

    def test_token_callback_updates_stream_snapshot_before_turn_done(self, web_client):
        import spark_cli.web_server as web_server

        async def run():
            loop = asyncio.get_running_loop()
            web_server._web_event_loop = loop
            web_server._mark_web_turn_active("sess_snapshot")
            callbacks = web_server._make_web_chat_callbacks("sess_snapshot", asyncio.Queue(), loop)
            token_callback = callbacks[0]
            token_callback("hello")
            token_callback(" world")

        asyncio.run(run())
        try:
            status = web_client.get("/api/conversations/sess_snapshot/turn-status")
            assert status.status_code == 200
            assert status.json()["stream_text_chars"] == len("hello world")
            assert status.json()["stream_revision"] == 2
            assert status.json()["state"] == "streaming"
            assert status.json()["reason"] == "stream_text_available"
            assert status.json()["stale_after_seconds"] > 0
            assert status.json()["diagnostics"]["source"] == "turn-status"
            assert status.json()["diagnostics"]["requested_session_id"] == "sess_snapshot"

            snapshot = web_client.get("/api/conversations/sess_snapshot/stream-snapshot")
            assert snapshot.status_code == 200
            data = snapshot.json()
            assert data["turn_active"] is True
            assert data["state"] == "streaming"
            assert data["stream_text"] == "hello world"
            assert data["stream_revision"] == 2
            assert data["stream_text_mode"] == "full"
            assert data["stream_text_start"] == 0
            assert data["stream_text_complete"] is True
        finally:
            web_server._clear_web_turn("sess_snapshot")

    def test_turn_status_reports_not_found_when_no_active_turn(self, web_client):
        resp = web_client.get("/api/conversations/no_active_turn/turn-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["turn_active"] is False
        assert data["state"] == "not_found"
        assert data["reason"] == "no_active_turn"
        assert data["active_turn_session_id"] is None

    def test_turn_status_reports_stalled_active_turn(self, web_client, monkeypatch):
        import spark_cli.web_server as web_server

        web_server._mark_web_turn_active("sess_stalled")
        try:
            _, turn = web_server._get_web_turn("sess_stalled")
            assert turn is not None
            with turn.lock:
                turn.last_event_at = 100.0
            monkeypatch.setattr(web_server.time, "time", lambda: 200.0)
            resp = web_client.get("/api/conversations/sess_stalled/turn-status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["turn_active"] is True
            assert data["state"] == "stalled"
            assert data["reason"] == "no_recent_backend_event"
            assert data["idle_for_seconds"] == 100.0
        finally:
            web_server._clear_web_turn("sess_stalled")

    def test_turn_status_includes_latency_timing_metadata(self, web_client):
        import spark_cli.web_server as web_server

        turn = web_server._mark_web_turn_active("sess_timing")
        try:
            with turn.lock:
                turn.timings["backend_received"] = turn.started_at - 0.25
                turn.timings["model_request_start"] = turn.started_at + 0.75
                turn.timings["first_visible_event"] = turn.started_at + 1.5
            resp = web_client.get("/api/conversations/sess_timing/turn-status")
            assert resp.status_code == 200
            timings = resp.json()["timings"]
            assert timings["absolute"]["backend_received"] == turn.started_at - 0.25
            assert timings["relative_seconds"]["turn_registered"] == 0.0
            assert timings["relative_seconds"]["send_to_model_request_start"] == 1.0
            assert timings["relative_seconds"]["send_to_first_visible_event"] == 1.75
            assert resp.json()["diagnostics"]["timings"]["relative_seconds"]["send_to_first_visible_event"] == 1.75
        finally:
            web_server._clear_web_turn("sess_timing")

    def test_conversation_diagnostics_reports_safe_timing_metadata(self, web_client):
        import spark_cli.web_server as web_server
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            db.create_session("sess_diag", source="web", model="m1")
            db.append_message("sess_diag", "user", content="private prompt text")
        finally:
            db.close()

        turn = web_server._mark_web_turn_active("sess_diag")
        try:
            with turn.lock:
                turn.timings["backend_received"] = turn.started_at
                turn.timings["model_request_start"] = turn.started_at + 0.5
                turn.timings["first_visible_event"] = turn.started_at + 1.25
            resp = web_client.get("/api/conversations/sess_diag/diagnostics")
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            assert data["turn"]["active"] is True
            assert data["message_count"] == 1
            assert data["timing_breakdown"]["send_to_model_request_start_s"] == 0.5
            assert data["timing_breakdown"]["send_to_first_visible_event_s"] == 1.25
            assert "private prompt text" not in json.dumps(data)
        finally:
            web_server._clear_web_turn("sess_diag")

    def test_stream_snapshot_can_return_delta_or_tail(self, web_client):
        import spark_cli.web_server as web_server

        async def run():
            loop = asyncio.get_running_loop()
            web_server._web_event_loop = loop
            web_server._mark_web_turn_active("sess_snapshot_delta")
            callbacks = web_server._make_web_chat_callbacks("sess_snapshot_delta", asyncio.Queue(), loop)
            token_callback = callbacks[0]
            token_callback("alpha ")
            token_callback("bravo ")
            token_callback("charlie")

        asyncio.run(run())
        try:
            delta = web_client.get(
                "/api/conversations/sess_snapshot_delta/stream-snapshot?after_chars=6"
            )
            assert delta.status_code == 200
            delta_data = delta.json()
            assert delta_data["stream_text"] == "bravo charlie"
            assert delta_data["stream_text_start"] == 6
            assert delta_data["stream_text_mode"] == "delta"
            assert delta_data["stream_text_complete"] is False
            assert delta_data["stream_text_chars"] == len("alpha bravo charlie")

            tail = web_client.get(
                "/api/conversations/sess_snapshot_delta/stream-snapshot?tail_chars=7"
            )
            assert tail.status_code == 200
            tail_data = tail.json()
            assert tail_data["stream_text"] == "charlie"
            assert tail_data["stream_text_start"] == len("alpha bravo ")
            assert tail_data["stream_text_mode"] == "tail"
            assert tail_data["stream_text_complete"] is False
            assert tail_data["diagnostics"]["source"] == "stream-snapshot"
        finally:
            web_server._clear_web_turn("sess_snapshot_delta")

    def test_token_callbacks_keep_two_active_sessions_isolated(self, web_client):
        import spark_cli.web_server as web_server

        async def run():
            loop = asyncio.get_running_loop()
            web_server._web_event_loop = loop
            events: asyncio.Queue = asyncio.Queue()
            web_server._event_subscribers.add(events)
            try:
                web_server._mark_web_turn_active("alpha_session")
                web_server._mark_web_turn_active("bravo_session")
                alpha_callbacks = web_server._make_web_chat_callbacks(
                    "alpha_session", asyncio.Queue(), loop
                )
                bravo_callbacks = web_server._make_web_chat_callbacks(
                    "bravo_session", asyncio.Queue(), loop
                )
                alpha_token = alpha_callbacks[0]
                bravo_token = bravo_callbacks[0]
                alpha_token("ALPHA-01 ")
                bravo_token("BRAVO-01 ")
                alpha_token("ALPHA-02")

                items = []
                while len(items) < 3:
                    items.append(await asyncio.wait_for(events.get(), timeout=2.0))
                return items
            finally:
                web_server._event_subscribers.discard(events)

        events = asyncio.run(run())
        try:
            alpha_snapshot = web_client.get("/api/conversations/alpha_session/stream-snapshot")
            bravo_snapshot = web_client.get("/api/conversations/bravo_session/stream-snapshot")
            assert alpha_snapshot.status_code == 200
            assert bravo_snapshot.status_code == 200
            assert alpha_snapshot.json()["stream_text"] == "ALPHA-01 ALPHA-02"
            assert bravo_snapshot.json()["stream_text"] == "BRAVO-01 "

            by_session = {}
            for event in events:
                by_session.setdefault(event["session_id"], "")
                by_session[event["session_id"]] += event["data"]["t"]
            assert by_session == {
                "alpha_session": "ALPHA-01 ALPHA-02",
                "bravo_session": "BRAVO-01 ",
            }
        finally:
            web_server._clear_web_turn("alpha_session")
            web_server._clear_web_turn("bravo_session")

    def test_session_migration_records_compaction_diagnostics(self, web_client):
        import spark_cli.web_server as web_server

        events = []
        original_publish = web_server._publish_event

        def capture_event(topic, data, session_id=None):
            events.append((topic, data, session_id))
            return original_publish(topic, data, session_id)

        web_server._publish_event = capture_event
        try:
            loop = asyncio.new_event_loop()
            try:
                web_server._mark_web_turn_active("compact_parent")
                callbacks = web_server._make_web_chat_callbacks("compact_parent", asyncio.Queue(), loop)
                session_migrated_callback = callbacks[5]
                session_migrated_callback("compact_parent", "compact_leaf", "context_compression")
            finally:
                loop.close()

            status = web_client.get("/api/conversations/compact_leaf/turn-status")
            assert status.status_code == 200
            data = status.json()
            assert data["turn_active"] is True
            assert data["compaction"]["status"] == "completed"
            assert data["compaction"]["old_session_id"] == "compact_parent"
            assert data["compaction"]["new_session_id"] == "compact_leaf"
            assert data["diagnostics"]["compaction"]["reason"] == "context_compression"
            assert any(event[0] == "chat.session_migrated" for event in events)
            assert any(event[0] == "chat.compaction" for event in events)
        finally:
            web_server._publish_event = original_publish
            web_server._clear_web_turn("compact_parent")
            web_server._clear_web_turn("compact_leaf")

    def test_multi_chat_streaming_stress_keeps_three_active_sessions_isolated(self, web_client):
        import spark_cli.web_server as web_server

        sessions = {
            "stress_alpha": ["A1 ", "A2 ", "A3"],
            "stress_bravo": ["B1 ", "B2"],
            "stress_charlie": ["C1 ", "C2 ", "C3 ", "C4"],
        }

        async def run():
            loop = asyncio.get_running_loop()
            web_server._web_event_loop = loop
            events: asyncio.Queue = asyncio.Queue()
            web_server._event_subscribers.add(events)
            try:
                callbacks_by_session = {}
                for session_id in sessions:
                    web_server._mark_web_turn_active(session_id)
                    callbacks_by_session[session_id] = web_server._make_web_chat_callbacks(
                        session_id, asyncio.Queue(), loop
                    )[0]

                for session_id, chunks in sessions.items():
                    callbacks_by_session[session_id](chunks[0])
                callbacks_by_session["stress_alpha"](sessions["stress_alpha"][1])
                callbacks_by_session["stress_charlie"](sessions["stress_charlie"][1])
                callbacks_by_session["stress_bravo"](sessions["stress_bravo"][1])
                callbacks_by_session["stress_charlie"](sessions["stress_charlie"][2])
                callbacks_by_session["stress_alpha"](sessions["stress_alpha"][2])
                callbacks_by_session["stress_charlie"](sessions["stress_charlie"][3])

                items = []
                expected_count = sum(len(chunks) for chunks in sessions.values())
                while len(items) < expected_count:
                    items.append(await asyncio.wait_for(events.get(), timeout=2.0))
                return items
            finally:
                web_server._event_subscribers.discard(events)

        events = asyncio.run(run())
        try:
            by_session = {}
            for event in events:
                assert event["topic"] == "chat.token"
                by_session.setdefault(event["session_id"], "")
                by_session[event["session_id"]] += event["data"]["t"]

            assert by_session == {
                session_id: "".join(chunks)
                for session_id, chunks in sessions.items()
            }

            for session_id, chunks in sessions.items():
                snapshot = web_client.get(f"/api/conversations/{session_id}/stream-snapshot")
                turn_status = web_client.get(f"/api/conversations/{session_id}/turn-status")
                assert snapshot.status_code == 200
                assert turn_status.status_code == 200
                assert snapshot.json()["stream_text"] == "".join(chunks)
                assert snapshot.json()["state"] == "streaming"
                assert turn_status.json()["state"] == "streaming"
                assert turn_status.json()["stream_text_chars"] == len("".join(chunks))
        finally:
            for session_id in sessions:
                web_server._clear_web_turn(session_id)

    def test_token_callback_strips_ansi_from_events_queue_and_snapshot(self, web_client):
        import spark_cli.web_server as web_server

        async def run():
            loop = asyncio.get_running_loop()
            web_server._web_event_loop = loop
            stream_queue: asyncio.Queue = asyncio.Queue()
            event_queue: asyncio.Queue = asyncio.Queue()
            web_server._event_subscribers.add(event_queue)
            try:
                web_server._mark_web_turn_active("sess_ansi_token")
                callbacks = web_server._make_web_chat_callbacks("sess_ansi_token", stream_queue, loop)
                token_callback = callbacks[0]
                token_callback("\x1b[31mred\x1b[0m")
                stream_token = await asyncio.wait_for(stream_queue.get(), timeout=2.0)
                event = await asyncio.wait_for(event_queue.get(), timeout=2.0)
                return stream_token, event
            finally:
                web_server._event_subscribers.discard(event_queue)

        stream_token, event = asyncio.run(run())
        try:
            assert stream_token == "red"
            assert "\x1b[" not in stream_token
            assert event["topic"] == "chat.token"
            assert event["data"]["t"] == "red"

            snapshot = web_client.get("/api/conversations/sess_ansi_token/stream-snapshot")
            assert snapshot.status_code == 200
            data = snapshot.json()
            assert data["stream_text"] == "red"
            assert "\x1b[" not in data["stream_text"]
        finally:
            web_server._clear_web_turn("sess_ansi_token")

    def test_tool_callback_strips_ansi_from_preview_payload(self, web_client):
        import spark_cli.web_server as web_server

        async def run():
            loop = asyncio.get_running_loop()
            web_server._web_event_loop = loop
            q: asyncio.Queue = asyncio.Queue()
            web_server._event_subscribers.add(q)
            try:
                callbacks = web_server._make_web_chat_callbacks("sess_ansi_tool", asyncio.Queue(), loop)
                tool_complete = callbacks[2]
                tool_complete("tid_color", "terminal", {}, "\x1b[32mok\x1b[0m")
                items = []
                while len(items) < 2:
                    items.append(await asyncio.wait_for(q.get(), timeout=2.0))
                return items
            finally:
                web_server._event_subscribers.discard(q)

        events = asyncio.run(run())
        end = next(item for item in events if item["topic"] == "chat.tool_end")
        assert end["data"]["result_preview"] == "ok"
        assert "\x1b[" not in end["data"]["result_preview"]

    def test_subagent_callback_persists_and_publishes_snapshot(self, web_client):
        import spark_cli.web_server as web_server
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            db.create_session("subagent_parent", source="web", model="m1")
        finally:
            db.close()

        async def run():
            loop = asyncio.get_running_loop()
            web_server._web_event_loop = loop
            q: asyncio.Queue = asyncio.Queue()
            web_server._event_subscribers.add(q)
            try:
                callbacks = web_server._make_web_chat_callbacks("subagent_parent", asyncio.Queue(), loop)
                subagent_callback = callbacks[6]
                subagent_callback(
                    {
                        "schema": "spark.subagent.lifecycle.v1",
                        "type": "subagent.started",
                        "event": "started",
                        "subagent_id": "subagent-1",
                        "task_index": 0,
                        "task_number": 1,
                        "task_count": 1,
                        "display_name": "Subagent 1",
                        "goal_preview": "Inspect the files",
                        "model": "m1",
                        "payload": {
                            "parent_session_id": "subagent_parent",
                            "provider": "test-provider",
                            "toolsets": ["terminal"],
                            "preview": "\x1b[33mreading\x1b[0m",
                        },
                    }
                )
                return await asyncio.wait_for(q.get(), timeout=2.0)
            finally:
                web_server._event_subscribers.discard(q)

        env = asyncio.run(run())
        assert env["topic"] == "chat.subagent.started"
        assert env["session_id"] == "subagent_parent"
        assert env["data"]["subagent_id"] == "subagent-1"
        assert env["data"]["subagent"]["status"] == "running"
        assert env["data"]["event"]["text"] == "reading"
        assert "\x1b[" not in env["data"]["data"]["preview"]

        listing = web_client.get("/api/conversations/subagent_parent/subagents")
        assert listing.status_code == 200
        runs = listing.json()["subagents"]
        assert len(runs) == 1
        assert runs[0]["id"] == "subagent-1"
        assert runs[0]["parent_session_id"] == "subagent_parent"
        assert runs[0]["task"] == "Inspect the files"

        detail = web_client.get("/api/conversations/subagent_parent/subagents/subagent-1")
        assert detail.status_code == 200
        data = detail.json()
        assert data["subagent"]["id"] == "subagent-1"
        assert data["events"][0]["event_type"] == "started"
        assert data["events"][0]["data"]["event"] == "started"
        assert data["events"][0]["data"]["payload"]["preview"] == "reading"

    def test_subagent_snapshots_follow_full_compression_chain(self, web_client):
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            db.create_session("chain_parent", source="web", model="m1")
            db.create_session("chain_mid", source="web", model="m1", parent_session_id="chain_parent")
            db.create_session("chain_latest", source="web", model="m1", parent_session_id="chain_mid")
            db.create_session("chain_child", source="web", model="m1", parent_session_id="chain_mid")

            def _mark_compressed(conn):
                conn.execute("UPDATE sessions SET end_reason = 'compression' WHERE id IN (?, ?)", ("chain_parent", "chain_mid"))

            db._execute_write(_mark_compressed)
            db.create_subagent_run(
                {
                    "id": "chain_subagent",
                    "parent_session_id": "chain_mid",
                    "child_session_id": "chain_child",
                    "task_index": 0,
                    "name": "Chain",
                    "status": "completed",
                    "task": "work from middle",
                }
            )
        finally:
            db.close()

        original = web_client.get("/api/conversations/chain_parent/subagents")
        latest = web_client.get("/api/conversations/chain_latest/subagents")
        detail = web_client.get("/api/conversations/chain_parent/subagents/chain_subagent")

        assert original.status_code == 200
        assert latest.status_code == 200
        assert detail.status_code == 200
        assert [r["id"] for r in original.json()["subagents"]] == ["chain_subagent"]
        assert [r["id"] for r in latest.json()["subagents"]] == ["chain_subagent"]
        assert detail.json()["subagent"]["parent_session_id"] == "chain_mid"

    def test_subagent_messages_returns_child_session_messages_safely(self, web_client):
        from core.spark_state import SessionDB

        large_tool_output = "x" * 3000
        db = SessionDB()
        try:
            db.create_session("msg_parent", source="web", model="m1")
            db.create_session("msg_child", source="web", model="m1", parent_session_id="msg_parent")
            db.create_subagent_run(
                {
                    "id": "msg_subagent",
                    "parent_session_id": "msg_parent",
                    "child_session_id": "msg_child",
                    "task_index": 0,
                    "name": "Messages",
                    "status": "running",
                    "task": "read files",
                }
            )
            db.append_message("msg_child", "user", content="child prompt")
            db.append_message("msg_child", "tool", content=large_tool_output, tool_name="terminal")
        finally:
            db.close()

        resp = web_client.get("/api/conversations/msg_parent/subagents/msg_subagent/messages")
        assert resp.status_code == 200
        data = resp.json()
        assert data["child_session_id"] == "msg_child"
        assert data["total"] == 2
        assert [m["message_index"] for m in data["messages"]] == [0, 1]
        tool_msg = data["messages"][1]
        assert tool_msg["role"] == "tool"
        assert tool_msg["result_truncated"] is True
        assert len(tool_msg["content"]) < len(large_tool_output)

        full = web_client.get(
            "/api/conversations/msg_parent/subagents/msg_subagent/messages?include_tool_results=true"
        )
        assert full.status_code == 200
        assert full.json()["messages"][1]["content"] == large_tool_output

    def test_subagent_interrupt_calls_tracked_active_child(self, web_client):
        import spark_cli.web_server as web_server
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            db.create_session("interrupt_parent", source="web", model="m1")
            db.create_session("interrupt_child", source="web", model="m1", parent_session_id="interrupt_parent")
            db.create_subagent_run(
                {
                    "id": "interrupt_subagent",
                    "parent_session_id": "interrupt_parent",
                    "child_session_id": "interrupt_child",
                    "task_index": 0,
                    "name": "Interrupt",
                    "status": "running",
                    "task": "long task",
                }
            )
        finally:
            db.close()

        child = MagicMock()
        child.session_id = "interrupt_child"
        parent = MagicMock()
        parent._active_children = [child]
        web_server._web_agents["interrupt_parent"] = parent
        web_server._mark_web_turn_active("interrupt_parent")
        try:
            resp = web_client.post(
                "/api/conversations/interrupt_parent/subagents/interrupt_subagent/interrupt",
                json={"message": "stop child"},
            )
            assert resp.status_code == 200
            child.interrupt.assert_called_once_with("stop child")
            assert resp.json()["status"] == "stopping"
        finally:
            web_server._clear_web_turn("interrupt_parent")
            web_server._web_agents.pop("interrupt_parent", None)

    def test_subagent_interrupt_conflicts_when_child_not_active(self, web_client):
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            db.create_session("inactive_parent", source="web", model="m1")
            db.create_session("inactive_child", source="web", model="m1", parent_session_id="inactive_parent")
            db.create_subagent_run(
                {
                    "id": "inactive_subagent",
                    "parent_session_id": "inactive_parent",
                    "child_session_id": "inactive_child",
                    "task_index": 0,
                    "name": "Inactive",
                    "status": "completed",
                    "task": "done",
                }
            )
        finally:
            db.close()

        resp = web_client.post(
            "/api/conversations/inactive_parent/subagents/inactive_subagent/interrupt",
            json={},
        )
        assert resp.status_code == 409


class TestConversationModels:
    def test_get_conversation_models(self, web_client):
        resp = web_client.get("/api/conversations/models")
        assert resp.status_code == 200
        data = resp.json()
        assert "models" in data
        assert len(data["models"]) >= 1
        assert "id" in data["models"][0]

    def test_commands_include_issue_skill(self, web_client, monkeypatch):
        from pathlib import Path

        import agent.skill_commands as skill_commands
        import tools.skills_tool as skills_tool

        repo_skills = Path(__file__).resolve().parents[2] / "skills"
        skill_commands._skill_commands = {}
        monkeypatch.setattr(skills_tool, "SKILLS_DIR", repo_skills)

        resp = web_client.get("/api/commands")
        assert resp.status_code == 200
        names = {cmd["name"] for cmd in resp.json()}
        assert "issue" in names


class TestConversationControl:
    def test_sessions_can_filter_to_web_source(self, web_client):
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            db.create_session("web_session", source="web", model="m1")
            db.create_session("web_child_session", source="web", model="m1", parent_session_id="web_session")
            db.create_session("cli_session", source="cli", model="m1")
        finally:
            db.close()

        resp = web_client.get("/api/sessions?source=web&limit=20")
        assert resp.status_code == 200
        ids = {row["id"] for row in resp.json()["sessions"]}
        assert "web_session" in ids
        assert "web_child_session" not in ids
        assert "cli_session" not in ids
        assert resp.json()["total"] == 1

    def test_sessions_list_returns_compact_sidebar_rows(self, web_client):
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            db.create_session("web_compact_session", source="web", model="m1")
            db.update_system_prompt("web_compact_session", "large prompt" * 1000)
        finally:
            db.close()

        resp = web_client.get("/api/sessions?source=web&limit=20")
        assert resp.status_code == 200
        row = next(r for r in resp.json()["sessions"] if r["id"] == "web_compact_session")
        assert "system_prompt" not in row
        assert "model_config" not in row
        assert row["id"] == "web_compact_session"
        assert row["model"] == "m1"

    def test_sessions_list_uses_authoritative_active_turn_state(self, web_client):
        import spark_cli.web_server as web_server
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            db.create_session("recent_done_session", source="web", model="m1")
            db.append_message("recent_done_session", "user", content="done")
            db.create_session("registered_active_session", source="web", model="m1")
            db.append_message("registered_active_session", "user", content="active")
        finally:
            db.close()

        web_server._mark_web_turn_active("registered_active_session")

        resp = web_client.get("/api/sessions?source=web&limit=20")
        assert resp.status_code == 200
        rows = {row["id"]: row for row in resp.json()["sessions"]}
        assert rows["recent_done_session"]["is_active"] is False
        assert rows["registered_active_session"]["is_active"] is True

    def test_session_search_can_filter_to_web_source(self, web_client):
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            db.create_session("web_search_session", source="web", model="m1")
            db.set_session_title("web_search_session", "Needle thread")
            db.append_message("web_search_session", "user", content="needle project")
            db.create_session("cli_search_session", source="cli", model="m1")
            db.append_message("cli_search_session", "user", content="needle project")
        finally:
            db.close()

        resp = web_client.get("/api/sessions/search?q=needle&source=web&limit=20")
        assert resp.status_code == 200
        ids = {row["session_id"] for row in resp.json()["results"]}
        assert "web_search_session" in ids
        assert "cli_search_session" not in ids
        assert resp.json()["results"][0]["title"] == "Needle thread"

    def test_session_title_patch(self, web_client):
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            db.create_session("title_session", source="web", model="m1")
        finally:
            db.close()

        resp = web_client.patch("/api/sessions/title_session/title", json={"title": "Renamed Thread"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "Renamed Thread"

        db2 = SessionDB()
        try:
            assert db2.get_session("title_session")["title"] == "Renamed Thread"
        finally:
            db2.close()

    def test_session_title_patch_rejects_duplicate(self, web_client):
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            db.create_session("title_one", source="web", model="m1")
            db.create_session("title_two", source="web", model="m1")
            db.set_session_title("title_one", "Taken")
        finally:
            db.close()

        resp = web_client.patch("/api/sessions/title_two/title", json={"title": "Taken"})
        assert resp.status_code == 400

    def test_session_tool_result_endpoint_returns_full_tool_content(self, web_client):
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            db.create_session("tool_result_session", source="web", model="m1")
            db.append_message("tool_result_session", "user", content="hello")
            db.append_message(
                "tool_result_session",
                "tool",
                content="full output" * 1000,
                tool_call_id="call_123",
                tool_name="browser_console",
            )
        finally:
            db.close()

        resp = web_client.get("/api/sessions/tool_result_session/tool-results/call_123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tool_call_id"] == "call_123"
        assert data["tool_name"] == "browser_console"
        assert data["content"] == "full output" * 1000

    def test_session_messages_preview_large_tool_content_by_default(self, web_client):
        from core.spark_state import SessionDB

        full_output = "large output " * 1000
        db = SessionDB()
        try:
            db.create_session("tool_preview_session", source="web", model="m1")
            db.append_message("tool_preview_session", "user", content="hello")
            db.append_message(
                "tool_preview_session",
                "tool",
                content=full_output,
                tool_call_id="call_preview",
                tool_name="browser_console",
            )
        finally:
            db.close()

        resp = web_client.get("/api/sessions/tool_preview_session/messages")
        assert resp.status_code == 200
        tool_msg = next(m for m in resp.json()["messages"] if m["role"] == "tool")
        assert tool_msg["content"] == tool_msg["result_preview"]
        assert len(tool_msg["content"]) < len(full_output)
        assert tool_msg["result_chars"] == len(full_output)
        assert tool_msg["result_truncated"] is True
        assert tool_msg["has_full_result"] is True

        full_resp = web_client.get(
            "/api/sessions/tool_preview_session/messages?include_tool_results=true",
        )
        assert full_resp.status_code == 200
        full_tool_msg = next(m for m in full_resp.json()["messages"] if m["role"] == "tool")
        assert full_tool_msg["content"] == full_output

    def test_session_messages_strip_ansi_from_chat_history_payloads(self, web_client):
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            db.create_session("ansi_history_session", source="web", model="m1")
            db.append_message("ansi_history_session", "user", content="hello")
            db.append_message(
                "ansi_history_session",
                "assistant",
                content="\x1b[35mpurple answer\x1b[0m",
            )
            db.append_message(
                "ansi_history_session",
                "tool",
                content="\x1b[32mtool output\x1b[0m",
                tool_call_id="call_ansi",
                tool_name="terminal",
            )
        finally:
            db.close()

        resp = web_client.get("/api/sessions/ansi_history_session/messages?include_tool_results=true")
        assert resp.status_code == 200
        messages = resp.json()["messages"]
        assistant_msg = next(m for m in messages if m["role"] == "assistant")
        tool_msg = next(m for m in messages if m["role"] == "tool")
        assert assistant_msg["content"] == "purple answer"
        assert tool_msg["content"] == "tool output"
        assert "\x1b[" not in str(messages)

        full_result = web_client.get("/api/sessions/ansi_history_session/tool-results/call_ansi")
        assert full_result.status_code == 200
        assert full_result.json()["content"] == "tool output"

    def test_session_messages_include_absolute_message_index_when_paginated(self, web_client):
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            db.create_session("message_index_session", source="web", model="m1")
            db.append_message("message_index_session", "user", content="first")
            db.append_message("message_index_session", "assistant", content="first response")
            db.append_message("message_index_session", "user", content="retry target")
            db.append_message("message_index_session", "assistant", content="interrupted response")
        finally:
            db.close()

        resp = web_client.get("/api/sessions/message_index_session/messages?limit=2")
        assert resp.status_code == 200
        messages = resp.json()["messages"]
        assert [m["role"] for m in messages] == ["user", "assistant"]
        assert [m["message_index"] for m in messages] == [2, 3]

    def test_conversation_message_rehydrates_stored_web_session(self, web_client, monkeypatch):
        import core.run_agent as run_agent
        import spark_cli.web_server as web_server
        from core.spark_state import SessionDB

        class FakeAgent:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)
                self.session_id = kwargs["session_id"]

        db = SessionDB()
        try:
            db.create_session("stored_web", source="web", model="m1")
            db.append_message("stored_web", "user", content="hello")
            db.append_message("stored_web", "assistant", content="hi")
        finally:
            db.close()

        captured = {}

        def fake_run(agent, user_message, conversation_history=None, context_items=None):
            captured["agent"] = agent
            captured["user_message"] = user_message
            captured["history"] = conversation_history
            captured["context_items"] = context_items

        monkeypatch.setattr(run_agent, "AIAgent", FakeAgent)
        monkeypatch.setattr(web_server, "_run_web_agent_turn", fake_run)

        resp = web_client.post("/api/conversations/stored_web/messages", json={"message": "again"})
        assert resp.status_code == 200
        assert resp.json()["session_id"] == "stored_web"
        assert "stored_web" in web_server._web_agents
        assert web_server._web_agents["stored_web"].model == "test-model"
        assert _wait_for(lambda: "history" in captured)
        assert captured["user_message"] == "again"
        assert captured["history"] == [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]

    def test_conversation_message_rehydrates_non_web_session(self, web_client, monkeypatch):
        import core.run_agent as run_agent
        import spark_cli.web_server as web_server
        from core.spark_state import SessionDB

        class FakeAgent:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)
                self.session_id = kwargs["session_id"]

        db = SessionDB()
        try:
            db.create_session("stored_cli", source="cli", model="m1")
            db.append_message("stored_cli", "user", content="hello from tui")
            db.append_message("stored_cli", "assistant", content="hi")
        finally:
            db.close()

        captured = {}

        def fake_run(agent, user_message, conversation_history=None, context_items=None):
            captured["agent"] = agent
            captured["user_message"] = user_message
            captured["history"] = conversation_history
            captured["context_items"] = context_items

        monkeypatch.setattr(run_agent, "AIAgent", FakeAgent)
        monkeypatch.setattr(web_server, "_run_web_agent_turn", fake_run)

        resp = web_client.post("/api/conversations/stored_cli/messages", json={"message": "continue"})
        assert resp.status_code == 200
        assert resp.json()["session_id"] == "stored_cli"
        assert "stored_cli" in web_server._web_agents
        assert web_server._web_agents["stored_cli"].model == "test-model"
        assert _wait_for(lambda: "history" in captured)
        assert captured["user_message"] == "continue"
        assert captured["history"] == [
            {"role": "user", "content": "hello from tui"},
            {"role": "assistant", "content": "hi"},
        ]

    def test_conversation_message_continues_latest_compressed_leaf(self, web_client, monkeypatch):
        import core.run_agent as run_agent
        import spark_cli.web_server as web_server
        from core.spark_state import SessionDB

        class FakeAgent:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)
                self.session_id = kwargs["session_id"]

        db = SessionDB()
        try:
            db.create_session("compressed_parent", source="web", model="m1")
            db.append_message("compressed_parent", "user", content="old fact")
            db.append_message("compressed_parent", "assistant", content="old answer")
            db.end_session("compressed_parent", "compression")
            db.create_session(
                "compressed_leaf",
                source="web",
                model="m1",
                parent_session_id="compressed_parent",
            )
            db.append_message("compressed_leaf", "system", content="summary of old fact")
            db.append_message("compressed_leaf", "user", content="newer fact")
            db.append_message("compressed_leaf", "assistant", content="newer answer")
        finally:
            db.close()

        captured = {}

        def fake_run(agent, user_message, conversation_history=None, context_items=None):
            captured["agent"] = agent
            captured["user_message"] = user_message
            captured["history"] = conversation_history
            captured["context_items"] = context_items

        monkeypatch.setattr(run_agent, "AIAgent", FakeAgent)
        monkeypatch.setattr(web_server, "_run_web_agent_turn", fake_run)

        resp = web_client.post(
            "/api/conversations/compressed_parent/messages",
            json={"message": "recall"},
        )

        assert resp.status_code == 200
        assert resp.json()["session_id"] == "compressed_leaf"
        assert "compressed_leaf" in web_server._web_agents
        assert "compressed_parent" not in web_server._web_agents
        assert _wait_for(lambda: "history" in captured)
        assert captured["agent"].session_id == "compressed_leaf"
        assert captured["user_message"] == "recall"
        assert captured["history"] == [
            {"role": "system", "content": "summary of old fact"},
            {"role": "user", "content": "newer fact"},
            {"role": "assistant", "content": "newer answer"},
        ]

    def test_web_turn_fallback_persists_missing_messages(self, web_client):
        import spark_cli.web_server as web_server
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            db.create_session("fallback_web", source="web", model="m1")
        finally:
            db.close()

        web_server._persist_web_turn_if_missing(
            "fallback_web",
            "Tell me a joke",
            {"final_response": "A small deterministic reply."},
            before_message_count=0,
        )

        db2 = SessionDB()
        try:
            msgs = db2.get_messages("fallback_web")
            row = db2.list_sessions_rich(source="web", limit=10)[0]
            assert [m["role"] for m in msgs] == ["user", "assistant"]
            assert msgs[0]["content"] == "Tell me a joke"
            assert msgs[1]["content"] == "A small deterministic reply."
            assert row["preview"] == "Tell me a joke"
            assert row["message_count"] == 2
        finally:
            db2.close()

    def test_web_turn_fallback_strips_ansi_from_assistant_response(self, web_client):
        import spark_cli.web_server as web_server
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            db.create_session("ansi_fallback_web", source="web", model="m1")
        finally:
            db.close()

        web_server._persist_web_turn_if_missing(
            "ansi_fallback_web",
            "Run colored output",
            {"final_response": "\x1b[32mDone\x1b[0m"},
            before_message_count=0,
        )

        db2 = SessionDB()
        try:
            msgs = db2.get_messages("ansi_fallback_web")
            assert [m["role"] for m in msgs] == ["user", "assistant"]
            assert msgs[1]["content"] == "Done"
            assert "\x1b[" not in msgs[1]["content"]
        finally:
            db2.close()

    def test_web_turn_fallback_completes_partially_persisted_turn(self, web_client):
        import spark_cli.web_server as web_server
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            db.create_session("already_persisted_web", source="web", model="m1")
            db.append_message("already_persisted_web", "user", content="Already saved")
        finally:
            db.close()

        web_server._persist_web_turn_if_missing(
            "already_persisted_web",
            "Already saved",
            {"final_response": "Should not be added"},
            before_message_count=0,
        )

        db2 = SessionDB()
        try:
            msgs = db2.get_messages("already_persisted_web")
            assert len(msgs) == 2
            assert msgs[0]["content"] == "Already saved"
            assert msgs[1]["role"] == "assistant"
            assert msgs[1]["content"] == "Should not be added"
        finally:
            db2.close()

    def test_web_turn_fallback_materializes_large_markdown_response(self, web_client):
        import spark_cli.web_server as web_server
        from core.spark_state import SessionDB

        full_report = "# Big Report\n\n" + ("body paragraph\n\n" * 2_000)

        db = SessionDB()
        try:
            db.create_session("artifact_web", source="web", model="m1")
        finally:
            db.close()

        web_server._persist_web_turn_if_missing(
            "artifact_web",
            "Write a comprehensive markdown report",
            {"final_response": full_report},
            before_message_count=0,
        )

        db2 = SessionDB()
        try:
            msgs = db2.get_messages("artifact_web")
            assert [m["role"] for m in msgs] == ["user", "assistant"]
            assert msgs[0]["content"] == "Write a comprehensive markdown report"
            assert "Open the markdown file" in msgs[1]["content"]
            assert "No content was hidden or discarded" in msgs[1]["content"]
            assert len(msgs[1]["content"]) < len(full_report)

            artifact_root = web_server.get_spark_home() / "workspace" / "chat-artifacts" / "artifact_web"
            files = list(artifact_root.glob("*.md"))
            assert len(files) == 1
            assert files[0].read_text(encoding="utf-8") == full_report
        finally:
            db2.close()

    def test_web_turn_fallback_strips_internal_delivery_instruction(self, web_client):
        import spark_cli.web_server as web_server
        from core.spark_state import SessionDB

        raw_message = "Write a comprehensive markdown report"
        injected_message = web_server._with_long_document_delivery_instruction(raw_message)

        db = SessionDB()
        try:
            db.create_session("artifact_instruction_web", source="web", model="m1")
            db.append_message("artifact_instruction_web", "user", content=injected_message)
        finally:
            db.close()

        web_server._persist_web_turn_if_missing(
            "artifact_instruction_web",
            raw_message,
            {"final_response": "Short acknowledgement."},
            before_message_count=0,
        )

        db2 = SessionDB()
        try:
            msgs = db2.get_messages("artifact_instruction_web")
            assert [m["role"] for m in msgs] == ["user", "assistant"]
            assert msgs[0]["content"] == raw_message
            assert "Spark delivery instruction" not in msgs[0]["content"]
            assert msgs[1]["content"] == "Short acknowledgement."
        finally:
            db2.close()

    def test_web_turn_fallback_replaces_persisted_large_assistant_with_artifact(self, web_client):
        import spark_cli.web_server as web_server
        from core.spark_state import SessionDB

        full_report = "# Persisted Report\n\n" + ("body paragraph\n\n" * 2_000)

        db = SessionDB()
        try:
            db.create_session("artifact_replace_web", source="web", model="m1")
            db.append_message("artifact_replace_web", "user", content="Write a long report")
            db.append_message("artifact_replace_web", "assistant", content=full_report)
        finally:
            db.close()

        web_server._persist_web_turn_if_missing(
            "artifact_replace_web",
            "Write a long report",
            {"final_response": full_report},
            before_message_count=0,
        )

        db2 = SessionDB()
        try:
            msgs = db2.get_messages("artifact_replace_web")
            assert len(msgs) == 2
            assert msgs[1]["role"] == "assistant"
            assert "Open the markdown file" in msgs[1]["content"]
            assert full_report not in msgs[1]["content"]

            artifact_root = (
                web_server.get_spark_home()
                / "workspace"
                / "chat-artifacts"
                / "artifact_replace_web"
            )
            files = list(artifact_root.glob("*.md"))
            assert len(files) == 1
            assert files[0].read_text(encoding="utf-8") == full_report
        finally:
            db2.close()

    def test_web_turn_fallback_does_not_duplicate_persisted_assistant(self, web_client):
        import spark_cli.web_server as web_server
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            db.create_session("fully_persisted_web", source="web", model="m1")
            db.append_message("fully_persisted_web", "user", content="Already saved")
            db.append_message("fully_persisted_web", "assistant", content="Already answered")
        finally:
            db.close()

        web_server._persist_web_turn_if_missing(
            "fully_persisted_web",
            "Already saved",
            {"final_response": "Should not be added"},
            before_message_count=0,
        )

        db2 = SessionDB()
        try:
            msgs = db2.get_messages("fully_persisted_web")
            assert len(msgs) == 2
            assert msgs[0]["content"] == "Already saved"
            assert msgs[1]["content"] == "Already answered"
        finally:
            db2.close()

    def test_cached_web_agent_validation_matches_db_history(self, web_client):
        import spark_cli.web_server as web_server
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            db.create_session("cache_ok", source="web", model="m1")
            db.append_message("cache_ok", "user", content="hello")
            db.append_message("cache_ok", "assistant", content="hi")
            history = db.get_messages_as_conversation("cache_ok")
        finally:
            db.close()

        agent = MagicMock()
        agent._session_messages = list(history)

        assert web_server._cached_web_agent_matches_history("cache_ok", agent, history) is True

    def test_cached_web_agent_followup_does_not_replay_prior_history(self, web_client):
        import spark_cli.web_server as web_server
        from core.spark_state import SessionDB

        sid = "cached_cursor_web"
        db = SessionDB()
        try:
            db.create_session(sid, source="web", model="m1")
            db.append_message(sid, "user", content="hello")
            db.append_message(sid, "assistant", content="hi")
            history = db.get_messages_as_conversation(sid)
        finally:
            db.close()

        class CachedAgent:
            session_id = sid
            model = "test-model"

            def __init__(self, initial_history):
                self._session_messages = list(initial_history)
                self.messages = list(initial_history)
                self._last_flushed_db_idx = 0

            def run_conversation(self, user_message, conversation_history=None):
                assert conversation_history is None
                messages = list(self._session_messages)
                messages.append({"role": "user", "content": user_message})
                messages.append({"role": "assistant", "content": "second answer"})

                db = SessionDB()
                try:
                    for msg in messages[self._last_flushed_db_idx:]:
                        db.append_message(sid, msg["role"], content=msg["content"])
                finally:
                    db.close()

                self._session_messages = messages
                self.messages = list(messages)
                self._last_flushed_db_idx = len(messages)
                return {"final_response": "second answer", "messages": messages}

        agent = CachedAgent(history)
        web_server._hydrate_web_agent_from_history(agent, history)

        db = SessionDB()
        try:
            eager_user_id = db.append_message(sid, "user", content="again")
            before_message_count = len(db.get_messages(sid))
        finally:
            db.close()

        result = agent.run_conversation("again", conversation_history=None)
        web_server._persist_web_turn_if_missing(
            sid,
            "again",
            result,
            before_message_count,
            eager_user_id=eager_user_id,
        )

        db2 = SessionDB()
        try:
            assert [m["content"] for m in db2.get_messages(sid)] == [
                "hello",
                "hi",
                "again",
                "second answer",
            ]
        finally:
            db2.close()

    def test_cached_web_agent_validation_rejects_stale_context(self, web_client):
        import spark_cli.web_server as web_server
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            db.create_session("cache_stale", source="web", model="m1")
            db.append_message("cache_stale", "user", content="first")
            db.append_message("cache_stale", "assistant", content="answer")
            history = db.get_messages_as_conversation("cache_stale")
        finally:
            db.close()

        agent = MagicMock()
        agent._session_messages = [{"role": "user", "content": "different"}]

        assert web_server._cached_web_agent_matches_history("cache_stale", agent, history) is False

    def test_turn_done_payload_includes_reconciliation_metadata(self, web_client):
        import spark_cli.web_server as web_server
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            db.create_session("turn_done_meta", source="web", model="m1")
            db.append_message("turn_done_meta", "user", content="hello")
            assistant_id = db.append_message("turn_done_meta", "assistant", content="hi")
        finally:
            db.close()

        payload = web_server._turn_done_payload(
            {
                "input_tokens": 3,
                "output_tokens": 4,
                "cache_read_tokens": 5,
                "cache_write_tokens": 6,
                "estimated_cost_usd": 0.01,
                "model": "m1",
            },
            "turn_done_meta",
        )

        assert payload["session_id"] == "turn_done_meta"
        assert payload["message_count"] == 2
        assert payload["final_assistant_message_id"] == assistant_id
        assert payload["final_assistant_present"] is True
        assert payload["tokens"]["input"] == 3
        assert payload["model"] == "m1"

    def test_interrupted_boundary_persists_after_dangling_user(self, web_client):
        import spark_cli.web_server as web_server
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            db.create_session("interrupt_boundary", source="web", model="m1")
            db.append_message("interrupt_boundary", "user", content="long request")
        finally:
            db.close()

        web_server._persist_interrupted_turn_boundary("interrupt_boundary", "new direction")

        db2 = SessionDB()
        try:
            msgs = db2.get_messages("interrupt_boundary")
            assert [m["role"] for m in msgs] == ["user", "assistant"]
            assert "interrupted" in msgs[-1]["content"].lower()
        finally:
            db2.close()

    def test_interrupt_requires_agent(self, web_client):
        resp = web_client.post("/api/conversations/none/interrupt", json={})
        assert resp.status_code == 404

    def test_interrupt_calls_agent(self, web_client, monkeypatch):
        import spark_cli.web_server as web_server

        agent = MagicMock()
        web_server._web_agents["s1"] = agent
        resp = web_client.post("/api/conversations/s1/interrupt", json={"message": "stop"})
        assert resp.status_code == 200
        agent.interrupt.assert_called_once_with("stop")

    def test_interrupt_request_leaves_turn_active_until_task_clears(self, web_client):
        import spark_cli.web_server as web_server

        agent = MagicMock()
        web_server._web_agents["s_active"] = agent
        web_server._mark_web_turn_active("s_active", status="Running…", phase="streaming")
        try:
            resp = web_client.post("/api/conversations/s_active/interrupt", json={"message": "redirect"})
            assert resp.status_code == 200

            status = web_client.get("/api/conversations/s_active/turn-status")
            assert status.status_code == 200
            data = status.json()
            assert data["turn_active"] is True
            assert data["interrupt_requested"] is True
            assert data["phase"] == "redirecting"
        finally:
            web_server._clear_web_turn("s_active")

    def test_interrupt_resolves_latest_descendant_agent(self, web_client):
        import spark_cli.web_server as web_server
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            db.create_session("parent_session", source="web", model="m1")
            db.create_session("child_session", source="web", model="m1", parent_session_id="parent_session")

            def _mark_compressed(conn):
                conn.execute("UPDATE sessions SET end_reason = 'compression' WHERE id = ?", ("parent_session",))

            db._execute_write(_mark_compressed)
        finally:
            db.close()

        agent = MagicMock()
        web_server._web_agents["child_session"] = agent
        web_server._mark_web_turn_active("child_session")
        try:
            resp = web_client.post("/api/conversations/parent_session/interrupt", json={"message": "stop latest"})
            assert resp.status_code == 200
            assert resp.json()["session_id"] == "child_session"
            agent.interrupt.assert_called_once_with("stop latest")
        finally:
            web_server._clear_web_turn("child_session")

    def test_interrupt_endpoint_persists_boundary_when_user_is_dangling(self, web_client):
        import spark_cli.web_server as web_server
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            db.create_session("s_interrupt", source="web", model="m1")
            db.append_message("s_interrupt", "user", content="please continue")
        finally:
            db.close()

        agent = MagicMock()
        web_server._web_agents["s_interrupt"] = agent

        resp = web_client.post("/api/conversations/s_interrupt/interrupt", json={"message": "redirect"})
        assert resp.status_code == 200

        db2 = SessionDB()
        try:
            msgs = db2.get_messages("s_interrupt")
            assert msgs[-1]["role"] == "assistant"
            assert "interrupted" in msgs[-1]["content"].lower()
        finally:
            db2.close()

    def test_model_switch_409_when_streaming(self, web_client, monkeypatch):
        import spark_cli.web_server as web_server

        agent = MagicMock()
        web_server._web_agents["s1"] = agent
        web_server._mark_web_turn_active("s1")
        resp = web_client.post("/api/conversations/s1/model", json={"model": "anthropic/claude-sonnet-4.6"})
        assert resp.status_code == 409
        web_server._clear_web_turn("s1")

    def test_turn_status_uses_active_turn_without_queue(self, web_client):
        import spark_cli.web_server as web_server

        web_server._mark_web_turn_active("s_streaming", status="Running…", phase="streaming")
        try:
            resp = web_client.get("/api/conversations/s_streaming/turn-status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["turn_active"] is True
            assert data["status"] == "Running…"
            assert data["phase"] == "streaming"
            assert data["started_at"] is not None
            assert data["last_event_at"] is not None
        finally:
            web_server._clear_web_turn("s_streaming")

    def test_turn_status_ignores_stale_queue_after_turn_done(self, web_client):
        import asyncio

        import spark_cli.web_server as web_server

        web_server._web_queues["s_done"] = asyncio.Queue()
        try:
            resp = web_client.get("/api/conversations/s_done/turn-status")
            assert resp.status_code == 200
            assert resp.json()["turn_active"] is False
        finally:
            web_server._web_queues.pop("s_done", None)

    def test_status_exposes_streaming_health_metrics(self, web_client):
        import spark_cli.web_server as web_server

        web_server._streaming_pipeline_metrics.record_loop_lag(0.123)
        resp = web_client.get("/api/status")
        assert resp.status_code == 200
        health = resp.json()["streaming_health"]
        assert health["loop_lag_seconds"] == 0.123
        assert "checkpoint_writes" in health
        assert "executor_queued" in health
        assert "agent_cache_size" in health

    def test_stream_snapshot_endpoint_uses_thread_offload(self, web_client, monkeypatch):
        import spark_cli.web_server as web_server

        calls = []

        async def fake_to_thread(fn, *args, **kwargs):
            calls.append(fn.__name__)
            return fn(*args, **kwargs)

        monkeypatch.setattr(web_server.asyncio, "to_thread", fake_to_thread)
        resp = web_client.get("/api/conversations/snapshot-threaded/stream-snapshot")
        assert resp.status_code == 200
        assert calls == ["_conversation_stream_snapshot_payload"]

    def test_agent_cache_eviction_skips_active_turn(self, web_client, monkeypatch):
        import spark_cli.web_server as web_server

        monkeypatch.setattr(web_server, "_web_agent_cache_limit", lambda: 1)
        inactive = MagicMock()
        active = MagicMock()
        web_server._store_web_agent("inactive-agent", inactive, {"model": "m"})
        web_server._mark_web_turn_active("active-agent")
        try:
            web_server._store_web_agent("active-agent", active, {"model": "m"})
            assert "active-agent" in web_server._web_agents
            assert "inactive-agent" not in web_server._web_agents
        finally:
            web_server._clear_web_turn("active-agent")

    def test_completed_conversation_without_stream_consumer_is_not_active(self, web_client, monkeypatch):
        import time

        import spark_cli.web_server as web_server

        class FakeAgent:
            session_id = "pending"

        def fake_new_agent(**kwargs):
            agent = FakeAgent()
            agent.session_id = kwargs["session_id"]
            return agent

        monkeypatch.setattr(web_server, "_new_web_agent", fake_new_agent)
        monkeypatch.setattr(web_server, "_run_web_agent_turn", lambda *_args, **_kwargs: {"final_response": "done"})
        monkeypatch.setattr(web_server, "_maybe_auto_title_web", lambda *_args, **_kwargs: None)

        resp = web_client.post("/api/conversations", json={"message": "hi"})
        assert resp.status_code == 200
        session_id = resp.json()["session_id"]

        deadline = time.time() + 2.0
        while time.time() < deadline:
            status = web_client.get(f"/api/conversations/{session_id}/turn-status")
            assert status.status_code == 200
            if status.json()["turn_active"] is False:
                break
            time.sleep(0.02)
        else:
            pytest.fail("completed web turn still reported active")

        assert session_id not in web_server._web_queues
        status = web_client.get(f"/api/conversations/{session_id}/turn-status")
        assert status.json()["turn_active"] is False

    def test_conversation_message_rejects_active_resolved_session_before_retargeting_callbacks(self, web_client, monkeypatch):
        import spark_cli.web_server as web_server
        from core.spark_state import SessionDB

        class FakeAgent:
            def __init__(self, session_id):
                self.session_id = session_id
                self.stream_delta_callback = "original"

        db = SessionDB()
        try:
            db.create_session("active_followup", source="web", model="m1")
            db.append_message("active_followup", "user", content="hello")
            db.append_message("active_followup", "assistant", content="hi")
        finally:
            db.close()

        agent = FakeAgent("active_followup")
        web_server._web_agents["active_followup"] = agent
        web_server._web_agent_signatures["active_followup"] = {
            "model": "test-model",
        }
        web_server._mark_web_turn_active(
            "active_followup",
            status="Running…",
            phase="streaming",
            active_agent_session_id="active_followup",
        )
        monkeypatch.setattr(
            web_server,
            "_resolve_web_turn_route",
            lambda _msg: {
                "model": "test-model",
                "runtime": {},
                "signature": {"model": "test-model"},
                "request_overrides": None,
            },
        )

        try:
            resp = web_client.post(
                "/api/conversations/active_followup/messages",
                json={"message": "second turn"},
            )

            assert resp.status_code == 409
            assert agent.stream_delta_callback == "original"
            assert "active_followup" not in web_server._web_queues
        finally:
            web_server._clear_web_turn("active_followup")
            web_server._web_agents.pop("active_followup", None)
            web_server._web_agent_signatures.pop("active_followup", None)

    def test_turn_status_active_immediately_after_conversation_accepts(self, web_client, monkeypatch):
        import spark_cli.web_server as web_server

        class FakeAgent:
            session_id = "pending"

        def fake_new_agent(**kwargs):
            agent = FakeAgent()
            agent.session_id = kwargs["session_id"]
            return agent

        created_tasks = []

        monkeypatch.setattr(web_server, "_new_web_agent", fake_new_agent)
        monkeypatch.setattr(web_server.asyncio, "create_task", lambda coro: created_tasks.append(coro))
        monkeypatch.setattr(web_server, "_maybe_auto_title_web", lambda *_args, **_kwargs: None)

        try:
            resp = web_client.post("/api/conversations", json={"message": "hi"})
            assert resp.status_code == 200
            session_id = resp.json()["session_id"]

            status = web_client.get(f"/api/conversations/{session_id}/turn-status")
            assert status.status_code == 200
            assert status.json()["turn_active"] is True
        finally:
            for coro in created_tasks:
                coro.close()

    def test_backend_exception_publishes_turn_done_and_clears_active(self, web_client, monkeypatch):
        import time

        import spark_cli.web_server as web_server

        class FakeAgent:
            session_id = "pending"

        def fake_new_agent(**kwargs):
            agent = FakeAgent()
            agent.session_id = kwargs["session_id"]
            return agent

        events = []
        original_publish = web_server._publish_event

        def capture_event(topic, data, session_id=None):
            events.append((topic, data, session_id))
            return original_publish(topic, data, session_id)

        def explode(*_args, **_kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(web_server, "_new_web_agent", fake_new_agent)
        monkeypatch.setattr(web_server, "_run_web_agent_turn", explode)
        monkeypatch.setattr(web_server, "_maybe_auto_title_web", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(web_server, "_publish_event", capture_event)

        resp = web_client.post("/api/conversations", json={"message": "hi"})
        assert resp.status_code == 200
        session_id = resp.json()["session_id"]

        deadline = time.time() + 2.0
        while time.time() < deadline:
            status = web_client.get(f"/api/conversations/{session_id}/turn-status")
            assert status.status_code == 200
            if status.json()["turn_active"] is False:
                break
            time.sleep(0.02)
        else:
            pytest.fail("failed web turn still reported active")

        done = [event for event in events if event[0] == "chat.turn_done"]
        assert done
        assert done[-1][1]["backend_error_class"] == "RuntimeError"

    def test_webview_diagnostics_reports_sidecar_and_activity_monitor_note(self, web_client):
        resp = web_client.get(
            "/api/diagnostics/webview?active_session_id=s1&safe_mode=true&recent_long_task_count=4&connection_mode=local"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["sidecar_pid"] > 0
        assert data["safe_mode"] is True
        assert data["recent_long_task_count"] == 4
        assert data["connection_mode"] == "local"
        assert "127.0.0.1:9119" in data["activity_monitor_process_name_note"]

    def test_webview_diagnostics_ignores_stale_queue_after_turn_done(self, web_client):
        import asyncio

        import spark_cli.web_server as web_server

        web_server._web_queues["s_done"] = asyncio.Queue()
        try:
            resp = web_client.get("/api/diagnostics/webview?active_session_id=s_done")
            assert resp.status_code == 200
            assert resp.json()["active_turn"] is False
        finally:
            web_server._web_queues.pop("s_done", None)

    def test_model_switch_persists_global_and_closes_cached_agent(self, web_client, monkeypatch):
        import spark_cli.web_server as web_server
        from spark_cli.model_switch import ModelSwitchResult

        agent = MagicMock()
        agent.model = "old"
        web_server._web_agents["s1"] = agent
        saved = {}

        monkeypatch.setattr(
            "spark_cli.model_switch.switch_model",
            lambda **_kw: ModelSwitchResult(
                success=True,
                new_model="new/model",
                target_provider="openrouter",
            ),
        )

        def fake_write(result):
            saved["model"] = result.new_model
            return {"model": {"default": result.new_model, "provider": result.target_provider}}

        monkeypatch.setattr("spark_cli.model_config.write_model_switch_result", fake_write)
        resp = web_client.post("/api/conversations/s1/model", json={"model": "new/model"})
        assert resp.status_code == 200
        assert saved["model"] == "new/model"
        assert "s1" not in web_server._web_agents

    def test_approval_no_pending(self, web_client):
        resp = web_client.post("/api/conversations/s1/approval", json={"choice": "once"})
        assert resp.status_code == 404

    def test_approval_resolves_pending(self, web_client, monkeypatch):
        import spark_cli.web_server as web_server
        from tools import approval as approval_mod

        session_key = "sapprove"
        entry = approval_mod._ApprovalEntry({"command": "echo", "description": "test"})
        with approval_mod._lock:
            approval_mod._gateway_queues[session_key] = [entry]

        resp = web_client.post(f"/api/conversations/{session_key}/approval", json={"choice": "once"})
        assert resp.status_code == 200
        assert entry.result == "once"
        web_server._event_subscribers.clear()

    def test_fork_requires_session(self, web_client):
        resp = web_client.post("/api/conversations/missing/fork", json={})
        assert resp.status_code == 404

    def test_fork_copies_messages(self, web_client):
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            sid = "20260101_testsrc"
            db.create_session(sid, source="web", model="m1")
            db.append_message(sid, "user", content="hello")
            db.append_message(sid, "assistant", content="hi")
        finally:
            db.close()

        resp = web_client.post(f"/api/conversations/{sid}/fork", json={"from_message_index": 2})
        assert resp.status_code == 200
        new_id = resp.json()["session_id"]
        assert new_id != sid

        db2 = SessionDB()
        try:
            msgs = db2.get_messages(new_id)
            assert len(msgs) == 2
            assert msgs[0]["role"] == "user"
            assert msgs[1]["role"] == "assistant"
        finally:
            db2.close()
