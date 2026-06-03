"""SQLite-backed workflow persistence helpers.

Stored at ``get_spark_home()/workflows/executions.db``. One row per execution;
per-node results are kept as JSON so the inspector can replay input/output items.
The same database also stores registered workflow triggers.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from spark_cli.config import get_spark_home


def _db_path() -> Path:
    d = get_spark_home() / "workflows"
    d.mkdir(parents=True, exist_ok=True)
    return d / "executions.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS executions (
            id            TEXT PRIMARY KEY,
            canvas_id     TEXT,
            scope         TEXT,
            slug          TEXT,
            status        TEXT,
            error         TEXT,
            started_at    REAL,
            finished_at   REAL,
            trigger       TEXT,
            nodes_json    TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS triggers (
            id             TEXT PRIMARY KEY,
            canvas_id      TEXT NOT NULL,
            scope          TEXT,
            slug           TEXT,
            node_id        TEXT NOT NULL,
            kind           TEXT NOT NULL,
            enabled        INTEGER NOT NULL DEFAULT 1,
            secret         TEXT,
            schedule       TEXT,
            path           TEXT,
            next_run_at    REAL,
            last_run_at    REAL,
            last_file_mtime REAL,
            doc_json       TEXT NOT NULL,
            created_at     REAL,
            updated_at     REAL
        )
        """
    )
    conn.commit()
    return conn


def record_execution(
    *,
    execution_id: str,
    canvas_id: str,
    scope: str,
    slug: str | None,
    status: str,
    error: str | None,
    started_at: float,
    trigger: str,
    nodes: list[dict[str, Any]],
) -> None:
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO executions "
            "(id, canvas_id, scope, slug, status, error, started_at, finished_at, trigger, nodes_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                execution_id,
                canvas_id,
                scope,
                slug,
                status,
                error,
                started_at,
                time.time(),
                trigger,
                json.dumps(nodes),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def list_executions(
    *, canvas_id: str | None = None, scope: str | None = None, slug: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        clauses, params = [], []
        if canvas_id:
            clauses.append("canvas_id = ?")
            params.append(canvas_id)
        if scope:
            clauses.append("scope = ?")
            params.append(scope)
        if slug:
            clauses.append("slug = ?")
            params.append(slug)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(
            f"SELECT id, canvas_id, scope, slug, status, error, started_at, finished_at, trigger "
            f"FROM executions{where} ORDER BY started_at DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_execution(execution_id: str) -> dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM executions WHERE id = ?", (execution_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["nodes"] = json.loads(d.pop("nodes_json") or "[]")
        return d
    finally:
        conn.close()


def replace_triggers(
    *,
    canvas_id: str,
    scope: str,
    slug: str | None,
    triggers: list[dict[str, Any]],
) -> None:
    """Replace all registered triggers for a canvas."""
    now = time.time()
    conn = _connect()
    try:
        conn.execute(
            "DELETE FROM triggers WHERE canvas_id = ? AND scope = ? AND COALESCE(slug, '') = COALESCE(?, '')",
            (canvas_id, scope, slug),
        )
        conn.executemany(
            """
            INSERT INTO triggers
            (id, canvas_id, scope, slug, node_id, kind, enabled, secret, schedule, path,
             next_run_at, last_run_at, last_file_mtime, doc_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    t["id"],
                    canvas_id,
                    scope,
                    slug,
                    t["node_id"],
                    t["kind"],
                    1 if t.get("enabled", True) else 0,
                    t.get("secret"),
                    t.get("schedule"),
                    t.get("path"),
                    t.get("next_run_at"),
                    t.get("last_run_at"),
                    t.get("last_file_mtime"),
                    json.dumps(t["doc"]),
                    now,
                    now,
                )
                for t in triggers
            ],
        )
        conn.commit()
    finally:
        conn.close()


def list_triggers(
    *, canvas_id: str | None = None, kind: str | None = None, enabled_only: bool = False
) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        clauses: list[str] = []
        params: list[Any] = []
        if canvas_id:
            clauses.append("canvas_id = ?")
            params.append(canvas_id)
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if enabled_only:
            clauses.append("enabled = 1")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(
            "SELECT id, canvas_id, scope, slug, node_id, kind, enabled, secret, schedule, path, "
            "next_run_at, last_run_at, last_file_mtime, created_at, updated_at "
            f"FROM triggers{where} ORDER BY updated_at DESC",
            params,
        ).fetchall()
        return [_trigger_row_to_dict(r, include_doc=False) for r in rows]
    finally:
        conn.close()


def get_trigger(trigger_id: str) -> dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM triggers WHERE id = ?", (trigger_id,)).fetchone()
        return _trigger_row_to_dict(row, include_doc=True) if row else None
    finally:
        conn.close()


def find_webhook(secret: str) -> dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM triggers WHERE kind = 'webhook' AND enabled = 1 AND secret = ?",
            (secret,),
        ).fetchone()
        return _trigger_row_to_dict(row, include_doc=True) if row else None
    finally:
        conn.close()


def due_schedules(now: float) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM triggers WHERE kind = 'schedule' AND enabled = 1 "
            "AND next_run_at IS NOT NULL AND next_run_at <= ?",
            (now,),
        ).fetchall()
        return [_trigger_row_to_dict(r, include_doc=True) for r in rows]
    finally:
        conn.close()


def enabled_file_triggers() -> list[dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM triggers WHERE kind = 'filewatch' AND enabled = 1 AND path IS NOT NULL AND path != ''"
        ).fetchall()
        return [_trigger_row_to_dict(r, include_doc=True) for r in rows]
    finally:
        conn.close()


def update_trigger_state(
    trigger_id: str,
    *,
    next_run_at: float | None = None,
    last_run_at: float | None = None,
    last_file_mtime: float | None = None,
) -> None:
    conn = _connect()
    try:
        conn.execute(
            "UPDATE triggers SET next_run_at = ?, last_run_at = COALESCE(?, last_run_at), "
            "last_file_mtime = COALESCE(?, last_file_mtime), updated_at = ? WHERE id = ?",
            (next_run_at, last_run_at, last_file_mtime, time.time(), trigger_id),
        )
        conn.commit()
    finally:
        conn.close()


def _trigger_row_to_dict(row: sqlite3.Row, *, include_doc: bool) -> dict[str, Any]:
    d = dict(row)
    d["enabled"] = bool(d.get("enabled"))
    if include_doc:
        d["doc"] = json.loads(d.pop("doc_json") or "{}")
    else:
        d.pop("doc_json", None)
    return d
