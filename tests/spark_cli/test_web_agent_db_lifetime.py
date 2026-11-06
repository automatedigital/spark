"""Real connection lifetimes at cached-agent construction and execution boundaries."""

import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from core import run_agent
from core.spark_state import SessionDB
from spark_cli import web_server as web

pytestmark = pytest.mark.serial


@pytest.fixture
def owned_agent(monkeypatch):
    events = {}
    original_init = SessionDB.__init__
    original_close = SessionDB.close
    original_get = SessionDB.get_session

    def opened(db, *args, **kwargs):
        original_init(db, *args, **kwargs)
        events[db] = [("open", threading.get_ident())]

    def read(db, *args, **kwargs):
        events[db].append(("read", threading.get_ident()))
        return original_get(db, *args, **kwargs)

    def closed(db):
        events[db].append(("close", threading.get_ident()))
        original_close(db)

    class Agent:
        def __init__(self, **kwargs):
            self.session_id = kwargs["session_id"]
            self._session_db = kwargs["session_db"]
            assert isinstance(self._session_db, SessionDB)
            self._session_db.create_session(self.session_id, "web")
            assert self._session_db.get_session(self.session_id)
            self._cached_system_prompt = "immutable prefix"
            self._active_children = [object()]
            self.clarify_callback = kwargs["clarify_callback"]

    monkeypatch.setattr(SessionDB, "__init__", opened)
    monkeypatch.setattr(SessionDB, "get_session", read)
    monkeypatch.setattr(SessionDB, "close", closed)
    monkeypatch.setattr(run_agent, "AIAgent", Agent)
    monkeypatch.setattr(web, "_web_max_iterations", lambda: 2)
    monkeypatch.setattr(web, "_web_agents", OrderedDict())
    monkeypatch.setattr(web, "_web_agent_signatures", {})
    monkeypatch.setattr(web, "_web_agent_last_used", {})

    def create():
        return web._new_web_agent(
            session_id="owned", model="fixture", token_callback=None,
            tool_start_callback=None, tool_complete_callback=None,
            reasoning_callback=None, status_callback=None,
        )

    yield create, events
    for db, trace in events.items():
        assert trace[0][0] == "open" and trace[-1][0] == "close"
        assert sum(stage == "close" for stage, _ in trace) == 1
        assert len({owner for _, owner in trace}) == 1, trace
        assert db._conn is None


@pytest.mark.parametrize("failure", [False, True])
def test_cold_cached_and_warm_agent_lease_on_executing_worker(owned_agent, monkeypatch, failure):
    create, events = owned_agent
    with ThreadPoolExecutor(1) as preparation, ThreadPoolExecutor(1) as execution:
        agent = preparation.submit(create).result()
        assert agent._session_db is None
        prefix, children, approval = agent._cached_system_prompt, agent._active_children, agent.clarify_callback
        leases = []

        def provider(current, *args):
            assert current is agent
            db = current._session_db
            assert isinstance(db, SessionDB)
            assert db.get_session("owned")
            # This is the real SessionDB that synchronous delegation inherits,
            # not a facade, and child/approval registrations stay on the agent.
            assert current._active_children is children
            assert current.clarify_callback is approval
            leases.append(db)
            if failure:
                raise RuntimeError("provider failed")
            return {"final_response": "answer"}

        monkeypatch.setattr(web, "_run_web_agent_turn", provider)
        for _ in range(2):
            future = execution.submit(web._run_web_agent_turn_with_db, agent, "next")
            if failure:
                with pytest.raises(RuntimeError, match="provider failed"):
                    future.result()
            else:
                assert future.result()["final_response"] == "answer"
            assert agent._session_db is None
            assert agent._cached_system_prompt == prefix
            assert web._get_web_cached_agent("owned") is agent
        assert leases[0] is not leases[1]
        assert len(events) == 3
        web._close_web_agent("owned")


def test_cache_retirement_does_not_close_running_workers_connection(owned_agent, monkeypatch):
    create, _ = owned_agent
    agent = create()
    entered, release = threading.Event(), threading.Event()

    def provider(current, *args):
        db = current._session_db
        entered.set()
        assert release.wait(5)
        assert current._session_db is db
        assert db.get_session("owned")

    monkeypatch.setattr(web, "_run_web_agent_turn", provider)
    with ThreadPoolExecutor(1) as executor:
        future = executor.submit(web._run_web_agent_turn_with_db, agent, "run")
        assert entered.wait(5)
        try:
            web._close_web_agent("owned")
            assert "owned" not in web._web_agents
        finally:
            release.set()
        future.result()
    assert agent._session_db is None


def test_constructor_failure_closes_owned_connection(owned_agent, monkeypatch):
    create, _ = owned_agent

    def failed(**kwargs):
        assert kwargs["session_db"].get_session("missing") is None
        raise RuntimeError("construction failed")

    monkeypatch.setattr(run_agent, "AIAgent", failed)
    with pytest.raises(RuntimeError, match="construction failed"):
        create()


def test_title_worker_owns_connection_after_cached_agent_detaches(owned_agent, monkeypatch):
    create, _ = owned_agent
    agent = create()
    done = threading.Event()
    from agent import title_generator

    monkeypatch.setattr(title_generator, "generate_title", lambda *args: "Owned title")
    monkeypatch.setattr(web, "_emit_web_session_updated", lambda sid: done.set())
    with ThreadPoolExecutor(1) as executor:
        futures = []

        def submit(fn):
            future = executor.submit(fn)
            futures.append(future)
            return future

        monkeypatch.setattr(web, "get_async_runtime", lambda: SimpleNamespace(submit_blocking=submit))
        web._maybe_auto_title_web(agent, "owned", "prompt", {"final_response": "answer"})
        assert done.wait(5)
        futures[0].result(timeout=5)
    assert agent._session_db is None


def test_stopped_dispatch_does_not_open_runtime_connection(owned_agent):
    create, events = owned_agent
    agent = create()
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(InterruptedError):
        web._dispatch_prepared_turn(SimpleNamespace(interrupt_requested=False), cancelled, agent, "stop", None, [])
    assert len(events) == 1


def test_warm_route_caches_agent_without_open_connection(owned_agent, monkeypatch):
    import asyncio

    create, _ = owned_agent
    seed = create()
    web._close_web_agent("owned")
    monkeypatch.setattr(web, "_web_warm_inflight", set())
    monkeypatch.setattr(web, "_web_warm_recent", {})
    monkeypatch.setattr(web, "_resolve_web_turn_route", lambda *a, **kw: {"model": "fixture", "runtime": {}, "signature": "fixture"})
    original_start = web._chat_preparation.start
    futures = []

    def start(fn, *args, **kwargs):
        future = original_start(fn, *args, **kwargs)
        futures.append(future)
        return future

    monkeypatch.setattr(web._chat_preparation, "start", start)

    async def warm():
        result = await web.warm_session_agent("owned")
        assert result == {"ok": True, "warm": False}
        await asyncio.wrap_future(futures[-1])
        assert web._get_web_cached_agent("owned") is not seed
        assert web._get_web_cached_agent("owned")._session_db is None
        # The general ownership fixture carries a fake live child; this warm
        # reuse case represents an idle agent, which has no active children.
        web._get_web_cached_agent("owned")._active_children = []
        assert await web.warm_session_agent("owned") == {"ok": True, "warm": True}

    asyncio.run(warm())


def test_stop_during_connection_open_fences_provider(owned_agent, monkeypatch):
    create, _ = owned_agent
    agent = create()
    cancelled = threading.Event()
    original_init = SessionDB.__init__

    def opened(db, *args, **kwargs):
        original_init(db, *args, **kwargs)
        cancelled.set()

    def forbidden(*args):
        pytest.fail("provider dispatched after Stop during DB open")

    monkeypatch.setattr(SessionDB, "__init__", opened)
    monkeypatch.setattr(web, "_run_web_agent_turn", forbidden)
    with pytest.raises(InterruptedError):
        web._dispatch_prepared_turn(SimpleNamespace(interrupt_requested=False), cancelled, agent, "stop", None, [])
    assert agent._session_db is None
