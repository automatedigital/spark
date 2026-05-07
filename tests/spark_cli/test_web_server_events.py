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

    import spark_cli.web_server as web_server

    monkeypatch.setattr(web_server, "_web_event_loop", asyncio.get_event_loop())
    web_server._event_subscribers.clear()
    web_server._web_streaming.clear()
    web_server._web_agents.clear()
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

    def test_model_switch_409_when_streaming(self, web_client, monkeypatch):
        import spark_cli.web_server as web_server

        agent = MagicMock()
        web_server._web_agents["s1"] = agent
        web_server._web_streaming.add("s1")
        resp = web_client.post("/api/conversations/s1/model", json={"model": "anthropic/claude-sonnet-4.6"})
        assert resp.status_code == 409
        web_server._web_streaming.discard("s1")

    def test_model_switch_updates_agent(self, web_client, monkeypatch):
        import spark_cli.web_server as web_server

        agent = MagicMock()
        agent.model = "old"
        web_server._web_agents["s1"] = agent
        resp = web_client.post("/api/conversations/s1/model", json={"model": "new/model"})
        assert resp.status_code == 200
        assert agent.model == "new/model"

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
