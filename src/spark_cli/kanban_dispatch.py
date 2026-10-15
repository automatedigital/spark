"""Gateway Kanban dispatcher — claims ready tasks and spawns worker processes."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from core import kanban_db as kb
from core.spark_constants import get_default_spark_root, get_spark_home
from spark_cli.config import load_config, load_env

_log = logging.getLogger(__name__)


def resolve_worker_homes(profile: str, board_home: Path | None = None) -> tuple[Path, Path]:
    """Resolve existing profiles without changing the dispatcher's environment.

    Only the root home or its named profiles can own a board. Reject symlink
    escapes, traversal and missing execution homes before a runtime is loaded.
    """
    from spark_cli.profiles import resolve_profile_env, validate_profile_name

    validate_profile_name(profile)
    root = get_default_spark_root().resolve()
    board = (board_home if board_home is not None else get_spark_home()).resolve()
    if board != root:
        validate_profile_name(board.name)
        if board.parent != root / "profiles":
            raise ValueError("Board home is outside the profile root")
    execution = Path(resolve_profile_env(profile)).resolve()
    expected = root if profile == "default" else root / "profiles" / profile
    if execution != expected or not execution.is_dir() or not board.is_dir():
        raise ValueError(
            "Worker homes must be existing owned profile directories (no symlink escape)"
        )
    return board, execution


def _config() -> dict[str, Any]:
    raw = load_config().get("kanban", {})
    return raw if isinstance(raw, dict) else {}


async def run_dispatch_tick(*, max_tasks: int = 3) -> dict[str, Any]:
    """Reconcile uncertain workers, then claim and spawn bounded ready work."""
    cfg = _config()
    board = str(cfg.get("default_board", "default"))
    claim_ttl = max(1, int(cfg.get("claim_ttl_seconds", 3600)))
    fail_limit = int(cfg.get("failure_limit", 5))
    owner_home = get_spark_home().resolve()
    kb.reclaim_stale_running(claim_ttl_seconds=claim_ttl, check_pid=True)

    task_ids: list[str] = []
    for row in kb.list_ready_for_dispatch(board_slug=board):
        if len(task_ids) >= max_tasks:
            break
        assignee = row.get("assignee") or ""
        if not assignee:
            continue
        tid = row["id"]
        claim = kb.claim_ready_task(tid, profile=assignee, claim_ttl_seconds=claim_ttl)
        if not claim:
            continue
        token, run_id = claim
        fence = {"claim_token": token, "run_id": run_id}
        try:
            owner_home, execution_home = resolve_worker_homes(assignee, owner_home)
        except (ValueError, FileNotFoundError) as error:
            kb.block_task(tid, f"Invalid worker profile: {error}", **fence)
            continue

        env = os.environ.copy()
        # Profile-specific secrets from the board must not override the assignee's
        # .env. This only edits the subprocess environment, never the parent.
        for key in load_env():
            env.pop(key, None)
        env.update(
            {
                "SPARK_HOME": str(execution_home),
                "SPARK_KANBAN_BOARD_HOME": str(owner_home),
                "SPARK_KANBAN_EXECUTION_HOME": str(execution_home),
                "SPARK_KANBAN_EXECUTION_PROFILE": assignee,
                "SPARK_KANBAN_OWNER_PROFILE": "default"
                if owner_home == get_default_spark_root().resolve()
                else owner_home.name,
                "SPARK_KANBAN_TASK": tid,
                "SPARK_KANBAN_BOARD": board,
                "SPARK_KANBAN_CLAIM_TOKEN": token,
                "SPARK_KANBAN_RUN_ID": str(run_id),
                "SPARK_KANBAN_CLAIM_TTL": str(claim_ttl),
                "SPARK_KANBAN_BOARD_POLICY": json.dumps(
                    {
                        key: bool(cfg.get(key, False))
                        for key in ("notify_on_changes", "wake_creator_on_changes")
                    }
                ),
                "SPARK_QUIET": "1",
            }
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "spark_cli.kanban_worker",
                env=env,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except Exception as error:
            _log.warning("Kanban spawn failed for %s: %s", tid, error)
            kb.record_spawn_failure(tid, str(error), failure_limit=fail_limit, **fence)
            continue
        # A fast worker can finish before this returns; never turn a post-spawn
        # bookkeeping failure into a safe-to-retry spawn failure.
        try:
            kb.set_worker_pid(tid, proc.pid, **fence)
        except kb.WorkerClaimError:
            _log.info("Worker %s released its claim before PID registration", tid)
        task_ids.append(tid)
    return {"ok": True, "claimed": len(task_ids), "task_ids": task_ids}
