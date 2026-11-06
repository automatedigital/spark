"""Read-only, bounded search navigation; no transcript/index mutations."""
from __future__ import annotations

import json
from typing import Any

from core.spark_state import SessionDB


def read_message_window(
    db: SessionDB, session_id: str, message_id: int, *, limit: int = 50,
    before_id: int | None = None, after_id: int | None = None,
) -> dict[str, Any]:
    """Validate the anchor/cursor inside the compression family, then keyset read.

    Payload materialization is bounded by 200 rows, including around a 10k-row
    anchor. Compression ancestors remain historical contexts, never live tails.
    A cursor is always a real message ID belonging to the anchor's stored session.
    """
    limit = max(2, min(limit, 200))
    if before_id is not None and after_id is not None:
        raise ValueError("Choose one history direction")
    with db._lock:
        db._conn.execute("BEGIN")
        try:
            sid = db.resolve_session_id(session_id)
            if not sid:
                raise LookupError("Session not found")
            family = db.resolve_compression_chain(sid)
            latest = family[-1]
            anchor = db._conn.execute(
                f"SELECT id, session_id, timestamp FROM messages WHERE id = ? AND {db._WEB_VISIBLE_MESSAGE_SQL}",
                (message_id,),
            ).fetchone()
            found = anchor is not None and anchor["session_id"] in family
            history_sid = anchor["session_id"] if found else latest
            cursor_id = before_id if before_id is not None else after_id
            cursor = None
            if cursor_id is not None:
                cursor = db._conn.execute(
                    "SELECT id, timestamp FROM messages WHERE id = ? AND session_id = ?",
                    (cursor_id, history_sid),
                ).fetchone()
                if cursor is None:
                    raise ValueError("History cursor is no longer available; reopen the search result")
            visible = db._WEB_VISIBLE_MESSAGE_SQL

            def select(direction: str, boundary: Any, count: int):
                op = "<" if direction == "before" else ">"
                order = "DESC" if direction == "before" else "ASC"
                condition = ""
                params: list[Any] = [history_sid]
                if boundary is not None:
                    condition = f"AND (timestamp, id) {op} (?, ?)"
                    params.extend((boundary["timestamp"], boundary["id"]))
                params.append(count)
                return db._conn.execute(
                    f"""SELECT id, role,
                        CASE WHEN role = 'tool' THEN substr(content, 1, 2001) ELSE content END AS content,
                        tool_call_id, tool_calls, tool_name, timestamp, finish_reason, reasoning,
                        reasoning_details, codex_reasoning_items
                        FROM messages WHERE session_id = ? AND {visible} {condition}
                        ORDER BY timestamp {order}, id {order} LIMIT ?""", params,
                ).fetchall()

            if cursor is not None:
                rows = select("before" if before_id is not None else "after", cursor, limit)
            elif found:
                rows = select("before", anchor, limit // 2)
                rows += select("after", anchor, limit - len(rows) - 1)
                # The exact anchor is selected with the same bounded projection.
                rows += db._conn.execute(
                    """SELECT id, role,
                    CASE WHEN role = 'tool' THEN substr(content, 1, 2001) ELSE content END AS content,
                    tool_call_id, tool_calls, tool_name, timestamp,
                    finish_reason, reasoning, reasoning_details, codex_reasoning_items
                    FROM messages WHERE id = ?""", (message_id,),
                ).fetchall()
            else:
                rows = select("before", None, limit)
            rows = sorted(rows, key=lambda row: (row["timestamp"], row["id"]))
            messages = []
            for row in rows:
                message = dict(row)
                if message.get("tool_calls"):
                    try:
                        message["tool_calls"] = json.loads(message["tool_calls"])
                    except (ValueError, TypeError):
                        message["tool_calls"] = []
                messages.append(message)
            earlier = bool(rows and select("before", rows[0], 1))
            newer = bool(rows and select("after", rows[-1], 1))
            return {
                "session_id": latest, "history_session_id": history_sid, "lineage": family,
                "anchor_id": message_id if found else None,
                "anchor_status": "found" if found else "unavailable",
                "notice": None if found else "This message is no longer available in this thread. The latest saved context is shown.",
                "messages": messages, "has_earlier": earlier, "has_newer": newer,
                "before_id": rows[0]["id"] if rows else None,
                "after_id": rows[-1]["id"] if rows else None,
            }
        finally:
            db._conn.rollback()
