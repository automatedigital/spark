"""Tests for context item validation, persistence, and message augmentation."""
import json
import os
import tempfile
import time
from pathlib import Path

import pytest


@pytest.fixture()
def spark_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


@pytest.fixture()
def db(spark_home):
    from core.spark_state import SessionDB
    d = SessionDB()
    yield d
    d.close()


def _make_session(db, session_id="test_session_001"):
    db._conn.execute(
        "INSERT OR IGNORE INTO sessions (id, source, started_at) VALUES (?, 'web', ?)",
        (session_id, time.time()),
    )
    db._conn.commit()
    return session_id


class TestContextItemValidation:
    def test_empty_items_ok(self, spark_home):
        from spark_cli.web_server import _validate_context_items
        assert _validate_context_items([]) == []

    def test_count_cap_enforced(self, spark_home):
        from fastapi import HTTPException
        from spark_cli.web_server import _validate_context_items
        items = [{"id": str(i), "type": "file", "inclusion_mode": "path_only"} for i in range(21)]
        with pytest.raises(HTTPException) as exc:
            _validate_context_items(items)
        assert exc.value.status_code == 400
        assert "Too many" in exc.value.detail

    def test_path_traversal_rejected(self, spark_home):
        from fastapi import HTTPException
        from spark_cli.web_server import _validate_context_items
        item = {"id": "x", "type": "file", "source_path": "../../etc/passwd", "inclusion_mode": "full"}
        with pytest.raises(HTTPException) as exc:
            _validate_context_items([item])
        assert exc.value.status_code == 400
        assert "traversal" in exc.value.detail.lower()

    def test_size_cap_enforced_for_full_mode(self, spark_home):
        from fastapi import HTTPException
        from spark_cli.web_server import _validate_context_items
        item = {"id": "big", "type": "file", "source_path": "foo.py", "inclusion_mode": "full", "size_bytes": 600 * 1024}
        with pytest.raises(HTTPException) as exc:
            _validate_context_items([item])
        assert exc.value.status_code == 400
        assert "size limit" in exc.value.detail.lower()

    def test_size_cap_not_enforced_for_path_only(self, spark_home):
        from spark_cli.web_server import _validate_context_items
        item = {"id": "big", "type": "file", "source_path": "foo.py", "inclusion_mode": "path_only", "size_bytes": 600 * 1024}
        result = _validate_context_items([item])
        assert len(result) == 1

    def test_valid_item_passes(self, spark_home):
        from spark_cli.web_server import _validate_context_items
        item = {"id": "ok", "type": "file", "source_path": "src/main.py", "inclusion_mode": "full", "size_bytes": 1024}
        result = _validate_context_items([item])
        assert len(result) == 1
        assert result[0]["id"] == "ok"


class TestContextItemPersistence:
    def test_persist_and_retrieve(self, db, spark_home):
        from spark_cli.web_server import _persist_context_items
        sid = _make_session(db)
        items = [{"id": "ci1", "type": "file", "source_path": "foo.py", "inclusion_mode": "full",
                  "scope": "one_turn", "size_bytes": 100, "content": None, "content_ref": None,
                  "excerpt_range": None, "search_query": None, "label": "foo.py"}]
        _persist_context_items(sid, items)

        rows = db._conn.execute(
            "SELECT id, source_path, inclusion_mode FROM context_items WHERE session_id=?", (sid,)
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["id"] == "ci1"
        assert rows[0]["source_path"] == "foo.py"
        assert rows[0]["inclusion_mode"] == "full"

    def test_empty_list_is_noop(self, db, spark_home):
        from spark_cli.web_server import _persist_context_items
        sid = _make_session(db)
        _persist_context_items(sid, [])
        count = db._conn.execute("SELECT COUNT(*) FROM context_items WHERE session_id=?", (sid,)).fetchone()[0]
        assert count == 0


class TestContextMessageAugmentation:
    def test_path_only_adds_header_not_content(self, spark_home, tmp_path):
        workspace = spark_home / "workspace"
        workspace.mkdir(parents=True)
        (workspace / "test.py").write_text("secret content")

        from spark_cli.web_server import _build_context_augmented_message
        items = [{"id": "x", "type": "file", "source_path": "test.py", "inclusion_mode": "path_only",
                  "content": None, "label": "test.py", "excerpt_range": None, "search_query": None}]
        result = _build_context_augmented_message("sid", "hello", items)
        assert "secret content" not in result
        assert "test.py" in result
        assert "hello" in result

    def test_full_mode_inlines_content(self, spark_home):
        workspace = spark_home / "workspace"
        workspace.mkdir(parents=True)
        (workspace / "data.txt").write_text("important data here")

        from spark_cli.web_server import _build_context_augmented_message
        items = [{"id": "x", "type": "file", "source_path": "data.txt", "inclusion_mode": "full",
                  "content": None, "label": "data.txt", "excerpt_range": None, "search_query": None}]
        result = _build_context_augmented_message("sid", "use this", items)
        assert "important data here" in result
        assert "use this" in result

    def test_empty_items_returns_original_message(self, spark_home):
        from spark_cli.web_server import _build_context_augmented_message
        result = _build_context_augmented_message("sid", "hello world", [])
        assert result == "hello world"

    def test_search_mode_returns_matching_lines(self, spark_home):
        workspace = spark_home / "workspace"
        workspace.mkdir(parents=True)
        content = "\n".join(["line1", "line2", "find me here", "line4", "line5"])
        (workspace / "search.txt").write_text(content)

        from spark_cli.web_server import _build_context_augmented_message
        items = [{"id": "x", "type": "file", "source_path": "search.txt", "inclusion_mode": "search",
                  "content": None, "label": "search.txt", "excerpt_range": None, "search_query": "find me"}]
        result = _build_context_augmented_message("sid", "search this", items)
        assert "find me here" in result
        assert "search this" in result

    def test_traversal_path_excluded_silently(self, spark_home):
        from spark_cli.web_server import _build_context_augmented_message
        items = [{"id": "x", "type": "file", "source_path": "../../etc/passwd", "inclusion_mode": "full",
                  "content": None, "label": "passwd", "excerpt_range": None, "search_query": None}]
        result = _build_context_augmented_message("sid", "hello", items)
        assert "hello" in result
        assert "passwd" not in result or result == "hello"
