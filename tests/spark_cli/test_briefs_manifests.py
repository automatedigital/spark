"""Tests for session brief and workspace manifest storage (Phase 3)."""

import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from spark_cli.web_server import app
    return TestClient(app)


# ── Brief unit tests (SessionDB) ─────────────────────────────────────────────

def test_brief_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    from core.spark_state import SessionDB
    db = SessionDB()
    # Create a session first (brief has FK on sessions)
    sid = "test-session-1"
    db.create_session(session_id=sid, source="web")
    db.set_brief(sid, "Key decision: use SQLite.")
    assert db.get_brief(sid) == "Key decision: use SQLite."
    db.close()


def test_brief_isolation_across_sessions(tmp_path, monkeypatch):
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    from core.spark_state import SessionDB
    db = SessionDB()
    s1 = "sess-a"
    s2 = "sess-b"
    db.create_session(session_id=s1, source="web")
    db.create_session(session_id=s2, source="web")
    db.set_brief(s1, "Brief for session 1")
    assert db.get_brief(s2) is None
    db.close()


def test_brief_update_overwrites(tmp_path, monkeypatch):
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    from core.spark_state import SessionDB
    db = SessionDB()
    sid = "sess-c"
    db.create_session(session_id=sid, source="web")
    db.set_brief(sid, "first")
    db.set_brief(sid, "second")
    assert db.get_brief(sid) == "second"
    db.close()


def test_brief_deleted_with_session(tmp_path, monkeypatch):
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    from core.spark_state import SessionDB
    db = SessionDB()
    sid = "sess-d"
    db.create_session(session_id=sid, source="web")
    db.set_brief(sid, "some text")
    db.delete_session(sid)
    # After deletion, brief should be gone (CASCADE)
    assert db.get_brief(sid) is None
    db.close()


# ── Manifest unit tests ───────────────────────────────────────────────────────

def test_manifest_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    from core.spark_state import SessionDB
    db = SessionDB()
    db.set_manifest("myproject", {"pinned_files": ["README.md"], "notes": "important"})
    data = db.get_manifest("myproject")
    assert data["pinned_files"] == ["README.md"]
    db.close()


def test_manifest_isolation_across_workspaces(tmp_path, monkeypatch):
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    from core.spark_state import SessionDB
    db = SessionDB()
    db.set_manifest("proj-a", {"foo": 1})
    assert db.get_manifest("proj-b") == {}
    db.close()


def test_manifest_empty_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    from core.spark_state import SessionDB
    db = SessionDB()
    assert db.get_manifest("unknown") == {}
    db.close()


# ── REST endpoint tests ───────────────────────────────────────────────────────

def test_brief_api_404_on_unknown_session(client):
    r = client.get("/api/sessions/does-not-exist-xyz/brief")
    assert r.status_code == 404


def test_manifest_api_returns_empty_for_unknown(client):
    r = client.get("/api/workspace/projects/unknown-slug/manifest")
    assert r.status_code == 200
    assert r.json()["data"] == {}
