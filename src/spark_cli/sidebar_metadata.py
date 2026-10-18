"""Profile-local sidebar metadata, independent of SessionDB's migration chain.

Use the production SessionDB connection/lock/write retry helper. Metadata and its
session event commit together; neither transcript nor run state is modified.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any, cast

from core.spark_state import SessionDB

DEFAULT_METADATA = {"pinned": False, "settled": False, "position": None, "revision": 0}
LIVE_STATES = {
    "created",
    "pending",
    "queued",
    "starting",
    "running",
    "working",
    "streaming",
    "waiting",
    "waiting_for_input",
    "waiting_for_approval",
    "cancel_requested",
    "stopping",
}


class MetadataConflict(Exception):
    def __init__(self, current: dict[str, Any]):
        self.current = current


class SettleBlocked(Exception):
    pass


class SidebarMetadata:
    def __init__(self, db: SessionDB):
        self.db = db
        with db._lock:
            initialized = db._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sidebar_thread_metadata'"
            ).fetchone()
        if initialized:
            return
        db._execute_write(
            lambda conn: conn.execute("""
            CREATE TABLE IF NOT EXISTS sidebar_thread_metadata (
                session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
                pinned INTEGER NOT NULL DEFAULT 0 CHECK(pinned IN (0, 1)),
                settled INTEGER NOT NULL DEFAULT 0 CHECK(settled IN (0, 1)),
                position REAL,
                revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0)
            )
        """)
        )

    @staticmethod
    def _metadata(row) -> dict[str, Any]:
        if not row:
            return dict(DEFAULT_METADATA)
        return {
            "pinned": bool(row["pinned"]),
            "settled": bool(row["settled"]),
            "position": row["position"],
            "revision": int(row["revision"]),
        }

    def snapshot(self) -> dict[str, dict[str, Any]]:
        with self.db._lock:
            rows = self.db._conn.execute("""
                SELECT s.id, m.pinned, m.settled, m.position, m.revision
                FROM sessions s LEFT JOIN sidebar_thread_metadata m ON m.session_id = s.id
            """).fetchall()
        return {
            row["id"]: self._metadata(row)
            if row["revision"] is not None
            else dict(DEFAULT_METADATA)
            for row in rows
        }

    def attention(self) -> dict[str, dict[str, Any]]:
        """Bounded queries, no per-thread polling or provider heuristics."""
        with self.db._lock:
            pending = self.db._conn.execute(
                "SELECT DISTINCT session_id FROM web_pending_actions WHERE status = 'pending'"
            ).fetchall()
            sessions = self.db._conn.execute(
                "SELECT id, parent_session_id, end_reason FROM sessions"
            ).fetchall()
            children = self.db._conn.execute(
                "SELECT parent_session_id, child_session_id, status FROM subagent_runs"
            ).fetchall()
            turns = self.db._conn.execute(
                "SELECT session_id, projection_json FROM web_turn_projections ORDER BY updated_at"
            ).fetchall()
        result = {}
        for row in turns:
            projection = json.loads(row["projection_json"])
            status = projection.get("state") or projection.get("status")
            result[row["session_id"]] = {
                "running": bool(projection.get("turn_active") or status in LIVE_STATES),
                "pending_decision": False,
                "status": status,
            }
        for row in pending:
            result.setdefault(row["session_id"], {"running": False, "status": None})[
                "pending_decision"
            ] = True
        for row in children:
            if row["parent_session_id"] and row["status"] in LIVE_STATES:
                result.setdefault(
                    row["parent_session_id"], {"pending_decision": False, "status": None}
                )["running"] = True
        # Compression aliases share attention; delegated decisions belong to the
        # visible parent too. Iterate to a fixed point for nested ownership.
        edges = [
            (row["child_session_id"], row["parent_session_id"])
            for row in children
            if row["parent_session_id"] and row["child_session_id"]
        ]
        session_map = {row["id"]: row for row in sessions}
        for row in sessions:
            parent = session_map.get(row["parent_session_id"])
            if parent and parent["end_reason"] == "compression":
                edges.extend([(row["id"], parent["id"]), (parent["id"], row["id"])])
        for _ in range(64):
            changed = False
            for source, target in edges:
                source_state = result.get(source, {})
                if not (source_state.get("pending_decision") or source_state.get("running")):
                    continue
                target_state = result.setdefault(
                    target, {"running": False, "pending_decision": False, "status": None}
                )
                for flag in ("pending_decision", "running"):
                    if source_state.get(flag) and not target_state.get(flag):
                        target_state[flag] = True
                        changed = True
            if not changed:
                break
        # Child work remains nested in its owning thread, never hydrated as an
        # unrelated top-level sidebar row.
        child_ids = {row["child_session_id"] for row in children if row["child_session_id"]}
        for _ in range(64):
            descendants = {
                row["id"]
                for row in sessions
                if row["parent_session_id"] in child_ids
                and session_map[row["parent_session_id"]]["end_reason"] == "compression"
            }
            if descendants <= child_ids:
                break
            child_ids.update(descendants)
        return {sid: state for sid, state in result.items() if sid not in child_ids}

    def patch(
        self,
        session_id: str,
        expected_revision: int,
        changes: dict[str, Any],
        *,
        family: list[str] | None = None,
        settle_guard: Callable[[str], str | None] | None = None,
    ) -> dict[str, Any]:
        family = family or [session_id]

        def write(conn):
            if not conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone():
                raise KeyError(session_id)
            current = self._metadata(
                conn.execute(
                    "SELECT * FROM sidebar_thread_metadata WHERE session_id = ?", (session_id,)
                ).fetchone()
            )
            if current["revision"] != expected_revision:
                raise MetadataConflict(current)
            if changes.get("settled") is True:
                if settle_guard and (reason := settle_guard(session_id)):
                    raise SettleBlocked(reason)
                # Include owned descendants in the same write transaction, so a
                # completed child cannot conceal its unresolved decision.
                placeholders = ",".join("?" for _ in family)
                owned = [
                    row[0]
                    for row in conn.execute(
                        f"""WITH RECURSIVE owned(id) AS (
                        SELECT id FROM sessions WHERE id IN ({placeholders})
                        UNION SELECT r.child_session_id FROM subagent_runs r JOIN owned o
                        ON r.parent_session_id = o.id WHERE r.child_session_id IS NOT NULL
                        UNION SELECT s.id FROM sessions s JOIN owned o ON s.parent_session_id = o.id
                        JOIN sessions parent ON parent.id = o.id WHERE parent.end_reason = 'compression'
                    ) SELECT id FROM owned""",
                        family,
                    )
                ]
                placeholders = ",".join("?" for _ in owned)
                if conn.execute(
                    f"SELECT 1 FROM web_pending_actions WHERE session_id IN ({placeholders}) AND status = 'pending' LIMIT 1",
                    owned,
                ).fetchone():
                    raise SettleBlocked("Resolve the pending decision before settling this thread")
                for row in conn.execute(
                    f"SELECT projection_json FROM web_turn_projections WHERE session_id IN ({placeholders})",
                    owned,
                ):
                    projection = json.loads(row["projection_json"])
                    if (
                        projection.get("turn_active")
                        or (projection.get("state") or projection.get("status")) in LIVE_STATES
                    ):
                        raise SettleBlocked(
                            "Wait for live work to finish before settling this thread"
                        )
                if conn.execute(
                    f"SELECT 1 FROM subagent_runs WHERE parent_session_id IN ({placeholders}) AND status IN ('created', 'pending', 'queued', 'starting', 'running', 'working', 'streaming', 'waiting', 'waiting_for_input', 'waiting_for_approval', 'cancel_requested', 'stopping') LIMIT 1",
                    owned,
                ).fetchone():
                    raise SettleBlocked(
                        "Wait for delegated work to finish before settling this thread"
                    )
            updated = {**current, **changes, "revision": current["revision"] + 1}
            conn.execute(
                """
                INSERT INTO sidebar_thread_metadata(session_id, pinned, settled, position, revision)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET pinned=excluded.pinned,
                    settled=excluded.settled, position=excluded.position, revision=excluded.revision
            """,
                (
                    session_id,
                    updated["pinned"],
                    updated["settled"],
                    updated["position"],
                    updated["revision"],
                ),
            )
            event, _ = self.db._append_session_event_row(
                conn,
                session_id,
                "sidebar.metadata_changed",
                updated,
                f"sidebar:{session_id}:{updated['revision']}",
                time.time(),
            )
            return updated, event

        updated, event = self.db._execute_write(write)
        self.db._publish_committed_events([event])
        return cast("dict[str, Any]", updated)
