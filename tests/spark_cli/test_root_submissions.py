"""Root receipt replay uses real SQLite and a deterministic provider boundary."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from core.spark_state import SessionDB
from spark_cli import web_server as web

pytestmark = pytest.mark.serial


def accept(db, session="thread", request="draft", message="hello"):
    return db.accept_runtime_command(
        session, "root.message", request, {"message": message},
        {"session_id": session, "turn_id": "turn-" + session, "ok": True},
        {"dispatch": "root"}, compression_family=True, root_message=message,
    )


def test_atomic_acceptance_concurrent_connections_and_restart():
    db = SessionDB()
    db.create_session("thread", "web")
    db.close()

    def submit(_):
        connection = SessionDB()
        try:
            return accept(connection)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(submit, range(16)))
    assert sum(row["created"] for row in results) == 1
    assert all(row["acceptance"] == results[0]["acceptance"] for row in results)
    db = SessionDB()
    assert len(db.get_messages("thread")) == 1
    assert len(db.list_web_turn_projections("thread")) == 1
    assert db.get_latest_web_turn_projection("thread")["projection"]["status"] == "uncertain"
    assert not accept(db)["created"]
    with pytest.raises(ValueError, match="different payload"):
        accept(db, message="changed")
    db.close()


def test_acceptance_rolls_back_prompt_if_turn_insert_fails():
    db = SessionDB()
    db.create_session("thread", "web")
    db._conn.execute("CREATE TRIGGER reject_root BEFORE INSERT ON web_turn_projections BEGIN SELECT RAISE(ABORT, 'fault'); END")
    db._conn.commit()
    with pytest.raises(Exception, match="fault"):
        accept(db)
    assert db.get_messages("thread") == []
    assert db.get_runtime_command("thread", "root.message", "draft", {"message": "hello"}) is None
    db.close()


def test_profiles_and_compression_aliases(monkeypatch, tmp_path):
    db = SessionDB()
    db.create_session("thread", "web")
    first = accept(db)
    db._conn.execute("UPDATE sessions SET end_reason='compression' WHERE id='thread'")
    db._conn.commit()
    db.create_session("compressed", "web", parent_session_id="thread")
    again = accept(db, session="compressed")
    assert not again["created"]
    assert again["acceptance"] == first["acceptance"]
    db.close()
    monkeypatch.setenv("SPARK_HOME", str(tmp_path / "profile-two"))
    db = SessionDB()
    db.create_session("thread", "web")
    assert accept(db)["created"]
    db.close()


@pytest.mark.parametrize("followup", [False, True])
def test_lost_response_replay_one_prompt_one_run_one_dispatch(monkeypatch, followup):
    web._web_active_turns.clear()
    web._web_turn_aliases.clear()
    web._web_agents.clear()
    dispatches = []
    monkeypatch.setattr(web, "_resolve_web_turn_route", lambda *a, **k: {
        "model": "replay", "runtime": {}, "signature": "replay",
    })
    monkeypatch.setattr(web, "_new_web_agent", lambda **kw: SimpleNamespace(session_id=kw["session_id"]))
    monkeypatch.setattr(web, "_maybe_auto_title_web", lambda *a, **k: None)
    monkeypatch.setattr(web, "_get_web_cached_agent", lambda *a: None)

    async def blocking(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    async def provider(loop, fn):
        return fn()

    def replay(agent, message, history, items):
        dispatches.append(message)
        return {"final_response": "replayed answer"}

    monkeypatch.setattr(web, "_run_blocking", blocking)
    monkeypatch.setattr(web, "_run_web_turn_in_executor", provider)
    monkeypatch.setattr(web, "_run_web_agent_turn", replay)
    if followup:
        db = SessionDB()
        db.create_session("existing", "web")
        db.close()

    async def exercise():
        body = (web.ConversationMessage if followup else web.ConversationCreate)(
            message="hello", submission_id="same-draft",
        )
        async def send():
            if followup:
                return await web.send_conversation_message("existing", body)
            return await web.create_conversation(body)
        # Treat the first returned body as dropped by the transport.
        first, second = await asyncio.gather(send(), send())
        assert first["session_id"] == second["session_id"]
        assert first["turn_id"] == second["turn_id"]
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and "run_agent_task" in t.get_coro().__qualname__]
        await asyncio.gather(*tasks)
        third = await send()
        assert third["turn_id"] == first["turn_id"]
        monkeypatch.setattr(web, "_root_submission_epoch", "restarted-process")
        fourth = await send()
        assert fourth["turn_id"] == first["turn_id"]
        db = SessionDB()
        messages = db.get_messages(first["session_id"])
        assert [m["content"] for m in messages if m["role"] == "user"] == ["hello"]
        assert len(db.list_web_turn_projections(first["session_id"])) == 1
        db.close()
    asyncio.run(exercise())
    assert dispatches == ["hello"]


def test_process_loss_before_dispatch_never_replays(monkeypatch):
    db = SessionDB()
    db.create_session("thread", "web")
    db.close()
    body = web.ConversationMessage(message="hello", submission_id="lost-before-dispatch")
    first = web._root_submission("thread", body, "root.message", accept=True)
    monkeypatch.setattr(web, "_root_submission_epoch", "another-process")
    retry = web._root_submission("thread", body, "root.message")
    assert retry["acceptance"]["turn_id"] == first["acceptance"]["turn_id"]
    assert retry["acceptance"]["execution_state"] == "uncertain"
    assert not retry["created"]


def test_running_submission_projection_becomes_uncertain_after_restart(monkeypatch):
    db = SessionDB()
    db.create_session("lost-running", "web")
    db.close()
    body = web.ConversationMessage(message="started", submission_id="running")
    receipt = web._root_submission("lost-running", body, "root.message", accept=True)
    web._mark_web_turn_active("lost-running", accepted_submission=receipt["acceptance"])
    monkeypatch.setattr(web, "_root_submission_epoch", "restarted")
    web._web_active_turns.clear()
    web._web_turn_aliases.clear()
    assert web._latest_web_turn_projection("lost-running")["status"] == "uncertain"
    assert web._root_submission("lost-running", body, "root.message")["acceptance"]["execution_state"] == "uncertain"


@pytest.mark.parametrize("after_dispatch", [False, True])
def test_real_process_loss_keeps_acceptance_without_redispatch(tmp_path, after_dispatch):
    import os
    import subprocess
    import sys
    marker = tmp_path / "provider-dispatches"
    script = '''
import asyncio, os
from pathlib import Path
from types import SimpleNamespace
from spark_cli import web_server as w
w._resolve_web_turn_route = lambda *a, **k: {"model": "replay", "runtime": {}, "signature": "replay"}
w._new_web_agent = lambda **kw: SimpleNamespace(session_id=kw["session_id"])
def provider(*args):
    Path(os.environ["SP01_DISPATCH_MARKER"]).write_text("one dispatch")
    os._exit(0)
w._run_web_agent_turn = provider
async def run():
    result = await w.create_conversation(w.ConversationCreate(message="process loss", submission_id="process-draft"))
    if os.environ["SP01_AFTER_DISPATCH"] == "0":
        os._exit(0)
    # Run the accepted task until the replay provider terminates this process.
    await asyncio.gather(*[t for t in asyncio.all_tasks() if t is not asyncio.current_task()])
asyncio.run(run())
'''
    result = subprocess.run([sys.executable, "-c", script], env={
        **os.environ, "SP01_DISPATCH_MARKER": str(marker),
        "SP01_AFTER_DISPATCH": str(int(after_dispatch)),
    }, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    sid = web._root_submission_session("process-draft", "unused")
    body = web.ConversationCreate(message="process loss", submission_id="process-draft")
    retry = web._root_submission(sid, body, "root.create", route="/api/conversations")
    assert retry["acceptance"]["execution_state"] == "uncertain"
    assert not retry["created"]
    assert marker.exists() == after_dispatch
    db = SessionDB()
    assert len(db.get_messages(sid)) == 1
    assert len(db.list_web_turn_projections(sid)) == 1
    db.close()
