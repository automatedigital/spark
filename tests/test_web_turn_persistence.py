"""Incremental persistence of web chat turns.

Covers the SessionDB update/delete primitives and the web-server turn
lifecycle: eager user persist at turn start, streaming assistant
checkpoints, and end-of-turn reconciliation (finalize vs dedupe).
A mid-turn crash must leave the user message and partial assistant text
recoverable from SQLite.
"""

import time

import pytest

from core.spark_state import SessionDB


@pytest.fixture()
def db():
    database = SessionDB()
    yield database
    database.close()


def _make_session(db: SessionDB, session_id: str = "web-turn-test") -> str:
    db.ensure_session(session_id, source="web", model="test-model")
    return session_id


class TestUpdateMessage:
    def test_updates_content_and_clears_finish_reason(self, db):
        sid = _make_session(db)
        mid = db.append_message(sid, "assistant", content="partial", finish_reason="interrupted")

        assert db.update_message(mid, content="full answer", finish_reason="") is True

        msgs = db.get_messages(sid)
        assert len(msgs) == 1
        assert msgs[0]["content"] == "full answer"
        assert msgs[0]["finish_reason"] is None

    def test_does_not_bump_message_count(self, db):
        sid = _make_session(db)
        mid = db.append_message(sid, "assistant", content="one")
        before = db.message_count(sid)
        db.update_message(mid, content="two")
        assert db.message_count(sid) == before

    def test_fts_reflects_updated_content(self, db):
        sid = _make_session(db)
        mid = db.append_message(sid, "assistant", content="alpha bravo")
        db.update_message(mid, content="charlie delta")

        assert any(sid == r.get("session_id") for r in db.search_messages("charlie"))
        assert not any(sid == r.get("session_id") for r in db.search_messages("bravo"))

    def test_missing_row_returns_false(self, db):
        assert db.update_message(999_999, content="x") is False


class TestDeleteMessage:
    def test_deletes_and_decrements_count(self, db):
        sid = _make_session(db)
        mid = db.append_message(sid, "assistant", content="dup")
        count = db.message_count(sid)

        assert db.delete_message(mid) is True
        assert db.get_messages(sid) == []
        assert db.message_count(sid) == count - 1

    def test_missing_row_returns_false(self, db):
        assert db.delete_message(999_999) is False


class TestStreamingCheckpoint:
    def test_first_checkpoint_inserts_interrupted_then_updates(self, db):
        from spark_cli import web_server

        sid = _make_session(db, "checkpoint-session")
        turn = web_server.WebActiveTurn(
            started_at=time.time(),
            last_event_at=time.time(),
            status="Running…",
            interrupt_requested=False,
            active_agent_session_id=sid,
            phase="streaming",
        )

        turn.stream_text = "partial answer "
        web_server._checkpoint_web_turn(sid, turn)
        assert turn.assistant_message_id is not None
        msgs = db.get_messages(sid)
        assert len(msgs) == 1
        assert msgs[0]["content"] == "partial answer "
        assert msgs[0]["finish_reason"] == "interrupted"

        # More tokens inside the throttle window do not rewrite the row on
        # every chunk; the final forced checkpoint preserves the full answer.
        turn.stream_text += "more text"
        web_server._checkpoint_web_turn(sid, turn)
        msgs = db.get_messages(sid)
        assert len(msgs) == 1
        assert msgs[0]["content"] == "partial answer "

        web_server._checkpoint_web_turn(sid, turn, force=True)
        msgs = db.get_messages(sid)
        assert len(msgs) == 1
        assert msgs[0]["content"] == "partial answer more text"

    def test_crash_mid_turn_leaves_recoverable_transcript(self, db):
        from spark_cli import web_server

        sid = _make_session(db, "crash-session")
        eager_id = web_server._persist_web_user_message(sid, "please do the thing")
        assert eager_id is not None

        turn = web_server.WebActiveTurn(
            started_at=time.time(),
            last_event_at=time.time(),
            status="Running…",
            interrupt_requested=False,
            active_agent_session_id=sid,
            phase="streaming",
        )
        turn.stream_text = "streamed half an answer"
        web_server._checkpoint_web_turn(sid, turn)

        # Simulated crash: no finalize runs. History must still show the turn.
        roles = [(m["role"], m["content"]) for m in db.get_messages(sid)]
        assert ("user", "please do the thing") in roles
        assert ("assistant", "streamed half an answer") in roles

    def test_crash_checkpoint_stays_with_originating_session(self, db):
        from spark_cli import web_server

        alpha = _make_session(db, "crash-alpha")
        bravo = _make_session(db, "crash-bravo")
        web_server._persist_web_user_message(alpha, "alpha prompt")
        web_server._persist_web_user_message(bravo, "bravo prompt")

        alpha_turn = web_server.WebActiveTurn(
            started_at=time.time(),
            last_event_at=time.time(),
            status="Running…",
            interrupt_requested=False,
            active_agent_session_id=alpha,
            phase="streaming",
        )
        bravo_turn = web_server.WebActiveTurn(
            started_at=time.time(),
            last_event_at=time.time(),
            status="Running…",
            interrupt_requested=False,
            active_agent_session_id=bravo,
            phase="streaming",
        )
        alpha_turn.stream_text = "alpha partial"
        bravo_turn.stream_text = "bravo partial"
        web_server._checkpoint_web_turn(alpha, alpha_turn)
        web_server._checkpoint_web_turn(bravo, bravo_turn)

        alpha_rows = [(m["role"], m["content"]) for m in db.get_messages(alpha)]
        bravo_rows = [(m["role"], m["content"]) for m in db.get_messages(bravo)]
        assert ("assistant", "alpha partial") in alpha_rows
        assert ("assistant", "bravo partial") not in alpha_rows
        assert ("assistant", "bravo partial") in bravo_rows
        assert ("assistant", "alpha partial") not in bravo_rows

    def test_concurrent_active_turn_tokens_checkpoint_separately(self, db):
        from spark_cli import web_server

        alpha = _make_session(db, "concurrent-alpha")
        bravo = _make_session(db, "concurrent-bravo")
        web_server._persist_web_user_message(alpha, "alpha question")
        web_server._persist_web_user_message(bravo, "bravo question")
        web_server._mark_web_turn_active(alpha, active_agent_session_id=alpha)
        web_server._mark_web_turn_active(bravo, active_agent_session_id=bravo)
        try:
            web_server._append_web_turn_token(alpha, "ALPHA-01 ")
            web_server._append_web_turn_token(bravo, "BRAVO-01 ")
            web_server._append_web_turn_token(alpha, "ALPHA-02")

            alpha_rows = [
                (m["role"], m["content"])
                for m in db.get_messages(alpha)
                if m["role"] == "assistant"
            ]
            bravo_rows = [
                (m["role"], m["content"])
                for m in db.get_messages(bravo)
                if m["role"] == "assistant"
            ]
            assert alpha_rows == [("assistant", "ALPHA-01 ")]
            assert bravo_rows == [("assistant", "BRAVO-01 ")]

            _, alpha_turn = web_server._get_web_turn(alpha)
            assert alpha_turn is not None
            web_server._checkpoint_web_turn(alpha, alpha_turn, force=True)
            alpha_rows = [
                (m["role"], m["content"])
                for m in db.get_messages(alpha)
                if m["role"] == "assistant"
            ]
            assert alpha_rows == [("assistant", "ALPHA-01 ALPHA-02")]
        finally:
            web_server._clear_web_turn(alpha)
            web_server._clear_web_turn(bravo)

    def test_active_turn_tokens_do_not_resolve_ids_per_token(self, db, monkeypatch):
        from spark_cli import web_server

        sid = _make_session(db, "hotpath-no-resolve")
        web_server._mark_web_turn_active(sid, active_agent_session_id=sid)
        try:
            def fail_resolve(_session_id):
                raise AssertionError("hot token path should use cached turn aliases")

            with monkeypatch.context() as m:
                m.setattr(web_server, "_resolve_web_turn_ids", fail_resolve)
                web_server._append_web_turn_token(sid, "hello")
            _, turn = web_server._get_web_turn(sid)
            assert turn is not None
            assert turn.stream_text == "hello"
        finally:
            web_server._clear_web_turn(sid)


class TestEndOfTurnReconciliation:
    def _start_turn(self, db, sid):
        from spark_cli import web_server

        eager_id = web_server._persist_web_user_message(sid, "the question")
        before = len(db.get_messages(sid))
        turn = web_server.WebActiveTurn(
            started_at=time.time(),
            last_event_at=time.time(),
            status="Running…",
            interrupt_requested=False,
            active_agent_session_id=sid,
            phase="streaming",
        )
        turn.stream_text = "partial"
        web_server._checkpoint_web_turn(sid, turn)
        return eager_id, turn, before

    def test_finalizes_checkpoint_when_agent_flush_missing(self, db):
        from spark_cli import web_server

        sid = _make_session(db, "finalize-session")
        eager_id, turn, before = self._start_turn(db, sid)

        web_server._persist_web_turn_if_missing(
            sid,
            "the question",
            {"final_response": "the full final answer"},
            before,
            eager_user_id=eager_id,
            checkpoint_assistant_id=turn.assistant_message_id,
        )

        msgs = db.get_messages(sid)
        assert [(m["role"], m["content"]) for m in msgs] == [
            ("user", "the question"),
            ("assistant", "the full final answer"),
        ]
        assert msgs[1]["finish_reason"] is None

    def test_deletes_eager_rows_when_agent_flushed_its_own(self, db):
        from spark_cli import web_server

        sid = _make_session(db, "dedupe-session")
        eager_id, turn, before = self._start_turn(db, sid)

        # Simulate the agent's own end-of-turn flush.
        db.append_message(sid, "user", content="the question")
        db.append_message(sid, "assistant", content="the full final answer")

        web_server._persist_web_turn_if_missing(
            sid,
            "the question",
            {"final_response": "the full final answer"},
            before,
            eager_user_id=eager_id,
            checkpoint_assistant_id=turn.assistant_message_id,
        )

        msgs = db.get_messages(sid)
        assert len([m for m in msgs if m["role"] == "user"]) == 1
        assert len([m for m in msgs if m["role"] == "assistant"]) == 1

    def test_interrupted_turn_keeps_partial_checkpoint(self, db):
        from spark_cli import web_server

        sid = _make_session(db, "interrupted-session")
        eager_id, turn, before = self._start_turn(db, sid)

        web_server._persist_web_turn_if_missing(
            sid,
            "the question",
            {"backend_error_class": "RuntimeError"},
            before,
            eager_user_id=eager_id,
            checkpoint_assistant_id=turn.assistant_message_id,
        )

        msgs = db.get_messages(sid)
        assistant = [m for m in msgs if m["role"] == "assistant"]
        assert len(assistant) == 1
        assert assistant[0]["content"] == "partial"
        assert assistant[0]["finish_reason"] == "interrupted"
        assert len([m for m in msgs if m["role"] == "user"]) == 1

    def test_ignores_pre_turn_assistant_summary_when_finalizing_leaf(self, db):
        from spark_cli import web_server

        sid = _make_session(db, "leaf-with-summary")
        db.append_message(sid, "system", content="compressed context summary")
        db.append_message(sid, "assistant", content="summary assistant note")
        db.append_message(sid, "user", content="current question")

        web_server._persist_web_turn_if_missing(
            sid,
            "current question",
            {"final_response": "current final answer"},
            before_message_count=0,
        )

        msgs = db.get_messages(sid)
        assert [(m["role"], m["content"]) for m in msgs] == [
            ("system", "compressed context summary"),
            ("assistant", "summary assistant note"),
            ("user", "current question"),
            ("assistant", "current final answer"),
        ]

    def test_finalizes_checkpoint_after_switch_away_without_agent_flush(self, db):
        from spark_cli import web_server

        sid = _make_session(db, "switch-away-finalize")
        eager_id, turn, before = self._start_turn(db, sid)

        # The UI can switch to another session while the worker thread keeps
        # streaming. If the agent does not write its own final assistant row,
        # the live checkpoint row must become the final persisted answer.
        web_server._persist_web_turn_if_missing(
            sid,
            "the question",
            {"final_response": "full answer after user switched away"},
            before,
            eager_user_id=eager_id,
            checkpoint_assistant_id=turn.assistant_message_id,
        )

        msgs = db.get_messages(sid)
        assert [(m["role"], m["content"]) for m in msgs] == [
            ("user", "the question"),
            ("assistant", "full answer after user switched away"),
        ]
        assert msgs[1]["finish_reason"] is None
