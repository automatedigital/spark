"""Real SQLite regression boundaries for SP13 bounded message navigation."""
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.spark_state import SessionDB
from spark_cli.message_anchor import read_message_window
from spark_cli.message_anchor_routes import router


@pytest.fixture
def history(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    db.create_session("anchor-thread", "web")
    db.create_session("other-thread", "web")
    db._conn.executemany(
        "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
        [("anchor-thread", "user" if i % 2 == 0 else "assistant", "equal snippet" if i in (100, 5000) else f"row {i}", i) for i in range(10000)],
    )
    db._conn.commit()
    yield db
    db.close()


def test_middle_window_bounded_and_exact_equal_snippets(history):
    timings = []
    for _ in range(5):
        start = time.perf_counter()
        window = read_message_window(history, "anchor-thread", 5001, limit=10000)
        timings.append((time.perf_counter() - start) * 1000)
        assert len(window["messages"]) == 200
        assert window["anchor_id"] == 5001
        assert [m["id"] for m in window["messages"] if m["content"] == "equal snippet"] == [5001]
        assert window["has_earlier"] and window["has_newer"]
    print(f"SP13 middle 10k window milliseconds n=5: {timings}")


def test_keyset_pages_and_live_append_have_no_duplicates_or_cursor_loss(history):
    middle = read_message_window(history, "anchor-thread", 5001)
    older = read_message_window(history, "anchor-thread", 5001, before_id=middle["before_id"])
    history.append_message("anchor-thread", "assistant", "new live tail")
    newer = read_message_window(history, "anchor-thread", 5001, after_id=middle["after_id"])
    back = read_message_window(history, "anchor-thread", 5001, after_id=older["after_id"])
    ids = [[m["id"] for m in page["messages"]] for page in (older, middle, newer)]
    assert len(set(sum(ids, []))) == 150
    assert back["messages"] == middle["messages"]
    assert newer["has_newer"]
    assert middle["after_id"] == back["after_id"]


def test_wrong_thread_deleted_and_wrong_cursor_are_honest(history):
    wrong = read_message_window(history, "other-thread", 5001)
    assert wrong["anchor_id"] is None and wrong["messages"] == []
    history._conn.execute("DELETE FROM messages WHERE id=5001")
    history._conn.commit()
    missing = read_message_window(history, "anchor-thread", 5001)
    assert missing["anchor_status"] == "unavailable"
    assert missing["notice"]
    assert len(missing["messages"]) == 50
    assert all(m["content"] != "equal snippet" for m in missing["messages"])
    fallback_page = read_message_window(history, "anchor-thread", 5001, before_id=missing["before_id"])
    assert fallback_page["anchor_status"] == "unavailable"
    assert len(fallback_page["messages"]) == 50
    assert fallback_page["after_id"] < missing["before_id"]
    with pytest.raises(ValueError):
        read_message_window(history, "anchor-thread", 5002, before_id=999999)
    with pytest.raises(ValueError):
        read_message_window(history, "anchor-thread", 5002, before_id=5003, after_id=5004)


def test_compression_keeps_exact_ancestor_and_forks_separate(history):
    history._conn.execute("UPDATE sessions SET end_reason='compression' WHERE id='anchor-thread'")
    history._conn.commit()
    history.create_session("compressed-thread", "web", parent_session_id="anchor-thread")
    history.append_message("compressed-thread", "assistant", "compressed summary")
    window = read_message_window(history, "compressed-thread", 5001)
    assert window["session_id"] == "compressed-thread"
    assert window["history_session_id"] == "anchor-thread"
    assert window["anchor_id"] == 5001
    history.create_session("fork-thread", "web", parent_session_id="compressed-thread")
    assert read_message_window(history, "fork-thread", 5001)["anchor_status"] == "unavailable"


def test_profile_and_route_validation(history, monkeypatch, tmp_path):
    monkeypatch.setenv("SPARK_HOME", str(tmp_path / "another-profile"))
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        assert client.get("/api/sessions/anchor-thread/message-window/5001").status_code == 404
        assert client.get("/api/sessions/anchor-thread/message-window/not-an-id").status_code == 422
        assert client.get("/api/sessions/anchor-thread/message-window/5001?limit=201").status_code == 422
    with pytest.raises(LookupError):
        read_message_window(history, "' OR 1=1 --", 5001)


def test_route_reads_owned_anchor_and_returns_honest_compression_fallback(history, monkeypatch):
    monkeypatch.setenv("SPARK_HOME", str(history.db_path.parent))
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        result = client.get("/api/sessions/anchor-thread/message-window/5001").json()
        assert result["anchor_status"] == "found"
        assert result["anchor_id"] == 5001
        assert len(result["messages"]) == 50
        assert client.get("/api/sessions/anchor-thread/message-window/5001?before_id=999999").status_code == 409
        fallback = client.get("/api/sessions/other-thread/message-window/5001").json()
        assert fallback["anchor_status"] == "unavailable"
        assert fallback["messages"] == []


def test_timestamp_ties_use_ids_as_stable_cursors(tmp_path):
    db = SessionDB(tmp_path / "tied.db")
    try:
        db.create_session("ties", "web")
        db._conn.executemany(
            "INSERT INTO messages(session_id,role,content,timestamp) VALUES ('ties','user','same',1)",
            [() for _ in range(12)],
        )
        db._conn.commit()
        middle = read_message_window(db, "ties", 6, limit=4)
        assert [m["id"] for m in middle["messages"]] == [4, 5, 6, 7]
        next_page = read_message_window(db, "ties", 6, limit=4, after_id=7)
        assert [m["id"] for m in next_page["messages"]] == [8, 9, 10, 11]
        previous = read_message_window(db, "ties", 6, limit=4, before_id=8)
        assert previous["messages"] == middle["messages"]
    finally:
        db.close()
