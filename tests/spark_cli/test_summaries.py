"""Tests for file summary storage and /api/summarize-file endpoint (Phase 4)."""

import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from spark_cli.web_server import app
    return TestClient(app)


# ── Summary DB unit tests ─────────────────────────────────────────────────────

def test_summary_round_trip(tmp_path, monkeypatch, tmp_path_factory):
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    from core.spark_state import SessionDB
    db = SessionDB()
    fake_path = str(tmp_path / "file.py")
    db.set_summary(fake_path, 1024, 1234567890.0, "This is a summary.")
    result = db.get_summary(fake_path, 1024, 1234567890.0)
    assert result == "This is a summary."
    db.close()


def test_summary_cache_miss_on_different_mtime(tmp_path, monkeypatch):
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    from core.spark_state import SessionDB
    db = SessionDB()
    fake_path = str(tmp_path / "file.py")
    db.set_summary(fake_path, 1024, 1000.0, "old summary")
    result = db.get_summary(fake_path, 1024, 2000.0)
    assert result is None
    db.close()


def test_summary_freshness_check(tmp_path, monkeypatch):
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    real_file = tmp_path / "real.py"
    real_file.write_text("def foo(): pass")
    from core.spark_state import SessionDB
    db = SessionDB()
    st = real_file.stat()
    db.set_summary(str(real_file), st.st_size, st.st_mtime, "cached summary")
    is_fresh, text = db.is_summary_fresh(str(real_file))
    assert is_fresh is True
    assert text == "cached summary"
    db.close()


def test_summary_stale_after_file_change(tmp_path, monkeypatch):
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    real_file = tmp_path / "changed.py"
    real_file.write_text("original")
    from core.spark_state import SessionDB
    import time
    db = SessionDB()
    st = real_file.stat()
    db.set_summary(str(real_file), st.st_size, st.st_mtime, "stale summary")
    # Modify file
    time.sleep(0.01)
    real_file.write_text("modified content that is longer")
    is_fresh, text = db.is_summary_fresh(str(real_file))
    assert is_fresh is False
    assert text is None
    db.close()


# ── REST endpoint tests ───────────────────────────────────────────────────────

def test_summarize_rejects_path_traversal(client):
    r = client.post("/api/summarize-file", json={"path": "../../etc/passwd"})
    assert r.status_code == 400


def test_summarize_rejects_binary_file(client, tmp_path, monkeypatch):
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    ws = tmp_path / "workspace"
    ws.mkdir()
    binary_file = ws / "image.png"
    binary_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    r = client.post("/api/summarize-file", json={"path": "image.png"})
    assert r.status_code == 400
    assert "binary" in r.json()["detail"].lower()


def test_summarize_rejects_oversized_file(client, tmp_path, monkeypatch):
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    ws = tmp_path / "workspace"
    ws.mkdir()
    big_file = ws / "big.py"
    big_file.write_text("x" * (3 * 1024 * 1024))  # 3MB > 2MB limit
    r = client.post("/api/summarize-file", json={"path": "big.py"})
    assert r.status_code == 400
    assert "large" in r.json()["detail"].lower()


def test_summaries_stored_outside_workspace(tmp_path, monkeypatch):
    """Summaries must be stored in SPARK_HOME, not inside the workspace."""
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    from core.spark_state import SessionDB
    db = SessionDB()
    ws = tmp_path / "workspace"
    ws.mkdir()
    fake_file = ws / "code.py"
    # Store a summary
    db.set_summary(str(fake_file), 100, 1000.0, "summary text")
    # Check no files were written into the workspace directory
    summary_files_in_ws = list(ws.rglob("*.summary")) + list(ws.rglob("*_summary*"))
    assert len(summary_files_in_ws) == 0, "Summaries should not be in the workspace dir"
    db.close()
