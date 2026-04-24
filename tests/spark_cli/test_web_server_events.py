"""Tests for web UI SSE event bus and conversation control endpoints."""

import asyncio
import json
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
