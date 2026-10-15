"""Receipt acceptance is durable, scoped and atomic across real SQLite clients."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from core.spark_state import SessionDB


def test_concurrent_acceptance_lost_response_restart_and_conflict(tmp_path):
    path = tmp_path / "state.db"
    db = SessionDB(path)
    db.create_session("owner", "web")
    clients = [SessionDB(path) for _ in range(8)]
    try:
        def accept(client):
            return client.accept_runtime_command(
                "owner", "subagent.dispatch", "request-1", {"goal": "fixture", "model": "custom"},
                {"handle": "attempt-1"}, {"dispatch": "attempt-1"},
            )
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(accept, clients))
        assert sum(r["created"] for r in results) == 1
        assert all(r["acceptance"] == results[0]["acceptance"] for r in results)
        assert results[0]["acceptance"]["committed_sequence"] > 0
        assert len([e for e in db.get_session_events("owner") if e["event_type"] == "runtime.command.accepted"]) == 1
    finally:
        for client in clients:
            client.close()
        db.close()
    db = SessionDB(path)
    try:
        retry = db.accept_runtime_command(
            "owner", "subagent.dispatch", "request-1", {"model": "custom", "goal": "fixture"},
            {"handle": "another-handle"}, {"dispatch": "do-not-use"},
        )
        assert retry["created"] is False
        assert retry["acceptance"]["handle"] == "attempt-1"
        assert retry["intent"] == {"dispatch": "attempt-1"}
        with pytest.raises(ValueError, match="different payload"):
            db.accept_runtime_command("owner", "subagent.dispatch", "request-1", {"goal": "changed"}, {}, {})
        assert db.get_runtime_command("other-owner", "subagent.dispatch", "request-1", {}) is None
        # Same caller request key is intentionally independent for another command kind.
        cancel = db.accept_runtime_command("owner", "subagent.interrupt", "request-1", {}, {"ok": True}, {})
        assert cancel["created"] is True
    finally:
        db.close()


def test_receipt_and_intent_roll_back_together(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    db.create_session("owner", "cli")
    db._conn.execute("""CREATE TRIGGER fail_receipt BEFORE INSERT ON runtime_command_receipts
        BEGIN SELECT RAISE(ABORT, 'fixture crash'); END""")
    published = []
    db.subscribe_session_events(published.append)
    with pytest.raises(Exception, match="fixture crash"):
        db.accept_runtime_command("owner", "subagent.dispatch", "r", {}, {}, {"child": "c"})
    assert db.get_runtime_command("owner", "subagent.dispatch", "r", {}) is None
    assert not published
    assert len(db.get_session_events("owner")) == 1  # only session.started
    db.close()
