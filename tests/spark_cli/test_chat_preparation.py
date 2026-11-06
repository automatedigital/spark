"""Real SQLite preparation, admission and deterministic dispatch boundaries."""

import asyncio
import threading
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from core.spark_state import SessionDB
from spark_cli import web_server as web
from spark_cli.chat_preparation import ChatPreparationPool, load_chat_preparation

pytestmark = pytest.mark.serial


@pytest.fixture
def replay(monkeypatch):
    web._web_active_turns.clear()
    web._web_turn_aliases.clear()
    web._web_agents.clear()
    pool = ChatPreparationPool(capacity=4)
    # Decorated handlers use the original admission pool; preserve that identity.
    assert web._chat_preparation.pending == 0
    web._chat_preparation.samples.clear()
    dispatches = []
    monkeypatch.setattr(
        web,
        "_resolve_web_turn_route",
        lambda *a, **k: {
            "model": "custom-model",
            "runtime": {"provider": "custom"},
            "signature": "custom",
        },
    )
    monkeypatch.setattr(
        web, "_new_web_agent", lambda **kw: SimpleNamespace(session_id=kw["session_id"])
    )
    monkeypatch.setattr(web, "_maybe_auto_title_web", lambda *a, **k: None)
    monkeypatch.setattr(
        web,
        "_run_web_agent_turn",
        lambda agent, message, history, items: (
            dispatches.append((message, history)) or {"final_response": "answer"}
        ),
    )
    db = SessionDB()
    db.create_session("history", "web", model="custom-model")
    db.append_message("history", "user", "old prompt")
    db.append_message("history", "assistant", "old answer")
    db.close()
    yield dispatches, pool
    web._web_active_turns.clear()
    web._web_turn_aliases.clear()
    web._web_agents.clear()


async def settle():
    tasks = [
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task() and "run_agent_task" in task.get_coro().__qualname__
    ]
    await asyncio.gather(*tasks)


def test_history_boundary_excludes_accepted_prompt_and_closes_connection():
    db = SessionDB()
    db.create_session("boundary", "web")
    db.append_message("boundary", "user", "before")
    db.close()
    preparation = load_chat_preparation("boundary")
    db = SessionDB()
    db.append_message("boundary", "user", "new accepted prompt")
    db.close()
    assert preparation.history() == [{"role": "user", "content": "before"}]


def test_cancelled_waiter_retains_bounded_admission_until_worker_exits():
    async def exercise():
        pool = ChatPreparationPool(capacity=1)
        started, finish = threading.Event(), threading.Event()

        def blocked():
            started.set()
            finish.wait(5)

        @pool.admitted
        async def prepare():
            await pool.run(blocked)

        task = asyncio.create_task(prepare())
        try:
            while not started.is_set():
                await asyncio.sleep(0.001)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert pool.pending == 1
            with pytest.raises(HTTPException) as busy:
                await prepare()
            assert busy.value.status_code == 503
            assert busy.value.headers == {"Retry-After": "1"}
        finally:
            finish.set()
        for _ in range(1000):
            if pool.pending == 0:
                break
            await asyncio.sleep(0.001)
        assert pool.pending == 0

    asyncio.run(exercise())


def test_followup_history_and_receipt_replay(replay):
    dispatches, _ = replay

    async def exercise():
        body = web.ConversationMessage(message="new prompt", submission_id="new-draft")
        first, retry = await asyncio.gather(
            web.send_conversation_message("history", body),
            web.send_conversation_message("history", body),
        )
        assert first["turn_id"] == retry["turn_id"]
        await settle()
        assert dispatches == [
            (
                "new prompt",
                [
                    {"role": "user", "content": "old prompt"},
                    {"role": "assistant", "content": "old answer"},
                ],
            )
        ]
        assert (await web.send_conversation_message("history", body))["turn_id"] == first["turn_id"]

    asyncio.run(exercise())


@pytest.mark.parametrize("cached", [False, True])
def test_stop_during_history_preparation_fences_provider_dispatch(replay, monkeypatch, cached):
    dispatches, _ = replay
    started, finish = threading.Event(), threading.Event()
    original = SessionDB.get_messages_as_conversation

    def delayed(db, sid):
        started.set()
        assert finish.wait(5)
        return original(db, sid)

    monkeypatch.setattr(SessionDB, "get_messages_as_conversation", delayed)
    if cached:
        web._web_agents["history"] = SimpleNamespace(
            session_id="history", interrupt=lambda *_: None
        )

    async def exercise():
        await web.send_conversation_message(
            "history",
            web.ConversationMessage(
                message="must not dispatch",
                submission_id="stop-draft",
            ),
        )
        try:
            while not started.is_set():
                await asyncio.sleep(0.001)
            result = await web.interrupt_conversation("history", web.ConversationInterrupt())
            assert result["ok"]
        finally:
            finish.set()
        await settle()
        assert dispatches == []
        db = SessionDB()
        try:
            projection = db.get_latest_web_turn_projection("history")["projection"]
            assert projection["status"] in {"interrupted", "cancelled"}
        finally:
            db.close()

    asyncio.run(exercise())


def test_stop_after_preparation_while_execution_is_queued(replay, monkeypatch):
    dispatches, _ = replay

    async def queued(loop, fn):
        await web.interrupt_conversation("history", web.ConversationInterrupt())
        return fn()

    monkeypatch.setattr(web, "_run_web_turn_in_executor", queued)

    async def exercise():
        await web.send_conversation_message("history", web.ConversationMessage(message="queued"))
        await settle()
        assert dispatches == []

    asyncio.run(exercise())


def test_worker_database_is_opened_read_and_closed_on_same_thread(monkeypatch):
    db = SessionDB()
    db.create_session("worker-owned", "web")
    db.close()
    events = []
    original_init, original_close = SessionDB.__init__, SessionDB.close
    original_history = SessionDB.get_messages_as_conversation

    def opened(db, *args, **kwargs):
        original_init(db, *args, **kwargs)
        events.append((db, "open", threading.get_ident()))

    def closed(db):
        events.append((db, "close", threading.get_ident()))
        original_close(db)

    def history(db, sid):
        events.append((db, "read", threading.get_ident()))
        return original_history(db, sid)

    monkeypatch.setattr(SessionDB, "__init__", opened)
    monkeypatch.setattr(SessionDB, "close", closed)
    monkeypatch.setattr(SessionDB, "get_messages_as_conversation", history)
    pool = ChatPreparationPool()

    @pool.admitted
    async def exercise():
        preparation = await pool.run(load_chat_preparation, "worker-owned")
        assert await pool.run(preparation.history) == []

    asyncio.run(exercise())
    assert len([event for event in events if event[1] == "open"]) == 2
    for identity in {event[0] for event in events}:
        owned = [event for event in events if event[0] == identity]
        assert len({event[2] for event in owned}) == 1
        assert owned[0][2] != threading.get_ident()
        assert owned[-1][1] == "close"


def test_cancelled_background_keeps_owner_until_preparation_worker_exits(replay, monkeypatch):
    dispatches, _ = replay
    started, finish = threading.Event(), threading.Event()
    original = SessionDB.get_messages_as_conversation

    def delayed(db, sid):
        started.set()
        assert finish.wait(5)
        return original(db, sid)

    monkeypatch.setattr(SessionDB, "get_messages_as_conversation", delayed)

    async def exercise():
        await web.send_conversation_message("history", web.ConversationMessage(message="cancelled"))
        while not started.is_set():
            await asyncio.sleep(0.001)
        task = next(t for t in asyncio.all_tasks() if "run_agent_task" in t.get_coro().__qualname__)
        task.cancel()
        await asyncio.sleep(0.01)
        assert web._is_web_turn_active("history")
        with pytest.raises(HTTPException) as conflict:
            await web.send_conversation_message(
                "history", web.ConversationMessage(message="replacement")
            )
        assert conflict.value.status_code == 409
        finish.set()
        await task
        assert dispatches == []
        assert not web._is_web_turn_active("history")

    try:
        asyncio.run(exercise())
    finally:
        finish.set()


def test_saturation_rejects_before_durable_acceptance(replay, monkeypatch):
    dispatches, _ = replay
    started, finish = threading.Event(), threading.Event()
    original = web._resolve_web_turn_route
    monkeypatch.setattr(web._chat_preparation, "capacity", 1)

    def delayed(*args, **kwargs):
        started.set()
        assert finish.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(web, "_resolve_web_turn_route", delayed)

    async def exercise():
        first = asyncio.create_task(
            web.create_conversation(
                web.ConversationCreate(
                    message="admitted",
                    submission_id="admitted-draft",
                )
            )
        )
        try:
            while not started.is_set():
                await asyncio.sleep(0.001)
            with pytest.raises(HTTPException) as busy:
                await web.create_conversation(
                    web.ConversationCreate(
                        message="busy",
                        submission_id="busy-draft",
                    )
                )
            assert busy.value.status_code == 503
            sid = web._root_submission_session("busy-draft", "unused")
            assert (
                web._root_submission(
                    sid,
                    web.ConversationCreate(
                        message="busy",
                        submission_id="busy-draft",
                    ),
                    "root.create",
                    route="/api/conversations",
                )
                is None
            )
        finally:
            finish.set()
        await first
        await settle()
        assert [item[0] for item in dispatches] == ["admitted"]

    asyncio.run(exercise())


def test_compression_between_lookup_and_claim_rebinds_canonical_owner(monkeypatch):
    from spark_cli import chat_preparation as preparation_module

    db = SessionDB()
    db.create_session("moving-parent", "web")
    db.close()
    original = preparation_module.load_chat_preparation
    moved = False

    def migrate_after_lookup(sid):
        nonlocal moved
        preparation = original(sid)
        if not moved:
            moved = True
            db = SessionDB()
            try:
                db.end_session("moving-parent", "compression")
                db.create_session("moving-leaf", "web", parent_session_id="moving-parent")
            finally:
                db.close()
        return preparation

    monkeypatch.setattr(preparation_module, "load_chat_preparation", migrate_after_lookup)
    pool = ChatPreparationPool()

    @pool.admitted
    async def exercise():
        preparation = await pool.load_session("moving-parent")
        assert preparation.session_id == "moving-leaf"
        assert pool.current.get().claimed[1] == "moving-leaf"
        assert len(pool.claims) == 1

    asyncio.run(exercise())
    assert pool.claims == {}
    assert pool.pending == 0
