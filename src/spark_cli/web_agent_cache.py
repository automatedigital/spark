"""Cost policy and durable revision checks for the existing web agent LRU.

Revision triggers belong to this optional cache helper, not SessionDB's numbered
migration chain. They cover SQL writers as well as API writes. No connection or
full durable transcript is retained by this module.
"""

from __future__ import annotations

import hashlib
import sys
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HistoryRevision:
    scope: tuple[str, str, str]
    revision: int
    destructive: int
    count: int
    context: tuple[Any, ...]


def ensure_history_revisions(db: Any) -> None:
    with db._lock:
        ready = db._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'web_cache_history_identity'"
        ).fetchone()
    if ready:
        return

    def install(conn):
        conn.execute("""CREATE TABLE IF NOT EXISTS web_cache_history_revisions (
            session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
            revision INTEGER NOT NULL, destructive INTEGER NOT NULL DEFAULT 0,
            generation TEXT NOT NULL DEFAULT (lower(hex(randomblob(16))))
        )""")
        for operation, reference in (
            ("INSERT", "NEW"), ("UPDATE", "OLD"), ("DELETE", "OLD"),
        ):
            # UPDATE invalidates both owners if a SQL writer moves a message.
            owners = [reference] + (["NEW"] if operation == "UPDATE" else [])
            insert_older = "EXISTS(SELECT 1 FROM messages WHERE session_id = NEW.session_id AND timestamp > NEW.timestamp)"
            initial_destructive = f"CASE WHEN {insert_older} THEN 1 ELSE 0 END" if operation == "INSERT" else "1"
            next_destructive = f"CASE WHEN {insert_older} THEN revision + 1 ELSE destructive END" if operation == "INSERT" else "revision + 1"
            body = " ".join(
                f"""INSERT INTO web_cache_history_revisions(session_id, revision, destructive)
                SELECT {owner}.session_id, 1, {initial_destructive}
                WHERE EXISTS(SELECT 1 FROM sessions WHERE id = {owner}.session_id)
                {"AND NEW.session_id != OLD.session_id" if operation == "UPDATE" and owner == "NEW" else ""}
                ON CONFLICT(session_id) DO UPDATE SET
                    revision = revision + 1,
                    destructive = {next_destructive};"""
                for owner in owners
            )
            conn.execute(f"""CREATE TRIGGER IF NOT EXISTS web_cache_messages_{operation.lower()}
                AFTER {operation} ON messages BEGIN {body} END""")
        conn.execute("""INSERT OR IGNORE INTO web_cache_history_revisions(session_id, revision)
            SELECT id, 0 FROM sessions""")
        conn.execute("""CREATE TRIGGER IF NOT EXISTS web_cache_session_insert
            AFTER INSERT ON sessions BEGIN
                INSERT INTO web_cache_history_revisions(session_id, revision) VALUES (NEW.id, 0)
                ON CONFLICT(session_id) DO UPDATE SET revision = 0, destructive = 0,
                    generation = lower(hex(randomblob(16)));
            END""")
        conn.execute("""CREATE TRIGGER IF NOT EXISTS web_cache_session_delete
            AFTER DELETE ON sessions BEGIN
                DELETE FROM web_cache_history_revisions WHERE session_id = OLD.id;
            END""")
        # Created last, in the same transaction: its presence certifies all triggers.
        conn.execute("CREATE TABLE IF NOT EXISTS web_cache_history_identity (id TEXT NOT NULL)")
        if not conn.execute("SELECT 1 FROM web_cache_history_identity").fetchone():
            conn.execute("INSERT INTO web_cache_history_identity VALUES (?)", (uuid.uuid4().hex,))

    db._execute_write(install)


def history_revision(db: Any, session_id: str) -> HistoryRevision:
    """Call inside the caller's read transaction for a consistent prefix boundary."""
    row = db._conn.execute("""
        SELECT s.model, s.model_config, s.system_prompt, s.parent_session_id, s.end_reason,
               COALESCE(r.revision, 0), COALESCE(r.destructive, 0),
               (SELECT COUNT(*) FROM messages WHERE session_id = s.id),
               (SELECT id FROM web_cache_history_identity LIMIT 1) || ':' || r.generation
        FROM sessions s LEFT JOIN web_cache_history_revisions r ON r.session_id = s.id
        WHERE s.id = ?
    """, (session_id,)).fetchone()
    if row is None:
        raise LookupError(session_id)
    return HistoryRevision(
        (str(db.db_path.resolve()), row[8], session_id), int(row[5]), int(row[6]),
        int(row[7]), tuple(hashlib.sha256(str(value).encode()).hexdigest() for value in row[:5]),
    )


def same_history_prefix(expected: HistoryRevision, current: HistoryRevision) -> bool:
    # Accepted prompts are appended after preparation captures its boundary.
    # Appends beyond that boundary are excluded by ChatPreparation.history_count.
    return (
        expected.scope == current.scope and expected.context == current.context
        and current.revision >= expected.revision
        and current.destructive <= expected.revision
        and current.count >= expected.count
    )


def retained_context_bytes(agent: Any) -> int:
    """Conservative logical Python size; excludes clients/native allocations (not RSS).

    Shared objects in the selected context fields are counted once. Include the
    strings' maximum UTF-8 encoding cost as headroom for request serialization.
    """
    seen: set[int] = set()

    def size(value: Any) -> int:
        if id(value) in seen:
            return 0
        seen.add(id(value))
        total = sys.getsizeof(value)
        if isinstance(value, dict):
            total += sum(size(k) + size(v) for k, v in value.items())
        elif isinstance(value, (list, tuple)):
            total += sum(size(v) for v in value)
        elif isinstance(value, str):
            total += 4 * len(value)
        return total

    return sum(size(getattr(agent, field, None)) for field in (
        "_session_messages", "messages", "_cached_system_prompt", "_system_prompt",
        "system_prompt", "tools",
    ))


def has_live_children(agent: Any) -> bool:
    lock = vars(agent).get("_active_children_lock")
    if lock is not None and hasattr(lock, "__enter__"):
        with lock:
            return bool(vars(agent).get("_active_children"))
    children = vars(agent).get("_active_children")
    return isinstance(children, (list, tuple, set, dict)) and bool(children)


def durable_cache_owners(session_ids: list[str]) -> set[str]:
    """One bounded worker-owned read; durable pending decisions also pin agents."""
    if not session_ids:
        return set()
    from core.spark_state import SessionDB

    db = SessionDB()
    try:
        protected: set[str] = set()
        for offset in range(0, len(session_ids), 128):
            batch = session_ids[offset:offset + 128]
            slots = ",".join("?" for _ in batch)
            rows = db._conn.execute(f"""
                WITH RECURSIVE family(cache_id, id, depth) AS (
                    SELECT id, id, 0 FROM sessions WHERE id IN ({slots})
                    UNION ALL
                    SELECT family.cache_id, s.parent_session_id, family.depth + 1
                    FROM family JOIN sessions s ON s.id = family.id
                    JOIN sessions parent ON parent.id = s.parent_session_id
                    WHERE parent.end_reason = 'compression' AND family.depth < 64
                )
                SELECT DISTINCT family.cache_id FROM family
                JOIN web_pending_actions a ON a.session_id = family.id
                WHERE a.status = 'pending'
                UNION
                SELECT DISTINCT family.cache_id FROM family
                JOIN subagent_runs child ON child.parent_session_id = family.id
                WHERE child.status NOT IN ('completed','failed','interrupted','cancelled','uncertain')
            """, batch).fetchall()
            protected.update(row[0] for row in rows)
        return protected
    finally:
        db.close()
