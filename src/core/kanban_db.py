"""
Durable Kanban board — SQLite store for multi-agent task coordination.

Storage path: ``<SPARK_HOME>/kanban.db`` (profile-scoped via get_spark_home()).

Schema inspired by Hermes-style boards: tasks, dependency links, comments,
per-attempt runs, and append-only events for dashboards and notifiers.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from core.spark_constants import get_spark_home


def _insert_row_id(cur: sqlite3.Cursor) -> int:
    """SQLite lastrowid after INSERT; narrows type for static analysis."""
    rid = cur.lastrowid
    if rid is None:
        raise RuntimeError("INSERT did not set lastrowid")
    return rid


KANBAN_STATUSES = frozenset(
    {
        "triage",
        "todo",
        "ready",
        "running",
        "user_review",
        "blocked",
        "done",
        "archived",
    }
)

RUN_OUTCOMES = frozenset(
    {
        "active",
        "completed",
        "blocked",
        "crashed",
        "timed_out",
        "spawn_failed",
        "gave_up",
        "reclaimed",
    }
)

_SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS boards (
    slug TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    description TEXT,
    icon TEXT,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    board_slug TEXT NOT NULL DEFAULT 'default'
        REFERENCES boards(slug) ON DELETE CASCADE,
    title TEXT NOT NULL,
    body TEXT,
    status TEXT NOT NULL DEFAULT 'todo',
    assignee TEXT,
    tenant TEXT,
    priority INTEGER NOT NULL DEFAULT 0,
    idempotency_key TEXT UNIQUE,
    workspace_kind TEXT NOT NULL DEFAULT 'scratch',
    workspace_path TEXT,
    skills_json TEXT,
    in_triage INTEGER NOT NULL DEFAULT 0,
    result TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    current_run_id INTEGER,
    claim_token TEXT,
    claim_expires_at REAL,
    worker_pid INTEGER,
    spawn_failures INTEGER NOT NULL DEFAULT 0,
    max_runtime_seconds INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_tasks_board_status ON tasks(board_slug, status);
CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON tasks(assignee);
CREATE INDEX IF NOT EXISTS idx_tasks_tenant ON tasks(tenant);

CREATE TABLE IF NOT EXISTS task_links (
    parent_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    child_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    PRIMARY KEY (parent_id, child_id)
);

CREATE TABLE IF NOT EXISTS task_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    author TEXT,
    body TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS task_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    profile TEXT,
    outcome TEXT NOT NULL,
    started_at REAL NOT NULL,
    ended_at REAL,
    summary TEXT,
    metadata_json TEXT,
    error TEXT
);

CREATE TABLE IF NOT EXISTS task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT REFERENCES tasks(id) ON DELETE CASCADE,
    run_id INTEGER,
    kind TEXT NOT NULL,
    payload_json TEXT,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_task_events_task ON task_events(task_id, id);
CREATE INDEX IF NOT EXISTS idx_task_events_id ON task_events(id);
"""

_lock = threading.Lock()
_initialized: dict[str, bool] = {}


def kanban_db_path() -> Path:
    return get_spark_home() / "kanban.db"


def _new_task_id() -> str:
    return f"t_{uuid.uuid4().hex[:8]}"


def _now() -> float:
    return time.time()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL)
    row = conn.execute(
        "SELECT COUNT(*) FROM boards WHERE slug = 'default'"
    ).fetchone()
    if row and row[0] == 0:
        conn.execute(
            "INSERT INTO boards (slug, display_name, description, icon, created_at) "
            "VALUES ('default', 'Default', '', '', ?)",
            (_now(),),
        )
    conn.commit()


def init_kanban_db() -> None:
    """Create DB file and schema if missing."""
    path = str(kanban_db_path())
    with _lock:
        if _initialized.get(path):
            return
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        try:
            conn.row_factory = sqlite3.Row
            _ensure_schema(conn)
        finally:
            conn.close()
        _initialized[path] = True


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    init_kanban_db()
    path = str(kanban_db_path())
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _emit_event(
    conn: sqlite3.Connection,
    *,
    task_id: str | None,
    run_id: int | None,
    kind: str,
    payload: dict | None = None,
) -> None:
    conn.execute(
        "INSERT INTO task_events (task_id, run_id, kind, payload_json, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            task_id,
            run_id,
            kind,
            json.dumps(payload or {}, ensure_ascii=False),
            _now(),
        ),
    )


def _all_parents_done(conn: sqlite3.Connection, task_id: str) -> bool:
    parents = conn.execute(
        "SELECT parent_id FROM task_links WHERE child_id = ?", (task_id,)
    ).fetchall()
    if not parents:
        return True
    for (pid,) in parents:
        st = conn.execute(
            "SELECT status FROM tasks WHERE id = ?", (pid,)
        ).fetchone()
        if not st or st["status"] not in ("done", "archived"):
            return False
    return True


def _promote_child_tasks(conn: sqlite3.Connection, parent_id: str) -> None:
    children = conn.execute(
        "SELECT child_id FROM task_links WHERE parent_id = ?", (parent_id,)
    ).fetchall()
    for (cid,) in children:
        row = conn.execute(
            "SELECT status, in_triage FROM tasks WHERE id = ?", (cid,)
        ).fetchone()
        if not row or row["in_triage"] or row["status"] != "todo":
            continue
        if _all_parents_done(conn, cid):
            conn.execute(
                "UPDATE tasks SET status = 'ready', updated_at = ? WHERE id = ?",
                (_now(), cid),
            )
            _emit_event(conn, task_id=cid, run_id=None, kind="promoted", payload={})


def create_task(
    *,
    title: str,
    board_slug: str = "default",
    body: str = "",
    assignee: str | None = None,
    tenant: str | None = None,
    priority: int = 0,
    parent_ids: Sequence[str] | None = None,
    idempotency_key: str | None = None,
    workspace_kind: str = "scratch",
    workspace_path: str | None = None,
    skills: Sequence[str] | None = None,
    in_triage: bool = False,
    max_runtime_seconds: int = 0,
) -> dict[str, Any]:
    """Insert a task. Respects idempotency_key: returns existing row if duplicate."""
    skills_json = json.dumps(list(skills or []), ensure_ascii=False)
    now = _now()

    with _connect() as conn:
        if idempotency_key:
            row = conn.execute(
                "SELECT * FROM tasks WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
            if row:
                return dict(row)

        # Ensure board exists
        b = conn.execute(
            "SELECT slug FROM boards WHERE slug = ?", (board_slug,)
        ).fetchone()
        if not b:
            conn.execute(
                "INSERT INTO boards (slug, display_name, created_at) VALUES (?, ?, ?)",
                (board_slug, board_slug, now),
            )

        status = "triage" if in_triage else "todo"

        tid = _new_task_id()
        conn.execute(
            "INSERT INTO tasks ("
            "id, board_slug, title, body, status, assignee, tenant, priority, "
            "idempotency_key, workspace_kind, workspace_path, skills_json, "
            "in_triage, created_at, updated_at, max_runtime_seconds"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                tid,
                board_slug,
                title,
                body,
                status,
                assignee,
                tenant,
                priority,
                idempotency_key,
                workspace_kind,
                workspace_path,
                skills_json,
                1 if in_triage else 0,
                now,
                now,
                max_runtime_seconds,
            ),
        )

        for pid in parent_ids or []:
            conn.execute(
                "INSERT OR IGNORE INTO task_links (parent_id, child_id) VALUES (?, ?)",
                (pid, tid),
            )

        _emit_event(
            conn,
            task_id=tid,
            run_id=None,
            kind="created",
            payload={
                "assignee": assignee,
                "status": status,
                "parents": list(parent_ids or []),
                "tenant": tenant,
            },
        )
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
        if not row:
            raise RuntimeError(f"kanban: task {tid!r} missing after insert")
        return dict(row)


def get_task(task_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None


def add_comment(task_id: str, body: str, author: str | None = None) -> int:
    with _connect() as conn:
        if not conn.execute("SELECT 1 FROM tasks WHERE id = ?", (task_id,)).fetchone():
            raise ValueError(f"Task not found: {task_id}")
        cur = conn.execute(
            "INSERT INTO task_comments (task_id, author, body, created_at) VALUES (?,?,?,?)",
            (task_id, author or "user", body, _now()),
        )
        cid = _insert_row_id(cur)
        _emit_event(
            conn, task_id=task_id, run_id=None, kind="comment", payload={"id": cid}
        )
        return cid


def _would_create_cycle(conn: sqlite3.Connection, parent_id: str, child_id: str) -> bool:
    """True if there is already a path child_id ->* parent_id (adding parent->child closes a loop)."""
    stack = [child_id]
    seen: set[str] = set()
    while stack:
        n = stack.pop()
        if n == parent_id:
            return True
        if n in seen:
            continue
        seen.add(n)
        for (cid,) in conn.execute(
            "SELECT child_id FROM task_links WHERE parent_id = ?", (n,)
        ):
            stack.append(cid)
    return False


def add_link(parent_id: str, child_id: str) -> None:
    if parent_id == child_id:
        raise ValueError("Cannot link task to itself")
    with _connect() as conn:
        missing = [
            tid
            for tid in (parent_id, child_id)
            if not conn.execute("SELECT 1 FROM tasks WHERE id = ?", (tid,)).fetchone()
        ]
        if missing:
            raise ValueError(f"Task not found: {', '.join(missing)}")
        if _would_create_cycle(conn, parent_id, child_id):
            raise ValueError("Dependency cycle detected")
        conn.execute(
            "INSERT OR IGNORE INTO task_links (parent_id, child_id) VALUES (?, ?)",
            (parent_id, child_id),
        )
        row = conn.execute(
            "SELECT status, in_triage FROM tasks WHERE id = ?", (child_id,)
        ).fetchone()
        if row and not row["in_triage"] and row["status"] == "todo":
            if _all_parents_done(conn, child_id):
                conn.execute(
                    "UPDATE tasks SET status = 'ready', updated_at = ? WHERE id = ?",
                    (_now(), child_id),
                )
                _emit_event(conn, task_id=child_id, run_id=None, kind="promoted", payload={})


def remove_link(parent_id: str, child_id: str) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM task_links WHERE parent_id = ? AND child_id = ?",
            (parent_id, child_id),
        )
        return cur.rowcount > 0


def patch_task(
    task_id: str,
    *,
    status: str | None = None,
    title: str | None = None,
    body: str | None = None,
    assignee: str | None = None,
    priority: int | None = None,
    tenant: str | None = None,
    result: str | None = None,
    in_triage: bool | None = None,
    workspace_path: str | None = None,
    workspace_path_set: bool = False,
) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            return None
        cur_status = row["status"]
        now = _now()
        run_id = row["current_run_id"]

        if status is not None and status not in KANBAN_STATUSES:
            raise ValueError(f"Invalid status {status}")

        new_in_triage = row["in_triage"]
        if in_triage is not None:
            new_in_triage = 1 if in_triage else 0

        new_status = status if status is not None else cur_status

        # Reclaim active run when leaving running
        if (
            cur_status == "running"
            and status is not None
            and new_status != "running"
        ):
            if run_id:
                conn.execute(
                    "UPDATE task_runs SET outcome = 'reclaimed', ended_at = ?, "
                    "error = (CASE WHEN trim(COALESCE(error, '')) != '' "
                    "THEN COALESCE(error, '') || char(10) ELSE '' END) "
                    "|| 'status changed away from running' "
                    "WHERE id = ? AND outcome = 'active'",
                    (now, run_id),
                )
            conn.execute(
                "UPDATE tasks SET current_run_id = NULL, claim_token = NULL, "
                "claim_expires_at = NULL, worker_pid = NULL WHERE id = ?",
                (task_id,),
            )

        sets = ["updated_at = ?"]
        params: list[Any] = [now]
        if title is not None:
            sets.append("title = ?")
            params.append(title)
        if body is not None:
            sets.append("body = ?")
            params.append(body)
        if assignee is not None:
            sets.append("assignee = ?")
            params.append(assignee)
        if priority is not None:
            sets.append("priority = ?")
            params.append(priority)
        if tenant is not None:
            sets.append("tenant = ?")
            params.append(tenant)
        if result is not None:
            sets.append("result = ?")
            params.append(result)
        if workspace_path_set:
            sets.append("workspace_path = ?")
            params.append(workspace_path)
        if in_triage is not None:
            sets.append("in_triage = ?")
            params.append(new_in_triage)
        if status is not None:
            sets.append("status = ?")
            params.append(new_status)

        params.append(task_id)
        conn.execute(
            f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", params
        )

        if status is not None and cur_status != new_status:
            _emit_event(
                conn,
                task_id=task_id,
                run_id=run_id,
                kind="status",
                payload={"from": cur_status, "to": new_status},
            )
            if new_status == "done":
                _promote_child_tasks(conn, task_id)

        refreshed = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(refreshed) if refreshed else None


def delete_task(task_id: str) -> bool:
    with _connect() as conn:
        row = conn.execute("SELECT id, title, status FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            return False
        _emit_event(
            conn,
            task_id=None,
            run_id=None,
            kind="deleted",
            payload={"task_id": task_id, "title": row["title"], "status": row["status"]},
        )
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        return True


def complete_task(
    task_id: str,
    *,
    summary: str = "",
    metadata: dict | None = None,
    result: str = "",
) -> dict[str, Any] | None:
    """Finish worker execution and move the task to user review."""
    now = _now()
    meta_json = json.dumps(metadata or {}, ensure_ascii=False)
    with _connect() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            return None
        run_id = row["current_run_id"]
        if run_id:
            conn.execute(
                "UPDATE task_runs SET outcome = 'completed', ended_at = ?, "
                "summary = ?, metadata_json = ? WHERE id = ?",
                (now, summary or result, meta_json, run_id),
            )
        else:
            cur = conn.execute(
                "INSERT INTO task_runs (task_id, profile, outcome, started_at, ended_at, "
                "summary, metadata_json) VALUES (?, ?, 'completed', ?, ?, ?, ?)",
                (
                    task_id,
                    row["assignee"] or "",
                    now,
                    now,
                    summary or result,
                    meta_json,
                ),
            )
            run_id = _insert_row_id(cur)

        conn.execute(
            "UPDATE tasks SET status = 'user_review', current_run_id = NULL, claim_token = NULL, "
            "claim_expires_at = NULL, worker_pid = NULL, result = ?, updated_at = ? WHERE id = ?",
            (result or summary[:500], now, task_id),
        )
        _emit_event(
            conn,
            task_id=task_id,
            run_id=run_id,
            kind="completed",
            payload={"summary": (summary or result)[:400], "status": "user_review"},
        )
        refreshed = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(refreshed) if refreshed else None


def mark_task_done(
    task_id: str,
    *,
    summary: str = "",
    result: str = "",
) -> dict[str, Any] | None:
    """Mark a reviewed task complete."""
    now = _now()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            return None
        run_id = row["current_run_id"]
        if run_id:
            conn.execute(
                "UPDATE task_runs SET outcome = 'reclaimed', ended_at = ?, "
                "error = (CASE WHEN trim(COALESCE(error, '')) != '' "
                "THEN COALESCE(error, '') || char(10) ELSE '' END) "
                "|| 'marked complete by user' "
                "WHERE id = ? AND outcome = 'active'",
                (now, run_id),
            )
        conn.execute(
            "UPDATE tasks SET status = 'done', current_run_id = NULL, claim_token = NULL, "
            "claim_expires_at = NULL, worker_pid = NULL, result = COALESCE(NULLIF(?, ''), result), "
            "updated_at = ? WHERE id = ?",
            (result or summary[:500], now, task_id),
        )
        _emit_event(
            conn,
            task_id=task_id,
            run_id=run_id,
            kind="status",
            payload={"from": row["status"], "to": "done"},
        )
        if summary:
            cid = conn.execute(
                "INSERT INTO task_comments (task_id, author, body, created_at) VALUES (?,?,?,?)",
                (task_id, "user", summary, now),
            )
            _emit_event(
                conn,
                task_id=task_id,
                run_id=None,
                kind="comment",
                payload={"id": _insert_row_id(cid)},
            )
        _promote_child_tasks(conn, task_id)
        refreshed = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(refreshed) if refreshed else None


def block_task(task_id: str, reason: str) -> dict[str, Any] | None:
    now = _now()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            return None
        run_id = row["current_run_id"]
        if run_id:
            conn.execute(
                "UPDATE task_runs SET outcome = 'blocked', ended_at = ?, error = ? "
                "WHERE id = ? AND outcome = 'active'",
                (now, reason, run_id),
            )
        else:
            cur = conn.execute(
                "INSERT INTO task_runs (task_id, profile, outcome, started_at, ended_at, "
                "summary, error) VALUES (?, ?, 'blocked', ?, ?, ?, ?)",
                (task_id, row["assignee"] or "", now, now, reason[:2000], reason),
            )
            run_id = _insert_row_id(cur)

        conn.execute(
            "UPDATE tasks SET status = 'blocked', current_run_id = NULL, claim_token = NULL, "
            "claim_expires_at = NULL, worker_pid = NULL, updated_at = ? WHERE id = ?",
            (now, task_id),
        )
        _emit_event(
            conn, task_id=task_id, run_id=run_id, kind="blocked", payload={"reason": reason}
        )
        refreshed = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(refreshed) if refreshed else None


def unblock_task(task_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row or row["status"] != "blocked":
            return None
        new_status = "ready" if _all_parents_done(conn, task_id) else "todo"
        now = _now()
        conn.execute(
            "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, now, task_id),
        )
        _emit_event(conn, task_id=task_id, run_id=None, kind="unblocked", payload={})
        refreshed = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(refreshed) if refreshed else None


def get_board(
    *,
    board_slug: str = "default",
    tenant: str | None = None,
    assignee: str | None = None,
    include_archived: bool = False,
    search: str | None = None,
) -> dict[str, Any]:
    """Return tasks grouped by status + filter metadata."""
    with _connect() as conn:
        q = "SELECT * FROM tasks WHERE board_slug = ?"
        params: list[Any] = [board_slug]
        if not include_archived:
            q += " AND status != 'archived'"
        if tenant:
            q += " AND tenant = ?"
            params.append(tenant)
        if assignee:
            q += " AND assignee = ?"
            params.append(assignee)
        if search:
            q += " AND (title LIKE ? OR body LIKE ? OR id LIKE ?)"
            pat = f"%{search}%"
            params.extend([pat, pat, pat])

        q += " ORDER BY priority DESC, updated_at DESC, created_at ASC"
        rows = conn.execute(q, params).fetchall()
        by_status: dict[str, list[dict[str, Any]]] = {s: [] for s in sorted(KANBAN_STATUSES)}
        assignees = set()
        tenants = set()
        for r in rows:
            d = dict(r)
            st = d["status"]
            if st in by_status:
                by_status[st].append(d)
            if d.get("assignee"):
                assignees.add(d["assignee"])
            if d.get("tenant"):
                tenants.add(d["tenant"])

        boards = [dict(x) for x in conn.execute("SELECT * FROM boards").fetchall()]
        return {
            "board_slug": board_slug,
            "columns": by_status,
            "assignees": sorted(assignees),
            "tenants": sorted(tenants),
            "boards": boards,
        }


def get_task_detail(task_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            return None
        task = dict(row)
        parents = [
            r["parent_id"]
            for r in conn.execute(
                "SELECT parent_id FROM task_links WHERE child_id = ?", (task_id,)
            )
        ]
        children = [
            r["child_id"]
            for r in conn.execute(
                "SELECT child_id FROM task_links WHERE parent_id = ?", (task_id,)
            )
        ]
        comments = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM task_comments WHERE task_id = ? ORDER BY id ASC",
                (task_id,),
            )
        ]
        events = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM task_events WHERE task_id = ? ORDER BY id DESC LIMIT 80",
                (task_id,),
            )
        ]
        runs = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM task_runs WHERE task_id = ? ORDER BY id ASC",
                (task_id,),
            )
        ]
        task["parents"] = parents
        task["children"] = children
        task["comments"] = comments
        task["events"] = events
        task["runs"] = runs
        task["worker_context"] = build_worker_context(conn, task_id)
        return task


def build_worker_context(
    conn: sqlite3.Connection,
    task_id: str,
) -> str:
    """Human-readable context block for spawned workers."""
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        return ""
    lines = [
        f"Task {row['id']}: {row['title']}",
        f"Status: {row['status']}",
        "",
        "Description:",
        row["body"] or "(empty)",
        "",
    ]
    for r in conn.execute(
        "SELECT * FROM task_runs WHERE task_id = ? ORDER BY id DESC LIMIT 5",
        (task_id,),
    ):
        lines.append(
            f"Prior attempt #{r['id']}: {r['outcome']} — {r['summary'] or r['error'] or ''}"
        )
    for pid in [
        r["parent_id"]
        for r in conn.execute(
            "SELECT parent_id FROM task_links WHERE child_id = ?", (task_id,)
        )
    ]:
        pr = conn.execute(
            "SELECT id, title FROM tasks WHERE id = ?", (pid,)
        ).fetchone()
        if not pr:
            continue
        lr = conn.execute(
            "SELECT summary, metadata_json FROM task_runs WHERE task_id = ? AND outcome = 'completed' "
            "ORDER BY id DESC LIMIT 1",
            (pid,),
        ).fetchone()
        if lr:
            lines.append(f"Parent {pr['id']} ({pr['title']}): {lr['summary']}")
            if lr["metadata_json"]:
                lines.append(f"  metadata: {lr['metadata_json']}")
    for c in conn.execute(
        "SELECT author, body, created_at FROM task_comments WHERE task_id = ? ORDER BY id ASC",
        (task_id,),
    ):
        lines.append(f"Comment ({c['author']}): {c['body']}")
    return "\n".join(lines)


def append_events_since(since_id: int = 0, limit: int = 200) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM task_events WHERE id > ? ORDER BY id ASC LIMIT ?",
            (since_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def claim_ready_task(
    task_id: str,
    *,
    profile: str,
    claim_ttl_seconds: int,
) -> tuple[str, int] | None:
    """Atomically claim a ready task. Returns (claim_token, run_id) or None."""
    token = uuid.uuid4().hex
    now = _now()
    expires = now + claim_ttl_seconds
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE tasks SET status = 'running', claim_token = ?, claim_expires_at = ?, "
            "updated_at = ? WHERE id = ? AND status = 'ready'",
            (token, expires, now, task_id),
        )
        if cur.rowcount != 1:
            return None
        cur2 = conn.execute(
            "INSERT INTO task_runs (task_id, profile, outcome, started_at) VALUES (?,?,?,?)",
            (task_id, profile, "active", now),
        )
        rid = _insert_row_id(cur2)
        conn.execute(
            "UPDATE tasks SET current_run_id = ?, worker_pid = NULL, updated_at = ? WHERE id = ?",
            (rid, now, task_id),
        )
        _emit_event(
            conn,
            task_id=task_id,
            run_id=rid,
            kind="claimed",
            payload={"expires": expires, "run_id": rid},
        )
        return token, rid


def set_worker_pid(task_id: str, pid: int) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE tasks SET worker_pid = ?, updated_at = ? WHERE id = ?",
            (pid, _now(), task_id),
        )
        _emit_event(conn, task_id=task_id, run_id=None, kind="spawned", payload={"pid": pid})


def record_spawn_failure(task_id: str, error: str, failure_limit: int) -> str:
    """Increment spawn failures; may block task with gave_up. Returns outcome tag."""
    now = _now()
    with _connect() as conn:
        row = conn.execute(
            "SELECT spawn_failures, assignee FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not row:
            return "missing"
        n = int(row["spawn_failures"] or 0) + 1
        conn.execute(
            "UPDATE tasks SET spawn_failures = ?, status = 'ready', current_run_id = NULL, "
            "claim_token = NULL, claim_expires_at = NULL, worker_pid = NULL, updated_at = ? "
            "WHERE id = ?",
            (n, now, task_id),
        )
        _emit_event(
            conn,
            task_id=task_id,
            run_id=None,
            kind="spawn_failed",
            payload={"error": error[:2000], "failures": n},
        )
        if n >= failure_limit:
            conn.execute(
                "UPDATE tasks SET status = 'blocked', updated_at = ? WHERE id = ?",
                (now, task_id),
            )
            _emit_event(
                conn,
                task_id=task_id,
                run_id=None,
                kind="gave_up",
                payload={"failures": n, "error": error[:2000]},
            )
            return "gave_up"
        return "retry"


def heartbeat(task_id: str, note: str = "") -> None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT current_run_id FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        rid = row["current_run_id"] if row else None
        _emit_event(conn, task_id=task_id, run_id=rid, kind="heartbeat", payload={"note": note})


def reclaim_stale_running(
    *,
    claim_ttl_seconds: int,
    check_pid: bool = True,
) -> list[str]:
    """Return list of task ids reclaimed (ready)."""
    import os as _os

    now = _now()
    reclaimed: list[str] = []
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, current_run_id, claim_expires_at, worker_pid FROM tasks WHERE status = 'running'"
        ).fetchall()

        for r in rows:
            tid = r["id"]
            run_id = r["current_run_id"]
            claim_at = r["claim_expires_at"]
            expired = claim_at is not None and float(claim_at) < now

            dead_pid = False
            pid_alive = False
            if r["worker_pid"]:
                if check_pid:
                    try:
                        _os.kill(int(r["worker_pid"]), 0)
                        pid_alive = True
                    except OSError:
                        dead_pid = True
                else:
                    pid_alive = True

            missing_claim_ttl = claim_at is None
            stale_no_claim = missing_claim_ttl and not pid_alive
            if expired or dead_pid or stale_no_claim:
                if dead_pid:
                    run_outcome, run_error = "crashed", "pid dead"
                elif expired:
                    run_outcome, run_error = "reclaimed", "claim expired"
                else:
                    run_outcome, run_error = "reclaimed", "missing claim TTL (no live worker)"
                if run_id:
                    conn.execute(
                        "UPDATE task_runs SET outcome = ?, ended_at = ?, error = ? "
                        "WHERE id = ? AND outcome = 'active'",
                        (
                            run_outcome,
                            now,
                            run_error,
                            run_id,
                        ),
                    )
                conn.execute(
                    "UPDATE tasks SET status = 'ready', current_run_id = NULL, "
                    "claim_token = NULL, claim_expires_at = NULL, worker_pid = NULL, "
                    "updated_at = ? WHERE id = ?",
                    (now, tid),
                )
                _emit_event(
                    conn,
                    task_id=tid,
                    run_id=run_id,
                    kind="reclaimed",
                    payload={"stale": True},
                )
                reclaimed.append(tid)
    return reclaimed


def list_ready_for_dispatch(board_slug: str = "default") -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE board_slug = ? AND status = 'ready' AND assignee IS NOT NULL "
            "ORDER BY priority DESC, created_at ASC",
            (board_slug,),
        ).fetchall()
        return [dict(r) for r in rows]


def preview_ready_for_dispatch(
    *,
    board_slug: str = "default",
    max_tasks: int = 3,
) -> dict[str, Any]:
    """Return dispatchable ready tasks plus assignees skipped by concurrency limits."""
    ready = list_ready_for_dispatch(board_slug=board_slug)
    selected: list[str] = []
    blocked_by_assignee: list[str] = []
    seen_assignee: set[str] = set()
    for row in ready:
        assignee = row.get("assignee") or ""
        if not assignee:
            continue
        blocked = assignee in seen_assignee or tasks_running_for_assignee(
            assignee, board_slug=board_slug
        ) > 0
        if blocked:
            if assignee not in blocked_by_assignee:
                blocked_by_assignee.append(assignee)
            continue
        if len(selected) < max_tasks:
            selected.append(row["id"])
            seen_assignee.add(assignee)
        elif assignee not in blocked_by_assignee:
            blocked_by_assignee.append(assignee)
    return {
        "dry_run": True,
        "ready": selected,
        "blocked_by_assignee": blocked_by_assignee,
    }


def tasks_running_for_assignee(assignee: str, board_slug: str = "default") -> int:
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE board_slug = ? AND status = 'running' AND assignee = ?",
            (board_slug, assignee),
        ).fetchone()
        return int(row[0]) if row else 0


def bulk_patch(task_ids: Sequence[str], fields: dict[str, Any]) -> dict[str, Any]:
    """Apply same patch to many tasks; return per-id errors."""
    errors: dict[str, str] = {}
    for tid in task_ids:
        try:
            ft = {k: v for k, v in fields.items() if v is not None and k in (
                "status", "title", "body", "assignee", "priority", "tenant", "result", "in_triage"
            )}
            if ft:
                row = patch_task(tid, **ft)
                if row is None:
                    errors[tid] = "Task not found"
        except Exception as e:
            errors[tid] = str(e)
    return {"ok": len(errors) == 0, "errors": errors}
