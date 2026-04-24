"""Tests for core/spark_state.py — SessionDB.

Covers: session lifecycle, message storage, FTS search, title management,
schema migrations (fresh-database path), WAL retry logic, and token accounting.
"""

import sqlite3
import threading
import time
import uuid
from pathlib import Path

import pytest

from core.spark_state import SessionDB


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sid() -> str:
    return str(uuid.uuid4())


@pytest.fixture()
def db(tmp_path) -> SessionDB:
    """A fresh in-memory-equivalent SessionDB for each test."""
    return SessionDB(db_path=tmp_path / "test_state.db")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class TestSchemaInit:
    def test_tables_exist(self, db):
        conn = db._conn
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "sessions" in tables
        assert "messages" in tables
        assert "schema_version" in tables

    def test_schema_version_is_current(self, db):
        from core.spark_state import SCHEMA_VERSION
        row = db._conn.execute("SELECT version FROM schema_version").fetchone()
        assert row is not None
        assert row[0] == SCHEMA_VERSION

    def test_fts_table_exists(self, db):
        tables = {r[0] for r in db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "messages_fts" in tables

    def test_wal_mode_active(self, db):
        row = db._conn.execute("PRAGMA journal_mode").fetchone()
        assert row[0].lower() == "wal"


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

class TestSessionLifecycle:
    def test_create_and_get(self, db):
        sid = _sid()
        db.create_session(sid, source="cli", model="test/model")
        session = db.get_session(sid)
        assert session is not None
        assert session["id"] == sid
        assert session["source"] == "cli"
        assert session["model"] == "test/model"
        assert session["ended_at"] is None

    def test_create_idempotent(self, db):
        sid = _sid()
        db.create_session(sid, source="cli")
        db.create_session(sid, source="cli")  # INSERT OR IGNORE — no error
        assert db.get_session(sid) is not None

    def test_end_session(self, db):
        sid = _sid()
        db.create_session(sid, source="cli")
        db.end_session(sid, end_reason="user_exit")
        session = db.get_session(sid)
        assert session["end_reason"] == "user_exit"
        assert session["ended_at"] is not None

    def test_reopen_session(self, db):
        sid = _sid()
        db.create_session(sid, source="cli")
        db.end_session(sid, end_reason="user_exit")
        db.reopen_session(sid)
        session = db.get_session(sid)
        assert session["ended_at"] is None
        assert session["end_reason"] is None

    def test_get_nonexistent_returns_none(self, db):
        assert db.get_session("does-not-exist") is None

    def test_ensure_session_creates_if_missing(self, db):
        sid = _sid()
        db.ensure_session(sid, source="gateway", model="gpt-4o")
        session = db.get_session(sid)
        assert session is not None
        assert session["source"] == "gateway"

    def test_ensure_session_noop_if_exists(self, db):
        sid = _sid()
        db.create_session(sid, source="cli", model="claude-3-5-sonnet")
        db.ensure_session(sid, source="gateway")  # should not overwrite
        session = db.get_session(sid)
        assert session["source"] == "cli"  # original value preserved

    def test_resolve_session_id_exact(self, db):
        sid = _sid()
        db.create_session(sid, source="cli")
        assert db.resolve_session_id(sid) == sid

    def test_resolve_session_id_prefix(self, db):
        sid = _sid()
        db.create_session(sid, source="cli")
        prefix = sid[:8]
        resolved = db.resolve_session_id(prefix)
        assert resolved == sid

    def test_resolve_session_id_ambiguous_returns_none(self, db):
        # Two sessions with the same prefix (force it by using deterministic UUIDs)
        prefix = "aaaaaaaa"
        sid1 = prefix + "-" + str(uuid.uuid4())[8:]
        sid2 = prefix + "-" + str(uuid.uuid4())[8:]
        db.create_session(sid1, source="cli")
        db.create_session(sid2, source="cli")
        assert db.resolve_session_id(prefix) is None

    def test_parent_session_id(self, db):
        parent = _sid()
        child = _sid()
        db.create_session(parent, source="cli")
        db.create_session(child, source="cli", parent_session_id=parent)
        session = db.get_session(child)
        assert session["parent_session_id"] == parent


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

class TestMessages:
    def test_add_and_retrieve_message(self, db):
        sid = _sid()
        db.create_session(sid, source="cli")
        db.append_message(sid, role="user", content="Hello!")
        msgs = db.get_messages(sid)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "Hello!"

    def test_message_order_preserved(self, db):
        sid = _sid()
        db.create_session(sid, source="cli")
        for i in range(5):
            db.append_message(sid, role="user" if i % 2 == 0 else "assistant",
                           content=f"msg {i}")
        msgs = db.get_messages(sid)
        for i, m in enumerate(msgs):
            assert m["content"] == f"msg {i}"

    def test_empty_session_returns_empty_list(self, db):
        sid = _sid()
        db.create_session(sid, source="cli")
        assert db.get_messages(sid) == []

    def test_messages_isolated_per_session(self, db):
        s1, s2 = _sid(), _sid()
        db.create_session(s1, source="cli")
        db.create_session(s2, source="cli")
        db.append_message(s1, role="user", content="session one")
        db.append_message(s2, role="user", content="session two")
        assert len(db.get_messages(s1)) == 1
        assert db.get_messages(s1)[0]["content"] == "session one"


# ---------------------------------------------------------------------------
# Token accounting
# ---------------------------------------------------------------------------

class TestTokenCounting:
    def test_increment_tokens(self, db):
        sid = _sid()
        db.create_session(sid, source="cli")
        db.update_token_counts(sid, input_tokens=100, output_tokens=50)
        db.update_token_counts(sid, input_tokens=200, output_tokens=75)
        session = db.get_session(sid)
        assert session["input_tokens"] == 300
        assert session["output_tokens"] == 125

    def test_absolute_tokens(self, db):
        sid = _sid()
        db.create_session(sid, source="cli")
        db.update_token_counts(sid, input_tokens=100, output_tokens=50)
        db.update_token_counts(sid, input_tokens=500, output_tokens=200, absolute=True)
        session = db.get_session(sid)
        assert session["input_tokens"] == 500
        assert session["output_tokens"] == 200

    def test_cache_tokens(self, db):
        sid = _sid()
        db.create_session(sid, source="cli")
        db.update_token_counts(sid, cache_read_tokens=10, cache_write_tokens=20)
        session = db.get_session(sid)
        assert session["cache_read_tokens"] == 10
        assert session["cache_write_tokens"] == 20


# ---------------------------------------------------------------------------
# Title management
# ---------------------------------------------------------------------------

class TestTitles:
    def test_set_and_get_title(self, db):
        sid = _sid()
        db.create_session(sid, source="cli")
        result = db.set_session_title(sid, "My Test Session")
        assert result is True
        assert db.get_session_title(sid) == "My Test Session"

    def test_title_uniqueness_enforced(self, db):
        s1, s2 = _sid(), _sid()
        db.create_session(s1, source="cli")
        db.create_session(s2, source="cli")
        db.set_session_title(s1, "Unique Title")
        with pytest.raises(ValueError, match="already in use"):
            db.set_session_title(s2, "Unique Title")

    def test_session_can_keep_its_own_title(self, db):
        sid = _sid()
        db.create_session(sid, source="cli")
        db.set_session_title(sid, "My Title")
        # Re-setting the same title on the same session must not raise
        assert db.set_session_title(sid, "My Title") is True

    def test_get_session_by_title(self, db):
        sid = _sid()
        db.create_session(sid, source="cli")
        db.set_session_title(sid, "Findable")
        result = db.get_session_by_title("Findable")
        assert result is not None
        assert result["id"] == sid

    def test_get_session_by_title_missing_returns_none(self, db):
        assert db.get_session_by_title("nonexistent") is None

    def test_sanitize_title_strips_controls(self):
        cleaned = SessionDB.sanitize_title("Hello\x00World")
        assert cleaned == "Hello World" or cleaned == "HelloWorld"
        assert "\x00" not in (cleaned or "")

    def test_sanitize_title_none_and_empty(self):
        assert SessionDB.sanitize_title(None) is None
        assert SessionDB.sanitize_title("") is None
        assert SessionDB.sanitize_title("   ") is None

    def test_sanitize_title_too_long_raises(self):
        with pytest.raises(ValueError, match="Title too long"):
            SessionDB.sanitize_title("x" * 101)

    def test_next_title_in_lineage(self, db):
        sid1, sid2 = _sid(), _sid()
        db.create_session(sid1, source="cli")
        db.create_session(sid2, source="cli")
        db.set_session_title(sid1, "Project")
        next_title = db.get_next_title_in_lineage("Project")
        assert next_title == "Project #2"

    def test_resolve_session_by_title_numbered_variant(self, db):
        sid1, sid2 = _sid(), _sid()
        db.create_session(sid1, source="cli")
        time.sleep(0.01)  # ensure different started_at
        db.create_session(sid2, source="cli")
        db.set_session_title(sid1, "Work")
        db.set_session_title(sid2, "Work #2")
        resolved = db.resolve_session_by_title("Work")
        assert resolved == sid2  # latest numbered variant wins


# ---------------------------------------------------------------------------
# FTS search
# ---------------------------------------------------------------------------

class TestFTSSearch:
    def test_fts_finds_message(self, db):
        sid = _sid()
        db.create_session(sid, source="cli")
        db.append_message(sid, role="user", content="the quick brown fox")
        results = db.search_messages("quick")
        assert any(r.get("session_id") == sid for r in results)

    def test_fts_no_match(self, db):
        sid = _sid()
        db.create_session(sid, source="cli")
        db.append_message(sid, role="user", content="completely unrelated")
        results = db.search_messages("xyznotfound")
        assert not any(r.get("session_id") == sid for r in results)


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------

class TestThreadSafety:
    def test_concurrent_writes_dont_corrupt(self, db):
        """Concurrent writes via separate threads must not raise or corrupt data."""
        errors = []
        sids = [_sid() for _ in range(10)]
        for sid in sids:
            db.create_session(sid, source="cli")

        def _write(sid):
            try:
                for _ in range(5):
                    db.update_token_counts(sid, input_tokens=1)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_write, args=(sid,)) for sid in sids]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"Concurrent write errors: {errors}"
        # Verify token counts are correct (5 increments × 1 = 5 each)
        for sid in sids:
            session = db.get_session(sid)
            assert session["input_tokens"] == 5
