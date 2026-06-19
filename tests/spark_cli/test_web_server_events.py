"""Tests for web UI SSE event bus and conversation control endpoints."""

import asyncio
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
    web_server._web_streaming.clear()
    web_server._web_agents.clear()
    web_server._web_agent_signatures.clear()
    web_server._web_queues.clear()

    return TestClient(web_server.app)


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


class TestConversationModels:
    def test_get_conversation_models(self, web_client):
        resp = web_client.get("/api/conversations/models")
        assert resp.status_code == 200
        data = resp.json()
        assert "models" in data
        assert len(data["models"]) >= 1
        assert "id" in data["models"][0]


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
        assert "web_child_session" in ids
        assert "cli_session" not in ids
        assert resp.json()["total"] == 2

    def test_session_search_can_filter_to_web_source(self, web_client):
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            db.create_session("web_search_session", source="web", model="m1")
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

        def fake_run(agent, user_message, conversation_history=None):
            captured["agent"] = agent
            captured["user_message"] = user_message
            captured["history"] = conversation_history

        monkeypatch.setattr(run_agent, "AIAgent", FakeAgent)
        monkeypatch.setattr(web_server, "_run_web_agent_turn", fake_run)

        resp = web_client.post("/api/conversations/stored_web/messages", json={"message": "again"})
        assert resp.status_code == 200
        assert resp.json()["session_id"] == "stored_web"
        assert "stored_web" in web_server._web_agents
        assert web_server._web_agents["stored_web"].model == "test-model"

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

        def fake_run(agent, user_message, conversation_history=None):
            captured["agent"] = agent
            captured["user_message"] = user_message
            captured["history"] = conversation_history

        monkeypatch.setattr(run_agent, "AIAgent", FakeAgent)
        monkeypatch.setattr(web_server, "_run_web_agent_turn", fake_run)

        resp = web_client.post("/api/conversations/stored_cli/messages", json={"message": "continue"})
        assert resp.status_code == 200
        assert resp.json()["session_id"] == "stored_cli"
        assert "stored_cli" in web_server._web_agents
        assert web_server._web_agents["stored_cli"].model == "test-model"

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
        web_server._web_streaming.add("s1")
        resp = web_client.post("/api/conversations/s1/model", json={"model": "anthropic/claude-sonnet-4.6"})
        assert resp.status_code == 409
        web_server._web_streaming.discard("s1")

    def test_turn_status_uses_web_streaming_without_queue(self, web_client):
        import spark_cli.web_server as web_server

        web_server._web_streaming.add("s_streaming")
        try:
            resp = web_client.get("/api/conversations/s_streaming/turn-status")
            assert resp.status_code == 200
            assert resp.json()["turn_active"] is True
        finally:
            web_server._web_streaming.discard("s_streaming")

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

        assert session_id in web_server._web_queues
        status = web_client.get(f"/api/conversations/{session_id}/turn-status")
        assert status.json()["turn_active"] is False

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
