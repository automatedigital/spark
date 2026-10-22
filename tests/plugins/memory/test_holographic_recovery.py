"""Corrupted-DB recovery for the holographic memory store.

A truncated/garbage memory_store.db (e.g. from an unclean shutdown on a VPS)
used to raise sqlite3.DatabaseError ("file is not a database") on every turn.
The store now quarantines the bad file and rebuilds an empty one.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from plugins.memory.holographic.store import MemoryStore


def test_corrupt_db_is_quarantined_and_rebuilt():
    d = tempfile.mkdtemp()
    db = os.path.join(d, "memory_store.db")
    # Write garbage so sqlite sees a non-database file.
    with open(db, "wb") as fh:
        fh.write(b"this is not a sqlite database, just junk bytes" * 10)

    # Should NOT raise — recovery kicks in.
    store = MemoryStore(db)

    # A corrupt-quarantine sidecar was created.
    corrupt = [p for p in Path(d).iterdir() if ".corrupt-" in p.name]
    assert corrupt, "expected the corrupt DB to be quarantined"

    # The rebuilt store is a usable, empty SQLite database.
    fid = store.add_fact("Joe likes coffee.", category="general")
    assert fid
    rows = store._conn.execute("SELECT content FROM facts").fetchall()
    assert any("coffee" in r[0] for r in rows)


def test_healthy_db_is_not_quarantined():
    d = tempfile.mkdtemp()
    db = os.path.join(d, "memory_store.db")
    MemoryStore(db).add_fact("first", category="general")
    # Re-open the same healthy DB — no quarantine, data preserved.
    store = MemoryStore(db)
    assert not [p for p in Path(d).iterdir() if ".corrupt-" in p.name]
    rows = store._conn.execute("SELECT content FROM facts").fetchall()
    assert any("first" in r[0] for r in rows)


def test_locked_healthy_db_preserves_facts(tmp_path, monkeypatch):
    db = tmp_path / "memory_store.db"
    with MemoryStore(db) as store:
        fact_id = store.add_fact("keep this memory")

    connect = sqlite3.connect

    def short_timeout_connect(*args, **kwargs):
        kwargs["timeout"] = 0.05
        return connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", short_timeout_connect)
    blocker = connect(db, timeout=0.05)
    try:
        # DELETE mode makes the exclusive lock block the initialization PRAGMA.
        assert blocker.execute("PRAGMA journal_mode=DELETE").fetchone()[0] == "delete"
        blocker.execute("BEGIN EXCLUSIVE")
        original = db.read_bytes()
        with pytest.raises(sqlite3.OperationalError) as raised:
            MemoryStore(db)
        assert raised.value.sqlite_errorcode == sqlite3.SQLITE_BUSY
        assert db.read_bytes() == original
        assert not list(tmp_path.glob("*.corrupt-*"))
    finally:
        blocker.rollback()
        blocker.close()

    with MemoryStore(db) as reopened:
        assert [(f["fact_id"], f["content"]) for f in reopened.list_facts()] == [
            (fact_id, "keep this memory")
        ]


@pytest.mark.parametrize("code", [
    sqlite3.SQLITE_BUSY,
    sqlite3.SQLITE_BUSY_SNAPSHOT,
    sqlite3.SQLITE_LOCKED,
    sqlite3.SQLITE_LOCKED_SHAREDCACHE,
    sqlite3.SQLITE_IOERR,
    sqlite3.SQLITE_IOERR_READ,
    sqlite3.SQLITE_READONLY,
    sqlite3.SQLITE_FULL,
    sqlite3.SQLITE_ERROR,
    None,
])
def test_non_corruption_error_preserves_database(tmp_path, monkeypatch, code):
    db = tmp_path / "memory_store.db"
    with MemoryStore(db) as store:
        store.add_fact("keep this memory")
    # Include sidecars to prove the recovery path never moves/removes them.
    for suffix in ("-wal", "-shm"):
        Path(str(db) + suffix).write_bytes(b"sidecar sentinel")
    originals = {p: p.read_bytes() for p in tmp_path.glob("memory_store.db*")}
    # A misleading message must not override the SQLite result code (or lack of one).
    error = sqlite3.OperationalError("database disk image is malformed")
    if code is not None:
        error.sqlite_errorcode = code
    connections = []

    def fail_init(self):
        connections.append(self._conn)
        raise error

    with monkeypatch.context() as patch:
        patch.setattr(MemoryStore, "_init_db", fail_init)
        with pytest.raises(sqlite3.OperationalError) as raised:
            MemoryStore(db)
    assert raised.value is error
    assert len(connections) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connections[0].execute("SELECT 1")
    assert {p: p.read_bytes() for p in tmp_path.glob("memory_store.db*")} == originals
    # Remove the synthetic sidecars before asking SQLite to reopen the real DB.
    for suffix in ("-wal", "-shm"):
        Path(str(db) + suffix).unlink()
    with MemoryStore(db) as reopened:
        assert [f["content"] for f in reopened.list_facts()] == ["keep this memory"]


@pytest.mark.parametrize("code", [sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_CORRUPT_VTAB])
def test_corruption_result_codes_trigger_recovery(tmp_path, monkeypatch, code):
    db = tmp_path / "memory_store.db"
    with MemoryStore(db) as store:
        store.add_fact("original memory")
    error = sqlite3.DatabaseError("confirmed corruption")
    error.sqlite_errorcode = code
    init_db = MemoryStore._init_db
    calls = 0

    def fail_once(self):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise error
        init_db(self)

    monkeypatch.setattr(MemoryStore, "_init_db", fail_once)
    with MemoryStore(db) as rebuilt:
        assert rebuilt.list_facts() == []
        assert rebuilt.add_fact("new memory")
    assert calls == 2
    assert list(tmp_path.glob("memory_store.db.corrupt-*"))


def test_provider_initialize_requires_session_id_kwarg():
    """The boot-time web_server init calls initialize(session_id=...)."""
    from plugins.memory.holographic import HolographicMemoryProvider

    d = tempfile.mkdtemp()
    provider = HolographicMemoryProvider({"db_path": os.path.join(d, "m.db")})
    # Must accept a session_id and not raise (the original bug was a bare
    # initialize() call missing the required positional arg).
    provider.initialize(session_id="__boot__")
