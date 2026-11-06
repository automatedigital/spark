"""Real profile SQLite palette reads and bounded public contract."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.spark_state import SessionDB
from spark_cli.palette_routes import lookup, register_palette_routes


@pytest.fixture
def history():
    db = SessionDB()
    db._conn.executemany(
        "INSERT INTO sessions (id, source, title, started_at) VALUES (?, 'web', ?, ?)",
        [(f"palette-{i:05}", f"Thread {i}", i) for i in range(10000)],
    )
    db._conn.commit()
    db.close()


def test_large_history_recent_and_title_paging(history):
    recent = lookup("recent", "", 12, 0)
    assert len(recent["items"]) == 12
    assert recent["next"] == 12
    # Oldest entry lies beyond the previous 500-row window.
    assert lookup("threads", "Thread 0", 12, 0)["items"][0]["id"] == "palette-00000"
    first = lookup("threads", "Thread", 12, 0)
    second = lookup("threads", "Thread", 12, first["next"])
    assert len(second["items"]) == 12
    assert not ({i["id"] for i in first["items"]} & {i["id"] for i in second["items"]})


def test_empty_query_never_discovers_domains(monkeypatch):
    for category in ("projects", "jobs", "skills", "threads", "messages"):
        assert lookup(category, " ", 12, 0) == {"items": [], "next": None}


def test_route_bounds():
    app = FastAPI()
    register_palette_routes(app)
    client = TestClient(app)
    for url in ("recent?limit=500", "recent?offset=-1", "recent?q=" + "a" * 201, "unknown"):
        assert client.get("/api/palette/" + url).status_code == 422


def test_profile_isolation(history, monkeypatch, tmp_path):
    monkeypatch.setenv("SPARK_HOME", str(tmp_path / "second-profile"))
    assert lookup("recent", "", 12, 0)["items"] == []
    assert lookup("threads", "Thread", 12, 0)["items"] == []


def test_literal_title_query():
    db = SessionDB()
    db.create_session(session_id="literal", source="web")
    db.set_session_title("literal", "100%_complete")
    db.create_session(session_id="other", source="web")
    db.set_session_title("other", "Other")
    db.close()
    assert [i["id"] for i in lookup("threads", "%_", 12, 0)["items"]] == ["literal"]


def test_message_search_old_thread():
    db = SessionDB()
    db.create_session("old", "web")
    db.append_message("old", "user", "needle historical content")
    db.close()
    page = lookup("messages", "need", 12, 0)
    assert page["items"][0]["destination"] == "old"
    assert "needle" in page["items"][0]["description"]


def test_project_query_does_not_count_files(monkeypatch, tmp_path):
    from spark_cli import workspace_routes

    root = tmp_path / "projects"
    root.mkdir()
    for i in range(30):
        (root / f"project-{i:02}").mkdir()
    monkeypatch.setattr(workspace_routes, "_workspace_root", lambda: root)
    from pathlib import Path

    def no_walk(*args, **kwargs):
        raise AssertionError("Palette must never recursively count project files")

    monkeypatch.setattr(Path, "rglob", no_walk)
    first = lookup("projects", "projects", 12, 0)
    second = lookup("projects", "projects", 12, first["next"])
    assert len(first["items"]) == len(second["items"]) == 12
    assert first["items"][0]["id"] == "project-00"
    assert second["items"][0]["id"] == "project-12"


def test_query_only_domain_results_are_bounded(monkeypatch):
    from cron import jobs
    from tools import skills_metadata

    monkeypatch.setattr(jobs, "list_jobs", lambda **kwargs: [{"id": str(i), "name": f"job-{i}", "prompt": "fixture"} for i in range(30)])
    monkeypatch.setattr(skills_metadata, "iter_skill_records", lambda **kwargs: [{"name": f"skill-{i}", "description": "fixture"} for i in range(30)])
    for category in ("jobs", "skills"):
        result = lookup(category, "fixture", 12, 0)
        assert len(result["items"]) == 12
        assert result["next"] == 12
        assert lookup(category, "fixture", 12, 24)["next"] is None
