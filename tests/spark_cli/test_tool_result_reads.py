"""Real SQLite contract for SP07's isolated read adapter."""
import hashlib
import sqlite3

import pytest
from fastapi import HTTPException

from core.spark_state import SessionDB
from spark_cli.tool_result_reads import PAGE_BYTES, read_result


@pytest.fixture
def stored(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    db.create_session("owner", source="web", model="test")
    db.create_session("other", source="web", model="test")
    text = ("a" * 65533 + "🙂漢é\n") * 160
    db.append_message("owner", "tool", content=text, tool_call_id="call", tool_name="read")
    db.close()
    return tmp_path, text


def test_ten_mb_unicode_pages_exact(stored):
    home, text = stored
    expected = text.encode()
    assert len(expected) > 10_000_000
    page = read_result(home, "owner", "call")
    pieces = []
    while True:
        raw = page["content"].encode()
        assert len(raw) <= PAGE_BYTES
        assert page["offset"] == sum(map(len, pieces))
        assert page["total_bytes"] == len(expected)
        assert page["sha256"] == hashlib.sha256(expected).hexdigest()
        pieces.append(raw)
        if page["next_offset"] is None:
            break
        page = read_result(home, "owner", "call", page["next_offset"], page["revision"])
    assert b"".join(pieces) == expected
    with sqlite3.connect(home / "state.db") as conn:
        assert conn.execute("SELECT content FROM messages").fetchone()[0] == text


def test_revision_ownership_profile_and_offsets(stored, tmp_path):
    home, _ = stored
    page = read_result(home, "owner", "call")
    for sid, call in [("other", "call"), ("owner", "missing"), ("missing", "call")]:
        with pytest.raises(HTTPException) as error:
            read_result(home, sid, call)
        assert error.value.status_code == 404
    with pytest.raises(HTTPException):
        read_result(tmp_path / "other-profile", "owner", "call")
    with pytest.raises(HTTPException) as error:
        read_result(home, "owner", "call", 65534, page["revision"])
    assert error.value.status_code == 400
    with sqlite3.connect(home / "state.db") as conn:
        conn.execute("UPDATE messages SET content = replace(content, 'a', 'b')")
    with pytest.raises(HTTPException) as error:
        read_result(home, "owner", "call", page["next_offset"], page["revision"])
    assert error.value.status_code == 409


def test_bounded_projection_and_no_whole_thread(stored, monkeypatch):
    home, _ = stored
    monkeypatch.setattr(SessionDB, "get_messages", lambda *_: pytest.fail("whole thread read"))
    page = read_result(home, "owner", "call")
    assert len(page["content"].encode()) <= PAGE_BYTES


def test_routes_download_exact_and_worker_owned(stored, monkeypatch):
    import asyncio
    import threading

    from starlette.testclient import TestClient

    import spark_cli.tool_result_reads as reads
    import spark_cli.web_server as server

    home, text = stored
    monkeypatch.setenv("SPARK_HOME", str(home))
    owner = threading.get_ident()
    original = reads.read_result
    workers = []

    def traced(*args, **kwargs):
        workers.append(threading.get_ident())
        return original(*args, **kwargs)

    monkeypatch.setattr(reads, "read_result", traced)
    # Invoke route directly too: it must dispatch away from the calling loop.
    page = asyncio.run(server.get_session_tool_result("owner", "call", True))
    assert workers and owner not in workers
    client = TestClient(server.app)
    path = "/api/sessions/owner/tool-results/call"
    response = client.get(path + "/download", params={"revision": page["revision"]})
    assert response.status_code == 200
    assert response.content == text.encode()
    assert response.headers["x-content-sha256"] == hashlib.sha256(response.content).hexdigest()
    assert client.get(path + "/download", params={"revision": "stale"}).status_code == 409
    assert client.get("/api/sessions/other/tool-results/call/download", params={"revision": page["revision"]}).status_code == 404


def test_empty_and_compression(stored):
    home, _ = stored
    db = SessionDB(home / "state.db")
    db.create_session("compressed", source="web", model="test", parent_session_id="owner")
    db.append_message("compressed", "tool", content="", tool_call_id="empty")
    db.close()
    with sqlite3.connect(home / "state.db") as conn:
        conn.execute("UPDATE sessions SET end_reason='compression' WHERE id='owner'")
    page = read_result(home, "owner", "empty")
    assert page["session_id"] == "compressed"
    assert page["content"] == "" and page["next_offset"] is None


def test_download_revalidates_between_chunks(stored):
    import asyncio

    from spark_cli.web_server import download_session_tool_result

    home, _ = stored
    import os
    previous = os.environ.get("SPARK_HOME")
    os.environ["SPARK_HOME"] = str(home)

    async def exercise():
        page = read_result(home, "owner", "call")
        response = await download_session_tool_result("owner", "call", page["revision"])
        iterator = response.body_iterator
        assert len(await anext(iterator)) <= PAGE_BYTES
        with sqlite3.connect(home / "state.db") as conn:
            conn.execute("UPDATE messages SET content='changed'")
        with pytest.raises(HTTPException) as error:
            await anext(iterator)
        assert error.value.status_code == 409
        await iterator.aclose()

    try:
        asyncio.run(exercise())
    finally:
        if previous is None:
            os.environ.pop("SPARK_HOME", None)
        else:
            os.environ["SPARK_HOME"] = previous


def test_remote_download_requires_existing_dashboard_auth(stored, monkeypatch):
    from starlette.testclient import TestClient

    import spark_cli.web_server as server

    home, _ = stored
    monkeypatch.setenv("SPARK_HOME", str(home))
    monkeypatch.setenv("SPARK_DASHBOARD_TOKEN", "synthetic-sp07-dashboard-token")
    page = read_result(home, "owner", "call")
    client = TestClient(server.app, client=("198.51.100.1", 10000))
    path = "/api/sessions/owner/tool-results/call/download"
    assert client.get(path, params={"revision": page["revision"]}).status_code == 401
    response = client.get(path, params={"revision": page["revision"]}, headers={"Authorization": "Bearer synthetic-sp07-dashboard-token"})
    assert response.status_code == 200
    assert hashlib.sha256(response.content).hexdigest() == page["sha256"]


def test_sql_projection_and_incremental_reads_are_bounded(stored, monkeypatch):
    home, _ = stored
    statements, sizes = [], []
    original_connect = sqlite3.connect

    class Blob:
        def __init__(self, inner):
            self.inner = inner

        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.inner.close()

        def __len__(self):
            return len(self.inner)

        def seek(self, offset):
            return self.inner.seek(offset)

        def read(self, size):
            sizes.append(size)
            assert 0 < size <= PAGE_BYTES
            return self.inner.read(size)

    class Connection(sqlite3.Connection):
        def blobopen(self, *args, **kwargs):
            return Blob(super().blobopen(*args, **kwargs))

    def connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs, factory=Connection)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect)
    read_result(home, "owner", "call")
    projections = [statement for statement in statements if "FROM messages" in statement]
    assert len(projections) == 1
    assert "SELECT id, tool_name, content IS NULL AS empty" in projections[0]
    assert sizes and max(sizes) == PAGE_BYTES
