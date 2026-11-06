"""Read-only, worker-owned bounded tool-result projection; no runtime writes."""
from __future__ import annotations

import hashlib
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException

PAGE_BYTES = 64 * 1024


@contextmanager
def _reader(home: Path):
    from core.spark_state import SessionDB

    path = home / "state.db"
    if not path.is_file():
        raise HTTPException(404, "Session not found")
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    # Reuse authoritative lineage resolution without running migrations or opening
    # a writable SessionDB. This facade never escapes the owning worker.
    db = SessionDB.__new__(SessionDB)
    db._conn = conn
    db._lock = threading.Lock()
    try:
        conn.execute("BEGIN")
        yield db, conn
    finally:
        conn.close()


def read_result(home: Path, session_id: str, tool_call_id: str,
                offset: int = 0, revision: str | None = None) -> dict:
    """Offsets count raw UTF-8 bytes. Each returned content ends on a codepoint."""
    if offset < 0 or (offset and not revision):
        raise HTTPException(400, "A revision is required for continuation")
    with _reader(home) as (db, conn):
        sid = db.resolve_session_id(session_id)
        if not sid:
            raise HTTPException(404, "Session not found")
        leaf = db.resolve_latest_descendant(sid)
        row = conn.execute(
            "SELECT id, tool_name, content IS NULL AS empty "
            "FROM messages WHERE session_id=? AND role='tool' AND tool_call_id=? "
            "ORDER BY timestamp, id LIMIT 1", (leaf, tool_call_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Tool result not found")
        total = 0
        raw = b""
        # Hash via bounded blob reads, never materialise the full result in
        # Python. Including profile, ownership and row identity fences aliases.
        digest = hashlib.sha256()
        digest.update(f"{home.resolve()}:{leaf}:{row['id']}:".encode())
        raw_hash = hashlib.sha256()
        if not row["empty"]:
            with conn.blobopen("messages", "content", row["id"], readonly=True) as blob:
                total = len(blob)
                while chunk := blob.read(PAGE_BYTES):
                    digest.update(chunk)
                    raw_hash.update(chunk)
                if offset <= total:
                    blob.seek(offset)
                    raw = blob.read(PAGE_BYTES)
        current = digest.hexdigest()
        if revision is not None and revision != current:
            raise HTTPException(409, "Tool result changed; reopen the result")
        if offset > total:
            raise HTTPException(400, "Invalid result offset")
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            if exc.reason != "unexpected end of data" or exc.end != len(raw):
                raise HTTPException(400, "Offset is not a UTF-8 boundary") from exc
            raw = raw[:exc.start]
            content = raw.decode("utf-8")
        end = offset + len(raw)
        return {"session_id": leaf, "tool_call_id": tool_call_id,
                "tool_name": row["tool_name"], "content": content,
                "offset": offset, "next_offset": end if end < total else None,
                "total_bytes": total, "truncated": end < total,
                "revision": current, "sha256": raw_hash.hexdigest()}
