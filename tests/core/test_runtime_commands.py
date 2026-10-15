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


def test_dispatch_receipt_family_excludes_forks_and_child_transcripts(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    try:
        db.create_session("root", "web")
        db.create_session("leaf", "web", parent_session_id="root")
        db._conn.execute("UPDATE sessions SET end_reason='compression' WHERE id='root'")
        db.create_session("fork", "web", parent_session_id="leaf")
        db.create_session("child-transcript", "delegate", parent_session_id="root")
        db.create_subagent_run({"id": "child", "parent_session_id": "root",
                                "child_session_id": "child-transcript", "status": "completed"})
        # A receipt created by an earlier app after compression may live on the
        # leaf rather than the canonical root. Recover it without moving it.
        original = db.accept_runtime_command("leaf", "subagent.dispatch", "r", {"goal": "one"},
                                             {"handle": "original"}, {})
        recovered = db.get_runtime_command("root", "subagent.dispatch", "r", {"goal": "one"},
                                            compression_family=True)
        assert recovered["acceptance"] == original["acceptance"]
        assert recovered["session_id"] == "leaf"
        assert db.get_runtime_command("root", "subagent.dispatch", "r", {"goal": "one"}) is None
        for unrelated in ("fork", "child-transcript"):
            assert db.get_runtime_command(unrelated, "subagent.dispatch", "r", {"goal": "one"},
                                          compression_family=True) is None
        with pytest.raises(ValueError, match="different payload"):
            db.accept_runtime_command("root", "subagent.dispatch", "r", {"goal": "changed"}, {}, {},
                                       compression_family=True)
        assert db._conn.execute("SELECT COUNT(*) FROM runtime_command_receipts").fetchone()[0] == 1
    finally:
        db.close()


def test_concurrent_acceptance_from_old_and_compressed_session_uses_one_receipt(tmp_path):
    path = tmp_path / "state.db"
    db = SessionDB(path)
    db.create_session("root", "web")
    db.create_session("leaf", "web", parent_session_id="root")
    db._conn.execute("UPDATE sessions SET end_reason='compression' WHERE id='root'")
    clients = [SessionDB(path) for _ in range(8)]
    try:
        def accept(item):
            index, client = item
            return client.accept_runtime_command(
                "root" if index % 2 else "leaf", "subagent.dispatch", "lost-ack", {"goal": "same"},
                {"handle": f"candidate-{index}"}, {}, compression_family=True,
            )
        with ThreadPoolExecutor(max_workers=len(clients)) as pool:
            receipts = list(pool.map(accept, enumerate(clients)))
        assert sum(receipt["created"] for receipt in receipts) == 1
        assert all(receipt["acceptance"] == receipts[0]["acceptance"] for receipt in receipts)
        assert db._conn.execute("SELECT COUNT(*) FROM runtime_command_receipts").fetchone()[0] == 1
        assert sum(len([e for e in db.get_session_events(owner)
                        if e["event_type"] == "runtime.command.accepted"]) for owner in ("root", "leaf")) == 1
    finally:
        for client in clients:
            client.close()
        db.close()
