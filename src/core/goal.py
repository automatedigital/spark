"""
Goal — durable cross-session objectives backed by the Kanban board.

Goals are tasks on the dedicated ``"goals"`` board in the Kanban DB
(``~/.spark/kanban.db``).  This means:

- Goal state is shared between the CLI and the Spark Dashboard web UI.
- The Dashboard shows the goals board when the user sets the board slug
  to ``"goals"`` — drag a card to a new column to pause, resume, or
  complete a goal without touching the CLI.
- The SSE event stream powers real-time updates in both directions.

Status mapping:
  active  → Kanban ``"todo"``    (no worker assigned; agent pursues it)
  paused  → Kanban ``"blocked"``
  done    → Kanban ``"done"``    (via complete_task)
  cleared → Kanban ``"archived"``

The active goal is injected into the agent system prompt so every
conversation turn is aware of the current objective.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

GOALS_BOARD = "goals"
GOAL_WORKSPACE_KIND = "goal"

# Statuses that mean the goal is still being pursued
_ACTIVE_STATUSES = frozenset({"todo", "ready"})
_INACTIVE_STATUSES = frozenset({"done", "archived"})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _kb():
    """Return kanban_db module (lazy import — avoids startup cost)."""
    from core import kanban_db
    return kanban_db


def _ensure_goals_board() -> None:
    """Create the goals board row if it doesn't exist yet."""
    kb = _kb()
    kb.init_kanban_db()
    import sqlite3

    path = str(kb.kanban_db_path())
    conn = sqlite3.connect(path)
    try:
        row = conn.execute("SELECT 1 FROM boards WHERE slug = ?", (GOALS_BOARD,)).fetchone()
        if not row:
            conn.execute(
                "INSERT INTO boards (slug, display_name, description, icon, created_at) "
                "VALUES (?, 'Goals', 'Durable objectives set via /goal', '🎯', ?)",
                (GOALS_BOARD, __import__("time").time()),
            )
            conn.commit()
    finally:
        conn.close()


def _task_to_goal(task: dict[str, Any]) -> dict[str, Any]:
    """Normalize a Kanban task row to the goal dict shape consumed by callers."""
    created_ts = task.get("created_at") or 0
    try:
        set_at = datetime.fromtimestamp(float(created_ts)).isoformat(timespec="seconds")
    except (TypeError, ValueError, OSError):
        set_at = ""
    return {
        "id": task.get("id", ""),
        "text": task.get("title", ""),
        "stopping_condition": task.get("body", ""),
        "set_at": set_at,
        "paused": task.get("status") == "blocked",
        "status": task.get("status", "todo"),
    }


def _find_active_task() -> dict[str, Any] | None:
    """Return the most-recently-created non-done goal task, or None."""
    kb = _kb()
    try:
        board = kb.get_board(board_slug=GOALS_BOARD, include_archived=False)
        columns = board.get("columns", {})
        candidates: list[dict] = []
        for status, tasks in columns.items():
            if status not in _INACTIVE_STATUSES:
                candidates.extend(tasks)
        if not candidates:
            return None
        # Most recently created first
        candidates.sort(key=lambda t: t.get("created_at", 0), reverse=True)
        return candidates[0]
    except Exception as e:
        logger.debug("Could not query goals board: %s", e)
        return None


# ---------------------------------------------------------------------------
# Public API  (same shape as before — callers are unchanged)
# ---------------------------------------------------------------------------

def get_active_goal() -> dict[str, Any] | None:
    """Return the active goal dict, or None if no goal is set.

    Returns a normalized dict with keys: id, text, stopping_condition,
    set_at, paused, status.
    """
    try:
        task = _find_active_task()
        return _task_to_goal(task) if task else None
    except Exception as e:
        logger.warning("get_active_goal failed: %s", e)
        return None


def set_goal(text: str, stopping_condition: str = "") -> dict[str, Any]:
    """Create a new goal, archiving any existing active goal first.

    Returns the normalized goal dict.
    """
    try:
        _ensure_goals_board()
        kb = _kb()
        # Archive any existing active goal
        existing_task = _find_active_task()
        if existing_task:
            kb.patch_task(existing_task["id"], status="archived")

        task = kb.create_task(
            title=text.strip(),
            body=stopping_condition.strip(),
            board_slug=GOALS_BOARD,
            workspace_kind=GOAL_WORKSPACE_KIND,
            priority=10,  # goals surface above regular tasks when viewing mixed boards
        )
        return _task_to_goal(task)
    except Exception as e:
        logger.exception("set_goal failed: %s", e)
        raise


def pause_goal() -> dict[str, Any] | None:
    """Pause the active goal. Returns updated goal dict, or None."""
    try:
        task = _find_active_task()
        if task is None or task.get("status") == "blocked":
            return None
        updated = _kb().patch_task(task["id"], status="blocked")
        return _task_to_goal(updated) if updated else None
    except Exception as e:
        logger.warning("pause_goal failed: %s", e)
        return None


def resume_goal() -> dict[str, Any] | None:
    """Resume the most-recently-paused (blocked) goal. Returns updated dict."""
    try:
        kb = _kb()
        board = kb.get_board(board_slug=GOALS_BOARD, include_archived=False)
        blocked = board.get("columns", {}).get("blocked", [])
        if not blocked:
            return None
        blocked.sort(key=lambda t: t.get("created_at", 0), reverse=True)
        task = blocked[0]
        updated = kb.patch_task(task["id"], status="todo")
        return _task_to_goal(updated) if updated else None
    except Exception as e:
        logger.warning("resume_goal failed: %s", e)
        return None


def clear_goal(outcome: str = "cleared") -> dict[str, Any] | None:
    """Archive the active goal. Returns the cleared goal dict, or None."""
    try:
        task = _find_active_task()
        if task is None:
            return None
        snapshot = _task_to_goal(task)
        _kb().patch_task(task["id"], status="archived")
        return snapshot
    except Exception as e:
        logger.warning("clear_goal failed: %s", e)
        return None


def done_goal(summary: str = "") -> dict[str, Any] | None:
    """Mark the active goal as done. Returns the goal dict, or None."""
    try:
        task = _find_active_task()
        if task is None:
            return None
        snapshot = _task_to_goal(task)
        _kb().mark_task_done(task["id"], summary=summary or "Goal completed via /goal done")
        return snapshot
    except Exception as e:
        logger.warning("done_goal failed: %s", e)
        return None


def get_history(limit: int = 20) -> list[dict[str, Any]]:
    """Return recent done/archived goals, most recent first."""
    try:
        kb = _kb()
        board = kb.get_board(board_slug=GOALS_BOARD, include_archived=True)
        columns = board.get("columns", {})
        past: list[dict] = []
        for status in ("done", "archived"):
            past.extend(columns.get(status, []))
        past.sort(key=lambda t: t.get("updated_at", 0), reverse=True)
        return [_task_to_goal(t) for t in past[:limit]]
    except Exception as e:
        logger.debug("get_history failed: %s", e)
        return []


# ---------------------------------------------------------------------------
# System prompt injection
# ---------------------------------------------------------------------------

def get_goal_block() -> str:
    """Return a formatted block to inject into the system prompt, or ''."""
    try:
        goal = get_active_goal()
    except Exception:
        return ""
    if goal is None:
        return ""
    text = goal.get("text", "").strip()
    if not text:
        return ""

    paused = goal.get("paused", False)
    stopping = goal.get("stopping_condition", "").strip()
    task_id = goal.get("id", "")

    lines = ["## Active Goal"]
    if paused:
        lines.append("*(Goal is currently paused — acknowledge it but do not actively pursue it.)*")
    lines.append(f"**Objective:** {text}")
    if stopping:
        lines.append(f"**Done when:** {stopping}")
    if task_id:
        lines.append(f"**Board task:** {task_id} (goals board)")
    lines.append(
        "\nKeep this goal in mind across every reply. "
        "When the user's request is unrelated, complete it as asked and note any "
        "progress or blockers toward the goal. "
        "When work directly relates to the goal, prioritize it. "
        "Do not declare the goal complete unless the stopping condition is explicitly met."
    )
    return "\n".join(lines)
