"""Gateway Kanban dispatcher — claims ready tasks and spawns worker processes."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Any, Dict, List

from core import kanban_db as kb
from spark_cli.config import load_config

_log = logging.getLogger(__name__)


def _config() -> Dict[str, Any]:
    raw = load_config().get("kanban", {})
    return raw if isinstance(raw, dict) else {}


async def run_dispatch_tick(*, max_tasks: int = 3) -> int:
    """Reclaim stale work, then claim & spawn up to ``max_tasks`` workers."""
    cfg = _config()
    board = str(cfg.get("default_board", "default"))
    claim_ttl = int(cfg.get("claim_ttl_seconds", 3600))
    fail_limit = int(cfg.get("failure_limit", 5))

    kb.reclaim_stale_running(claim_ttl_seconds=claim_ttl, check_pid=True)

    claimed = 0
    ready = kb.list_ready_for_dispatch(board_slug=board)
    seen_assignee: set[str] = set()

    for row in ready:
        if claimed >= max_tasks:
            break
        assignee = row.get("assignee") or ""
        if not assignee:
            continue
        if assignee in seen_assignee:
            continue
        if kb.tasks_running_for_assignee(assignee, board_slug=board) > 0:
            continue

        tid = row["id"]
        claim = kb.claim_ready_task(tid, profile=assignee, claim_ttl_seconds=claim_ttl)
        if not claim:
            continue
        _, _run_id = claim
        env = os.environ.copy()
        env["SPARK_KANBAN_TASK"] = tid
        env["SPARK_KANBAN_BOARD"] = board
        env["SPARK_QUIET"] = "1"

        cmd = [sys.executable, "-m", "spark_cli.kanban_worker"]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                env=env,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            kb.set_worker_pid(tid, proc.pid)
            seen_assignee.add(assignee)
            claimed += 1
        except Exception as e:
            _log.warning("Kanban spawn failed for %s: %s", tid, e)
            kb.record_spawn_failure(tid, str(e), failure_limit=fail_limit)

    return claimed
