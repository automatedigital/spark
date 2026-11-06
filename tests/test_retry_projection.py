"""Retry evidence commits before status replay; restart never invents a wait."""

import asyncio
import json
import time

import pytest

from core.run_agent.retry_policy import RetryStatus
from core.spark_state import SessionDB
from spark_cli import web_server as web
from spark_cli.retry_projection import RETRY_STATUS_PREFIX


def retry_status():
    now = time.time()
    return RetryStatus({
        "version": 1, "reason_class": "rate_limit", "attempt": 2, "max_attempts": 3,
        "next_delay_seconds": 10, "next_attempt_at": now + 10, "observed_at": now,
        "elapsed_seconds": 0, "budget_seconds": 240, "budget_deadline_at": now + 240,
    })


@pytest.fixture
def turn(monkeypatch):
    sid = "retry-projection"
    db = SessionDB()
    db.ensure_session(sid, source="web", model="replay")
    db.close()
    active = web.WebActiveTurn(
        started_at=time.time(), last_event_at=time.time(), status="Calling model…",
        interrupt_requested=False, active_agent_session_id=sid, phase="api",
    )
    monkeypatch.setattr(web, "_web_active_turns", {sid: active})
    loop = asyncio.new_event_loop()
    callback = web._make_web_chat_callbacks(sid, asyncio.Queue(), loop)[4]
    yield sid, active, callback
    loop.close()


def test_retry_commits_before_publish_and_reconciles_snapshot(turn, monkeypatch):
    sid, active, callback = turn
    published = []

    def publish(topic, data, session_id):
        db = SessionDB()
        try:
            events = db.get_session_events(sid)
            assert events[-1]["event_type"] == "retry.status"
            assert events[-1]["payload"]["turn_id"] == active.turn_id
        finally:
            db.close()
        published.append((topic, data))

    monkeypatch.setattr(web, "_publish_event", publish)
    retry_status_message = retry_status()
    retry_status_message.data["run_id"] = active.turn_id
    callback("lifecycle", retry_status_message)
    callback("lifecycle", retry_status_message)
    assert active.phase == "retry"
    snapshot = web._conversation_turn_status_payload(sid)
    assert snapshot["status"] == published[-1][1]["message"]
    data = json.loads(snapshot["status"].removeprefix(RETRY_STATUS_PREFIX))
    assert data["reason_class"] == "rate_limit"
    assert data["turn_id"] == active.turn_id
    assert data["attempt"] == 2
    web._web_active_turns.clear()
    restarted = web._conversation_turn_status_payload(sid)
    assert restarted["status"] is None
    assert not restarted["turn_active"]
    db = SessionDB()
    try:
        assert db.get_session_events(sid)[-1]["event_type"] == "retry.status"
        assert len(db.get_session_events(sid)) == 1
    finally:
        db.close()


def test_retry_commit_failure_never_publishes_confirmed_wait(turn, monkeypatch):
    sid, active, callback = turn
    monkeypatch.setattr(SessionDB, "append_session_event", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("write failed")))
    monkeypatch.setattr(web, "_publish_event", lambda *a, **kw: pytest.fail("Uncommitted retry published"))
    with pytest.raises(RuntimeError, match="write failed"):
        callback("lifecycle", retry_status())
    assert active.phase == "api"
    assert not active.status.startswith(RETRY_STATUS_PREFIX)


def test_retired_retry_callback_cannot_update_replacement(turn, monkeypatch):
    sid, active, callback = turn
    monkeypatch.setattr(web, "_publish_event", lambda *a, **kw: None)
    callback("lifecycle", "Calling model…")
    replacement = web.WebActiveTurn(
        started_at=time.time(), last_event_at=time.time(), status="Replacement",
        interrupt_requested=False, active_agent_session_id=sid, phase="api",
    )
    web._web_active_turns[sid] = replacement
    callback("lifecycle", retry_status())
    assert replacement.status == "Replacement"
    db = SessionDB()
    try:
        assert not db.get_session_events(sid)
    finally:
        db.close()


def test_first_late_retry_is_fenced_by_root_run_identity(turn, monkeypatch):
    sid, active, callback = turn
    monkeypatch.setattr(web, "_publish_event", lambda *a, **kw: pytest.fail("Retired run published a retry"))
    late = retry_status()
    late.data["run_id"] = "retired-root-run"
    callback("lifecycle", late)
    assert active.phase == "api"
    db = SessionDB()
    try:
        assert not db.get_session_events(sid)
    finally:
        db.close()
