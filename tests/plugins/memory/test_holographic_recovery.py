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


def test_provider_initialize_requires_session_id_kwarg():
    """The boot-time web_server init calls initialize(session_id=...)."""
    from plugins.memory.holographic import HolographicMemoryProvider

    d = tempfile.mkdtemp()
    provider = HolographicMemoryProvider({"db_path": os.path.join(d, "m.db")})
    # Must accept a session_id and not raise (the original bug was a bare
    # initialize() call missing the required positional arg).
    provider.initialize(session_id="__boot__")
