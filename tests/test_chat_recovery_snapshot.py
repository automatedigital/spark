"""SP02 read recovery at real SQLite / process-delivery boundaries."""
import pytest

from core.spark_state import SessionDB
from spark_cli import web_server as web
from spark_cli.web_state import web_state_journal

pytestmark = pytest.mark.serial


@pytest.fixture
def database():
    db = SessionDB()
    db.ensure_session("recovery", source="web", model="replay")
    db.append_message("recovery", "user", "one prompt")
    yield db
    web._clear_web_turn("recovery")
    db.close()


def test_snapshot_is_transactional_across_connections(database, monkeypatch):
    other = SessionDB()
    original = database.list_web_turn_projections
    def concurrent_write(sid):
        other.create_web_pending_action(action_id="late", session_id=sid, turn_id="t", kind="approval", payload={})
        return original(sid)
    monkeypatch.setattr(database, "list_web_turn_projections", concurrent_write)
    try:
        snapshot = database.get_web_recovery_snapshot("recovery")
        assert snapshot["pending_actions"] == []
        assert other.get_web_pending_action("late") is not None
    finally:
        other.close()


def test_restart_preserves_uncertainty_and_pending_decisions(database):
    database.upsert_web_turn_projection("t", "recovery", {"turn_id": "t", "status": "running", "submission_epoch": "dead-process"})
    database.create_web_pending_action(action_id="approval", session_id="recovery", turn_id="t", kind="approval", payload={"command": "replay"})
    before = database.get_messages("recovery")
    result = web._conversation_recovery_payload("recovery")
    assert result["schema_version"] == 1
    assert result["turn_outcome"]["status"] == "uncertain"
    assert result["stream_text_mode"] == "unknown"
    assert result["pending_actions"][0]["action_id"] == "approval"
    assert result["durable_cursor"]["session_sequences"]["recovery"] > 0
    assert result["stream_watermark"]["server_epoch"] == web_state_journal.server_epoch
    assert database.get_messages("recovery") == before


def test_bounded_stream_tail_and_legacy_routes_remain(database):
    turn = web._mark_web_turn_active("recovery", active_agent_session_id="recovery")
    with turn.lock:
        turn.stream_text = "x" * 100_000
        turn.stream_revision = 7
    result = web._conversation_recovery_payload("recovery")
    assert len(result["stream_text"]) == 64_000
    assert result["stream_text_start"] == 36_000
    assert result["stream_revision"] == 7
    delta = web._conversation_recovery_payload("recovery", after_chars=1)
    assert len(delta["stream_text"]) == 64_000
    assert delta["stream_text_mode"] == "tail"
    routes = set(web.app.openapi()["paths"])
    assert {f"/api/conversations/{{session_id}}/{name}" for name in ["recovery", "turn-status", "stream-snapshot", "pending-actions", "plan", "turn-outcome"]} <= routes


def test_retry_compression_commit_before_publication(database, monkeypatch):
    original = SessionDB.get_web_recovery_snapshot
    calls = 0
    def compress(db, sid, **kwargs):
        nonlocal calls
        snapshot = original(db, sid, **kwargs)
        calls += 1
        if calls == 1:
            database.create_session("compressed", source="web", model="replay", parent_session_id="recovery")
            database.end_session("recovery", end_reason="compression")
            database.append_message("compressed", "assistant", "saved after compression")
        return snapshot
    monkeypatch.setattr(SessionDB, "get_web_recovery_snapshot", compress)
    result = web._conversation_recovery_payload("recovery")
    assert result["latest_session_id"] == "compressed"
    assert result["history"]["messages"][-1]["content"] == "saved after compression"
    assert calls == 4


def test_bounded_reconciliation_on_changing_journal(database, monkeypatch):
    original = SessionDB.get_web_recovery_snapshot
    def moving(db, sid, **kwargs):
        snapshot = original(db, sid, **kwargs)
        web_state_journal.append(topic="chat.status", entity_id=sid, payload={})
        return snapshot
    monkeypatch.setattr(SessionDB, "get_web_recovery_snapshot", moving)
    with pytest.raises(web.HTTPException) as error:
        web._conversation_recovery_payload("recovery")
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "reconcile_again"


def test_expired_journal_recovers_without_replaying(database, monkeypatch):
    from spark_cli.web_state import WEB_STATE_PROJECTION_VERSION, WebStateJournal

    journal = WebStateJournal(max_events=1, server_epoch="expired-fixture")
    for _ in range(3):
        journal.append("chat.status", {}, "recovery")
    resume = journal.resume(0, projection_version=WEB_STATE_PROJECTION_VERSION,
                            server_epoch=journal.server_epoch)
    assert resume.requires_snapshot
    assert resume.reason == "retention_expired"
    monkeypatch.setattr("spark_cli.web_state.web_state_journal", journal)
    before = database.get_messages("recovery")
    snapshot = web._conversation_recovery_payload("recovery")
    assert snapshot["history"]["messages"][0]["content"] == "one prompt"
    assert snapshot["stream_watermark"] == {"server_epoch": "expired-fixture", "sequence": 3}
    assert database.get_messages("recovery") == before


def test_read_accessor_bounds_history_and_does_not_write(database):
    for i in range(85):
        database.append_message("recovery", "assistant", f"saved {i}")
    before = database._conn.total_changes
    snapshot = database.get_web_recovery_snapshot("recovery", limit=5)
    assert len(snapshot["history"]["messages"]) == 5
    assert snapshot["history"]["has_earlier"]
    assert snapshot["history"]["messages"][-1]["content"] == "saved 84"
    assert database._conn.total_changes == before
    assert not database._conn.in_transaction


def test_two_generating_chats_recover_independently(database):
    database.ensure_session("second", source="web", model="replay")
    try:
        for sid, text in [("recovery", "alpha"), ("second", "bravo")]:
            turn = web._mark_web_turn_active(sid, active_agent_session_id=sid)
            with turn.lock:
                turn.stream_text = text
                turn.stream_revision = 1
        for sid, text in [("recovery", "alpha"), ("second", "bravo")]:
            result = web._conversation_recovery_payload(sid)
            assert result["turn_active"]
            assert result["active_turn_session_id"] == sid
            assert result["stream_text"] == text
    finally:
        web._clear_web_turn("second")
