"""Real persistence at the cache boundary; provider requests stay byte-equivalent."""

import asyncio
import json
import threading
import time
from types import SimpleNamespace

import pytest

from core.spark_state import SessionDB
from spark_cli import web_server as web
from spark_cli.chat_preparation import load_chat_preparation
from spark_cli.web_agent_cache import retained_context_bytes

pytestmark = pytest.mark.serial
CALLBACKS = dict.fromkeys((
    "token_callback", "tool_start_callback", "tool_complete_callback",
    "reasoning_callback", "status_callback", "session_migrated_callback", "subagent_event_callback",
))
ROUTE = {"model": "fixture", "runtime": {}, "signature": "fixture"}


@pytest.fixture
def cache(monkeypatch):
    for mapping in (
        web._web_agents, web._web_agent_signatures, web._web_agent_last_used,
        web._web_agent_history_revisions, web._web_warm_recent,
        web._web_active_turns, web._web_turn_aliases,
    ):
        mapping.clear()
    web._web_warm_inflight.clear()
    monkeypatch.setattr(web, "_web_agent_cache_policy", lambda: (1800, 64 * 1024 * 1024))
    monkeypatch.setattr(web, "_resolve_web_turn_route", lambda *a, **kw: ROUTE)
    created, closed = [], []

    def new(**kw):
        web._close_web_agent(kw["session_id"])
        agent = SimpleNamespace(
            session_id=kw["session_id"], _session_db=None,
            _active_children=[], _active_children_lock=threading.Lock(),
            close=lambda: closed.append(kw["session_id"]),
        )
        created.append(agent)
        web._store_web_agent(agent.session_id, agent, kw["signature"])
        return agent

    monkeypatch.setattr(web, "_new_web_agent", new)
    db = SessionDB()
    db.create_session("cached", "web", model="fixture")
    db.append_message("cached", "user", "Unicode é 中 👋")
    db.append_message("cached", "assistant", "answer")
    db.close()
    yield created, closed
    for sid in list(web._web_agents):
        web._close_web_agent(sid)
    web._web_warm_inflight.clear()


def warm(sid="cached", route=None):
    preparation = load_chat_preparation(sid)
    web._web_warm_inflight.add(sid)
    try:
        return web._warm_web_agent(preparation, route or ROUTE)
    finally:
        web._web_warm_inflight.discard(sid)
        web._evict_web_agent_cache_if_needed()


def request_bytes(agent, history, message):
    return json.dumps(
        [*(agent._session_messages if history is None else history), {"role": "user", "content": message}],
        ensure_ascii=False, sort_keys=True,
    ).encode()


def test_verified_warm_send_skips_full_read_and_excludes_accepted_prompt(cache, monkeypatch):
    assert warm() is False
    preparation = load_chat_preparation("cached")
    expected = preparation.history()
    # history() reopens the session, but does not change transcript revision.
    preparation = load_chat_preparation("cached")
    db = SessionDB()
    db.append_message("cached", "user", "accepted prompt")
    db.close()
    monkeypatch.setattr(SessionDB, "get_messages_as_conversation", lambda *a: pytest.fail("warm hit read full history"))
    prepared = preparation.prepare_agent(web, "accepted prompt", CALLBACKS, lambda: False)
    assert prepared.history is None
    assert request_bytes(prepared.agent, prepared.history, "accepted prompt") == json.dumps(
        [*expected, {"role": "user", "content": "accepted prompt"}],
        ensure_ascii=False, sort_keys=True,
    ).encode()
    assert "cached" not in web._web_agent_history_revisions


def test_repeated_warm_hit_does_not_read_history(cache, monkeypatch):
    assert warm() is False
    monkeypatch.setattr(SessionDB, "get_messages_as_conversation", lambda *a: pytest.fail("unchanged warm rehydrated"))
    assert warm() is True


@pytest.mark.parametrize("operation", ["update", "delete", "append", "move"])
def test_external_sql_writer_invalidates_warm_revision(cache, operation):
    warm()
    old = web._web_agents["cached"]
    db = SessionDB()
    if operation == "update":
        # Same role/count/content length defeats the old count/last-user check.
        db._conn.execute("UPDATE messages SET content = 'ANSWER' WHERE session_id = 'cached' AND role = 'assistant'")
    elif operation == "delete":
        db._conn.execute("DELETE FROM messages WHERE session_id = 'cached' AND role = 'assistant'")
    elif operation == "move":
        db.create_session("other", "web")
        db._conn.execute("UPDATE messages SET session_id = 'other' WHERE session_id = 'cached' AND role = 'assistant'")
    else:
        db.append_message("cached", "assistant", "external append")
    db._conn.commit()
    expected = db.get_messages_as_conversation("cached")
    db.close()
    assert warm() is False
    assert web._web_agents["cached"] is old
    assert old._session_messages == expected
    assert warm() is True


def test_destructive_write_after_acceptance_prevents_fast_path(cache):
    warm()
    preparation = load_chat_preparation("cached")
    db = SessionDB()
    db.append_message("cached", "user", "accepted")
    db._conn.execute("UPDATE messages SET content = 'edited' WHERE session_id = 'cached' AND role = 'assistant'")
    db._conn.commit()
    db.close()
    history, hit = web._web_agent_history_for_preparation(preparation, web._web_agents["cached"], "fixture")
    assert not hit
    assert history == [{"role": "user", "content": "Unicode é 中 👋"}, {"role": "assistant", "content": "edited"}]


def test_route_change_disposes_idle_agent_and_compression_resolves_leaf(cache):
    created, closed = cache
    warm()
    assert warm(route={**ROUTE, "signature": "other-route"}) is False
    assert len(created) == 2 and closed == ["cached"]
    db = SessionDB()
    db.end_session("cached", "compression")
    db.create_session("compressed", "web", model="fixture", parent_session_id="cached")
    db.append_message("compressed", "user", "compressed summary")
    db.close()
    assert load_chat_preparation("cached").session_id == "compressed"
    assert warm("cached") is False
    assert web._web_agents["compressed"]._session_messages == [{"role": "user", "content": "compressed summary"}]


def test_same_session_id_in_another_profile_cannot_reuse_stamp(cache, monkeypatch, tmp_path):
    warm()
    old = web._web_agents["cached"]
    monkeypatch.setenv("SPARK_HOME", str(tmp_path / "other-profile"))
    db = SessionDB()
    db.create_session("cached", "web", model="fixture")
    db.append_message("cached", "user", "other profile")
    db.close()
    history, hit = web._web_agent_history_for_preparation(load_chat_preparation("cached"), old, "fixture")
    assert not hit and history == [{"role": "user", "content": "other profile"}]


def test_memory_pressure_protects_root_child_approval_and_warm_ownership(cache, monkeypatch):
    _, closed = cache
    monkeypatch.setattr(web, "_web_agent_cache_limit", lambda: 1)
    monkeypatch.setattr(web, "_web_agent_cache_policy", lambda: (1, 100))
    from tools import approval

    decision = approval._ApprovalEntry({"command": "fixture approval"})
    monkeypatch.setattr(approval, "_gateway_queues", {"approval": [decision]})
    web._mark_web_turn_active("root")
    for sid in ("root", "child", "approval", "warming", "idle"):
        agent = SimpleNamespace(
            _session_db=None, _session_messages=[{"content": "x" * 1000}],
            _active_children=[object()] if sid == "child" else [],
            close=lambda sid=sid: closed.append(sid),
        )
        if sid == "warming":
            web._web_warm_inflight.add(sid)
        web._store_web_agent(sid, agent, "fixture")
        web._web_agent_last_used[sid] = time.monotonic() - 10
    web._evict_web_agent_cache_if_needed()
    assert set(web._web_agents) == {"root", "child", "approval", "warming"}
    assert closed == ["idle"]
    assert not decision.event.is_set()
    web._clear_web_turn("root")
    web._web_agents["child"]._active_children.clear()
    approval._gateway_queues.clear()
    web._web_warm_inflight.clear()
    web._evict_web_agent_cache_if_needed()
    assert not web._web_agents
    assert set(closed) == {"root", "child", "approval", "warming", "idle"}


def test_durable_pending_decision_protects_agent(cache, monkeypatch):
    warm()
    db = SessionDB()
    db._conn.execute("""INSERT INTO web_pending_actions
        (action_id, session_id, turn_id, kind, created_at) VALUES ('decision', 'cached', 'root', 'clarification', 1)""")
    db._conn.commit()
    db.close()
    monkeypatch.setattr(web, "_web_agent_cache_policy", lambda: (1, 1))
    web._evict_web_agent_cache_if_needed()
    assert "cached" in web._web_agents
    db = SessionDB()
    db._conn.execute("UPDATE web_pending_actions SET status = 'resolved'")
    db._conn.commit()
    db.close()
    web._evict_web_agent_cache_if_needed()
    assert "cached" not in web._web_agents


def test_idle_expiry_closes_resources_and_eviction_reload_is_identical(cache, monkeypatch):
    warm()
    before = request_bytes(web._web_agents["cached"], None, "same prompt")
    monkeypatch.setattr(web, "_web_agent_cache_policy", lambda: (1, 64 * 1024 * 1024))
    web._web_agent_last_used["cached"] = time.monotonic() - 2
    assert web._get_web_cached_agent("cached") is None
    assert cache[1] == ["cached"]
    assert not web._web_agent_history_revisions
    warm()
    assert request_bytes(web._web_agents["cached"], None, "same prompt") == before


def test_hundred_large_sessions_bound_context_and_bookkeeping(cache, monkeypatch):
    monkeypatch.setattr(web, "_web_agent_cache_limit", lambda: 8)
    monkeypatch.setattr(web, "_web_agent_cache_policy", lambda: (1800, 6 * 1024 * 1024))
    for index in range(100):
        sid = f"pressure-{index}"
        # Independent large objects, not 100 aliases to one shared string.
        agent = SimpleNamespace(_session_db=None, _session_messages=[{"content": str(index) + "x" * 500_000}])
        web._store_web_agent(sid, agent, "fixture")
        assert len(web._web_agents) <= 8
        assert sum(retained_context_bytes(a) for a in web._web_agents.values()) <= 6 * 1024 * 1024
    assert len(web._web_agent_last_used) == len(web._web_agents)
    web._web_warm_recent.update({str(i): time.monotonic() for i in range(1000)})
    web._evict_web_agent_cache_if_needed()
    assert len(web._web_warm_recent) == 256


def test_warm_queue_uses_existing_admission_and_keeps_claim_until_worker_exit(cache, monkeypatch):
    started, finish = threading.Event(), threading.Event()
    original = web._warm_web_agent

    def blocked(*args):
        started.set()
        assert finish.wait(5)
        return original(*args)

    monkeypatch.setattr(web, "_warm_web_agent", blocked)

    async def exercise():
        await web.warm_session_agent("cached")
        try:
            for _ in range(1000):
                if started.is_set():
                    break
                await asyncio.sleep(0.001)
            assert started.is_set()
            assert web._chat_preparation.pending == 1
            assert len(web._chat_preparation.claims) == 1
            assert web._web_warm_inflight == {"cached"}
        finally:
            finish.set()
        for _ in range(1000):
            if web._chat_preparation.pending == 0 and not web._chat_preparation.claims:
                break
            await asyncio.sleep(0.001)
        assert not web._web_warm_inflight
        assert web._chat_preparation.pending == 0
        assert not web._chat_preparation.claims

    asyncio.run(exercise())


def test_backdated_external_insert_after_acceptance_invalidates_prefix(cache):
    warm()
    preparation = load_chat_preparation("cached")
    db = SessionDB()
    db.append_message("cached", "user", "accepted")
    db._conn.execute("INSERT INTO messages(session_id, role, content, timestamp) VALUES ('cached', 'assistant', 'backdated', 0)")
    db._conn.commit()
    db.close()
    history, hit = web._web_agent_history_for_preparation(preparation, web._web_agents["cached"], "fixture")
    assert not hit
    assert history[0] == {"role": "assistant", "content": "backdated"}


def test_pending_ancestor_decision_protects_compressed_leaf(cache, monkeypatch):
    db = SessionDB()
    db.end_session("cached", "compression")
    db.create_session("compressed", "web", model="fixture", parent_session_id="cached")
    db._conn.execute("""INSERT INTO web_pending_actions
        (action_id, session_id, turn_id, kind, created_at) VALUES ('ancestor', 'cached', 'root', 'clarification', 1)""")
    db._conn.commit()
    db.close()
    warm("cached")
    monkeypatch.setattr(web, "_web_agent_cache_policy", lambda: (1, 1))
    web._evict_web_agent_cache_if_needed()
    assert "compressed" in web._web_agents


def test_in_place_context_growth_without_warm_stamp_reestimates_bytes(cache, monkeypatch):
    monkeypatch.setattr(web, "_web_agent_cache_policy", lambda: (1800, 10000))
    agent = SimpleNamespace(_session_db=None, _session_messages=[{"content": "small"}])
    web._store_web_agent("growth", agent, "fixture")
    agent._session_messages[0]["content"] = "x" * 10000
    web._evict_web_agent_cache_if_needed()
    assert "growth" not in web._web_agents


def test_idle_maintenance_expires_without_another_cache_request(cache, monkeypatch):
    warm()
    monkeypatch.setattr(web, "_web_agent_cache_policy", lambda: (0.05, 64 * 1024 * 1024))

    async def exercise():
        maintenance = asyncio.create_task(web._maintain_web_agent_cache())
        try:
            for _ in range(1000):
                if cache[1] == ["cached"]:
                    break
                await asyncio.sleep(0.001)
            assert "cached" not in web._web_agents
            assert cache[1] == ["cached"]
        finally:
            maintenance.cancel()
            with pytest.raises(asyncio.CancelledError):
                await maintenance

    asyncio.run(exercise())


def test_external_delete_and_recreate_same_session_cannot_reuse_generation(cache):
    warm()
    old = web._web_agents["cached"]
    old_revision = web._web_agent_history_revisions["cached"][1]
    db = SessionDB()
    db.delete_session("cached")
    db.create_session("cached", "web", model="fixture")
    db.append_message("cached", "user", "new generation")
    db.append_message("cached", "assistant", "answer")
    db.close()
    preparation = load_chat_preparation("cached")
    assert preparation.revision.scope != old_revision.scope
    history, hit = web._web_agent_history_for_preparation(preparation, old, "fixture")
    assert not hit and history[0]["content"] == "new generation"
    assert "cached" not in web._web_agent_history_revisions


def test_cache_policy_config_and_environment_precedence(monkeypatch):
    monkeypatch.setattr(web, "load_config", lambda: {"dashboard": {
        "agent_cache_idle_seconds": 123, "agent_cache_context_bytes": 456,
    }})
    monkeypatch.delenv("SPARK_WEB_AGENT_CACHE_IDLE_SECONDS", raising=False)
    monkeypatch.delenv("SPARK_WEB_AGENT_CACHE_CONTEXT_BYTES", raising=False)
    assert web._web_agent_cache_policy() == (123.0, 456)
    monkeypatch.setenv("SPARK_WEB_AGENT_CACHE_IDLE_SECONDS", "0")
    monkeypatch.setenv("SPARK_WEB_AGENT_CACHE_CONTEXT_BYTES", "0")
    assert web._web_agent_cache_policy() == (0.0, 0)
    monkeypatch.setenv("SPARK_WEB_AGENT_CACHE_IDLE_SECONDS", "invalid")
    monkeypatch.setenv("SPARK_WEB_AGENT_CACHE_CONTEXT_BYTES", "-1")
    assert web._web_agent_cache_policy() == (1800.0, 0)


def test_warm_admission_rejects_overload_without_growing_queue(cache, monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(web._chat_preparation, "capacity", 2)
    finish = threading.Event()
    original = web._warm_web_agent

    def blocked(*args):
        assert finish.wait(5)
        return original(*args)

    monkeypatch.setattr(web, "_warm_web_agent", blocked)
    db = SessionDB()
    for sid in ("queued-b", "queued-c"):
        db.create_session(sid, "web", model="fixture")
    db.close()

    async def exercise():
        try:
            await web.warm_session_agent("cached")
            await web.warm_session_agent("queued-b")
            assert web._chat_preparation.pending == 2
            assert len(web._web_warm_inflight) == 2
            with pytest.raises(HTTPException) as busy:
                await web.warm_session_agent("queued-c")
            assert busy.value.status_code == 503
            assert busy.value.headers == {"Retry-After": "1"}
            assert "queued-c" not in web._web_warm_inflight
        finally:
            finish.set()
        for _ in range(1000):
            if web._chat_preparation.pending == 0 and not web._chat_preparation.claims:
                break
            await asyncio.sleep(0.001)
        assert web._chat_preparation.pending == 0
        assert not web._web_warm_inflight
        assert not web._chat_preparation.claims

    asyncio.run(exercise())


def test_warm_route_change_does_not_replace_child_owned_agent(cache):
    warm()
    agent = web._web_agents["cached"]
    agent._active_children.append(object())
    history = agent._session_messages
    assert warm(route={**ROUTE, "signature": "different"}) is False
    assert web._web_agents["cached"] is agent
    assert agent._session_messages is history
    assert len(cache[0]) == 1 and cache[1] == []
    agent._active_children.clear()
