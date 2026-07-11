"""Incremental persistence of web chat turns.

Covers the SessionDB update/delete primitives and the web-server turn
lifecycle: eager user persist at turn start, streaming assistant
checkpoints, and end-of-turn reconciliation (finalize vs dedupe).
A mid-turn crash must leave the user message and partial assistant text
recoverable from SQLite.
"""

import asyncio
import time

import pytest

from core.spark_state import SessionDB


@pytest.fixture(autouse=True)
def _reset_checkpoint_writer():
    from spark_cli import web_server

    web_server._checkpoint_writer.shutdown(timeout=1.0)
    yield
    web_server._checkpoint_writer.shutdown(timeout=1.0)


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
    def test_slow_database_does_not_block_token_callback(self, db, monkeypatch):
        from spark_cli import web_server

        sid = _make_session(db, "slow-checkpoint")
        eager_id = web_server._persist_web_user_message(sid, "question")
        turn = web_server._mark_web_turn_active(sid, active_agent_session_id=sid)
        turn.user_message_id = eager_id
        original = web_server._CheckpointWriter._write_request

        def delayed(database, request):
            time.sleep(0.5)
            return original(database, request)

        monkeypatch.setattr(
            web_server._CheckpointWriter, "_write_request", staticmethod(delayed)
        )
        try:
            started = time.perf_counter()
            web_server._append_web_turn_token(sid, "fast token")
            callback_seconds = time.perf_counter() - started
            assert callback_seconds < 0.05
            assert web_server._checkpoint_writer.flush(sid, turn, timeout=2.0)
            assert db.get_messages(sid)[-1]["content"] == "fast token"
        finally:
            web_server._clear_web_turn(sid)

    def test_many_revisions_coalesce_to_bounded_write_rate(self, db, monkeypatch):
        from spark_cli import web_server

        sid = _make_session(db, "coalesced-checkpoint")
        eager_id = web_server._persist_web_user_message(sid, "question")
        turn = web_server._mark_web_turn_active(sid, active_agent_session_id=sid)
        turn.user_message_id = eager_id
        monkeypatch.setattr(web_server, "_WEB_TURN_CHECKPOINT_INTERVAL_S", 0.05)
        before = web_server._streaming_pipeline_metrics.snapshot()["checkpoint_writes"]
        try:
            for _ in range(1_000):
                web_server._append_web_turn_token(sid, "x")
            assert web_server._checkpoint_writer.flush(sid, turn, timeout=2.0)
            writes = (
                web_server._streaming_pipeline_metrics.snapshot()["checkpoint_writes"]
                - before
            )
            assert writes <= 2
            assert db.get_messages(sid)[-1]["content"] == "x" * 1_000
        finally:
            web_server._clear_web_turn(sid)

    def test_transient_writer_failure_retries_without_losing_revision(self, db, monkeypatch):
        from spark_cli import web_server

        sid = _make_session(db, "retry-checkpoint")
        eager_id = web_server._persist_web_user_message(sid, "question")
        turn = web_server._mark_web_turn_active(sid, active_agent_session_id=sid)
        turn.user_message_id = eager_id
        original = web_server._CheckpointWriter._write_request
        attempts = 0

        def flaky(database, request):
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise TimeoutError("database is locked")
            return original(database, request)

        monkeypatch.setattr(web_server._CheckpointWriter, "_write_request", staticmethod(flaky))
        try:
            web_server._append_web_turn_token(sid, "eventual")
            assert web_server._checkpoint_writer.flush(sid, turn, timeout=2.0)
            assert attempts == 3
            assert db.get_messages(sid)[-1]["content"] == "eventual"
        finally:
            web_server._clear_web_turn(sid)

    def test_interrupted_turn_keeps_streamed_checkpoint_instead_of_diagnostic(self, db):
        from spark_cli import web_server

        sid = _make_session(db, "interrupted-partial")
        eager_id = web_server._persist_web_user_message(sid, "question")
        turn = web_server._mark_web_turn_active(sid, active_agent_session_id=sid)
        turn.user_message_id = eager_id
        try:
            web_server._append_web_turn_token(sid, "partial answer already shown")
            assert web_server._checkpoint_writer.flush(sid, turn, timeout=1.0)
            checkpoint_id = turn.assistant_message_id

            web_server._persist_web_turn_if_missing(
                sid,
                "question",
                {
                    "interrupted": True,
                    "final_response": "Operation interrupted: waiting for model response.",
                },
                before_message_count=1,
                eager_user_id=eager_id,
                checkpoint_assistant_id=checkpoint_id,
            )

            messages = db.get_messages(sid)
            assistant = [message for message in messages if message["role"] == "assistant"]
            assert len(assistant) == 1
            assert assistant[0]["content"] == "partial answer already shown"
            assert assistant[0]["finish_reason"] == "interrupted"
        finally:
            web_server._clear_web_turn(sid)

    def test_shutdown_forces_pending_checkpoint_before_interval(self, db, monkeypatch):
        from spark_cli import web_server

        sid = _make_session(db, "shutdown-checkpoint")
        turn = web_server._mark_web_turn_active(sid, active_agent_session_id=sid)
        turn.user_message_id = web_server._persist_web_user_message(sid, "question")
        turn.stream_text = "pending at shutdown"
        turn.stream_revision = 1
        turn.last_checkpoint_at = time.perf_counter()
        monkeypatch.setattr(web_server, "_WEB_TURN_CHECKPOINT_INTERVAL_S", 60.0)
        writer = web_server._CheckpointWriter()
        try:
            writer.mark_dirty(sid, turn)
            assert writer.pending_count == 1
            assert writer.shutdown(timeout=2.0)
            assert db.get_messages(sid)[-1]["content"] == "pending at shutdown"
        finally:
            writer.shutdown(timeout=1.0)
            web_server._clear_web_turn(sid)

    def test_dirty_revision_is_persisted_within_checkpoint_interval(self, db, monkeypatch):
        from spark_cli import web_server

        sid = _make_session(db, "crash-window-checkpoint")
        turn = web_server._mark_web_turn_active(sid, active_agent_session_id=sid)
        turn.user_message_id = web_server._persist_web_user_message(sid, "question")
        monkeypatch.setattr(web_server, "_WEB_TURN_CHECKPOINT_INTERVAL_S", 0.05)
        try:
            web_server._append_web_turn_token(sid, "first")
            assert web_server._checkpoint_writer.flush(sid, turn, timeout=1.0)
            web_server._append_web_turn_token(sid, " second")
            deadline = time.perf_counter() + 0.5
            while time.perf_counter() < deadline:
                if db.get_messages(sid)[-1]["content"] == "first second":
                    break
                time.sleep(0.01)
            assert db.get_messages(sid)[-1]["content"] == "first second"
        finally:
            web_server._clear_web_turn(sid)

    def test_inflight_timeout_blocks_finalization_until_writer_finishes(
        self, db, monkeypatch
    ):
        from spark_cli import web_server

        sid = _make_session(db, "blocked-finalization")
        turn = web_server._mark_web_turn_active(sid, active_agent_session_id=sid)
        turn.user_message_id = web_server._persist_web_user_message(sid, "question")
        original = web_server._CheckpointWriter._write_request
        write_started = __import__("threading").Event()
        release_write = __import__("threading").Event()

        def blocked(database, request):
            write_started.set()
            release_write.wait(2.0)
            return original(database, request)

        monkeypatch.setattr(
            web_server._CheckpointWriter,
            "_write_request",
            staticmethod(blocked),
        )
        monkeypatch.setattr(web_server, "_WEB_TURN_CHECKPOINT_FLUSH_TIMEOUT_S", 0.05)
        finalized = False
        try:
            web_server._append_web_turn_token(sid, "partial before blocked flush")
            assert write_started.wait(1.0)
            if web_server._force_checkpoint_or_block(
                sid, turn, operation="test_finalization"
            ):
                finalized = True

            assert finalized is False
            assert web_server._is_web_turn_active(sid) is True
            assert turn.phase == "checkpoint_blocked"
            assert [m for m in db.get_messages(sid) if m["role"] == "assistant"] == []

            release_write.set()
            deadline = time.perf_counter() + 1.0
            while time.perf_counter() < deadline:
                assistant = [m for m in db.get_messages(sid) if m["role"] == "assistant"]
                if assistant:
                    break
                time.sleep(0.01)
            assert assistant[-1]["content"] == "partial before blocked flush"
            # The late writer did not race a finalized/cleared turn: the
            # explicit blocker remains visible for deterministic recovery.
            assert web_server._is_web_turn_active(sid) is True
            assert turn.phase == "checkpoint_blocked"
        finally:
            release_write.set()
            web_server._checkpoint_writer.flush(sid, turn, timeout=1.0)
            web_server._clear_web_turn(sid)

    def test_async_checkpoint_barrier_keeps_loop_responsive_and_finalizes_eventually(
        self, db, monkeypatch
    ):
        from spark_cli import web_server

        sid = _make_session(db, "async-blocked-finalization")
        turn = web_server._mark_web_turn_active(sid, active_agent_session_id=sid)
        eager_id = web_server._persist_web_user_message(sid, "question")
        turn.user_message_id = eager_id
        before = len(db.get_messages(sid))
        original = web_server._CheckpointWriter._write_request
        write_started = __import__("threading").Event()
        release_write = __import__("threading").Event()

        def blocked(database, request):
            write_started.set()
            release_write.wait(2.0)
            return original(database, request)

        monkeypatch.setattr(
            web_server._CheckpointWriter,
            "_write_request",
            staticmethod(blocked),
        )
        monkeypatch.setattr(web_server, "_WEB_TURN_CHECKPOINT_FLUSH_TIMEOUT_S", 0.05)
        web_server._append_web_turn_token(sid, "partial")
        assert write_started.wait(1.0)

        async def wait_with_heartbeat():
            barrier = asyncio.create_task(
                web_server._await_checkpoint_ready(
                    sid, turn, operation="test_async_finalization"
                )
            )
            ticks = 0
            for _ in range(5):
                await asyncio.sleep(0.02)
                ticks += 1
            assert not barrier.done()
            release_write.set()
            await asyncio.wait_for(barrier, timeout=1.0)
            return ticks

        try:
            assert asyncio.run(wait_with_heartbeat()) == 5
            web_server._persist_web_turn_if_missing(
                sid,
                "question",
                {"final_response": "complete after slow checkpoint"},
                before,
                eager_user_id=eager_id,
                checkpoint_assistant_id=turn.assistant_message_id,
            )
            web_server._clear_web_turn(sid)
            assert web_server._is_web_turn_active(sid) is False
            assert db.get_messages(sid)[-1]["content"] == "complete after slow checkpoint"
        finally:
            release_write.set()
            web_server._clear_web_turn(sid)
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
            _, alpha_turn = web_server._get_web_turn(alpha)
            _, bravo_turn = web_server._get_web_turn(bravo)
            assert alpha_turn is not None and bravo_turn is not None
            alpha_turn.user_message_id = 1
            bravo_turn.user_message_id = 1
            web_server._append_web_turn_token(alpha, "ALPHA-01 ")
            web_server._append_web_turn_token(bravo, "BRAVO-01 ")
            web_server._append_web_turn_token(alpha, "ALPHA-02")

            web_server._checkpoint_web_turn(alpha, alpha_turn, force=True)
            web_server._checkpoint_web_turn(bravo, bravo_turn, force=True)

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
            assert alpha_rows == [("assistant", "ALPHA-01 ALPHA-02")]
            assert bravo_rows == [("assistant", "BRAVO-01 ")]

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
        assert [(m["role"], m["content"]) for m in msgs] == [
            ("user", "the question"),
            ("assistant", "the full final answer"),
        ]

    def test_agent_user_flush_cannot_move_question_after_partial_checkpoint(self, db):
        from spark_cli import web_server

        sid = _make_session(db, "checkpoint-order")
        eager_id, turn, before = self._start_turn(db, sid)

        # The agent flush happens after the checkpoint has already inserted
        # the assistant row. This is the ordering seen in real stopped turns.
        duplicate_user_id = db.append_message(sid, "user", content="the question")

        web_server._persist_web_turn_if_missing(
            sid,
            "the question",
            {"interrupted": True, "final_response": "Operation interrupted."},
            before,
            eager_user_id=eager_id,
            checkpoint_assistant_id=turn.assistant_message_id,
        )

        msgs = db.get_messages(sid)
        assert [(m["role"], m["content"]) for m in msgs] == [
            ("user", "the question"),
            ("assistant", "partial"),
        ]
        assert all(m["id"] != duplicate_user_id for m in msgs)

    def test_provider_failure_is_saved_as_actionable_assistant_error(self, db):
        from spark_cli import web_server

        sid = _make_session(db, "provider-model-failure")
        eager_id = web_server._persist_web_user_message(sid, "Hey")

        web_server._persist_web_turn_if_missing(
            sid,
            "Hey",
            {
                "failed": True,
                "final_response": None,
                "error": "HTTP 404: Model not found gpt-5.6-luna",
            },
            before_message_count=1,
            eager_user_id=eager_id,
        )

        messages = db.get_messages(sid)
        assert [(message["role"], message["content"]) for message in messages] == [
            ("user", "Hey"),
            (
                "assistant",
                "Model request failed: HTTP 404: Model not found gpt-5.6-luna",
            ),
        ]

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

    def test_migrated_turn_finalizes_into_leaf_session_not_parent_checkpoint(self, db):
        from spark_cli import web_server

        parent = _make_session(db, "compact-parent")
        leaf = _make_session(db, "compact-leaf")
        db.end_session(parent, "compressed")

        eager_id = web_server._persist_web_user_message(parent, "the question")
        before = len(db.get_messages(leaf))
        turn = web_server.WebActiveTurn(
            started_at=time.time(),
            last_event_at=time.time(),
            status="Running…",
            interrupt_requested=False,
            active_agent_session_id=parent,
            phase="streaming",
        )
        turn.stream_text = "partial before compaction"
        web_server._checkpoint_web_turn(parent, turn)
        assert turn.assistant_message_id is not None

        web_server._persist_web_turn_if_missing(
            leaf,
            "the question",
            {"final_response": "full answer after compaction"},
            before,
            eager_user_id=eager_id,
            checkpoint_assistant_id=turn.assistant_message_id,
        )

        parent_msgs = db.get_messages(parent)
        leaf_msgs = db.get_messages(leaf)
        assert [(m["role"], m["content"]) for m in leaf_msgs] == [
            ("assistant", "full answer after compaction"),
        ]
        assert [m for m in parent_msgs if m["role"] == "assistant"] == []
def test_chunked_stream_ingests_and_recovers_ten_megabytes_linearly():
    """Regression: token ingestion must not rebuild the accumulated response."""
    from spark_cli import web_server

    turn = web_server.WebActiveTurn(
        started_at=time.time(),
        last_event_at=time.time(),
        status="Streaming",
        interrupt_requested=False,
        active_agent_session_id="large-stream",
        phase="streaming",
    )
    chunk = "0123456789" * 100
    started = time.perf_counter()
    for _ in range(10_000):
        turn.stream_text.append(chunk)
    append_seconds = time.perf_counter() - started

    assert len(turn.stream_text) == 10_000_000
    assert append_seconds < 2.0
    snapshot = turn.stream_text.snapshot()
    assert len(snapshot[0]) == 10_000
    recovered = web_server._ChunkedStreamText.materialize(snapshot)
    assert len(recovered) == 10_000_000
    assert recovered[:1000] == chunk
    assert recovered[-1000:] == chunk
