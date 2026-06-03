"""SQLite-backed execution history for workflow runs.

Stored at ``get_spark_home()/workflows/executions.db``. One row per execution;
per-node results are kept as JSON so the inspector can replay input/output items.
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
