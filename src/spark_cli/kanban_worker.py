#!/usr/bin/env python3
"""One-shot owned Kanban attempt, with separate board and execution homes."""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _agent_runtime_kwargs(runtime: dict) -> dict:
    kwargs = {
        key: runtime[key]
        for key in ("provider", "api_key", "base_url", "api_mode", "credential_pool")
        if runtime.get(key) is not None
    }
    if runtime.get("command") is not None:
        kwargs["acp_command"] = runtime["command"]
    if runtime.get("args") is not None:
        kwargs["acp_args"] = runtime["args"]
    return kwargs


def main() -> int:
    from core import kanban_db as kb
    from spark_cli.kanban_dispatch import resolve_worker_homes

    task_id = os.getenv("SPARK_KANBAN_TASK", "").strip()
    token = os.getenv("SPARK_KANBAN_CLAIM_TOKEN", "").strip()
    try:
        run_id = int(os.getenv("SPARK_KANBAN_RUN_ID", "0"))
        ttl = max(1, int(os.environ["SPARK_KANBAN_CLAIM_TTL"]))
        profile = os.environ["SPARK_KANBAN_EXECUTION_PROFILE"]
        raw_board = Path(os.environ["SPARK_KANBAN_BOARD_HOME"])
        raw_execution = Path(os.environ["SPARK_KANBAN_EXECUTION_HOME"])
        if (
            not task_id
            or not token
            or run_id <= 0
            or not raw_board.is_absolute()
            or not raw_execution.is_absolute()
        ):
            raise ValueError("Explicit worker task, claim, attempt and absolute homes are required")
        board, execution = resolve_worker_homes(profile, raw_board)
        board_db = board / "kanban.db"
        if (
            execution != raw_execution.resolve()
            or not board_db.is_file()
            or board_db.resolve().parent != board
        ):
            raise ValueError("Worker execution home or board ownership mismatch")
    except (ValueError, KeyError, FileNotFoundError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 2

    # This process belongs to one attempt. Select the assigned home BEFORE
    # importing runtime/config/state modules; the board remains explicitly routed.
    os.environ["SPARK_HOME"] = str(execution)
    os.environ["SPARK_KANBAN_BOARD_HOME"] = str(board)
    from spark_cli.config import load_config, load_env

    for key, value in load_env().items():
        if key != "SPARK_HOME" and not key.startswith("SPARK_KANBAN_"):
            os.environ[key] = value
    # Profile .env cannot change the owned dispatch identity or state paths.
    os.environ.update(
        {
            "SPARK_HOME": str(execution),
            "SPARK_KANBAN_BOARD_HOME": str(board),
            "SPARK_KANBAN_TASK": task_id,
            "SPARK_KANBAN_CLAIM_TOKEN": token,
            "SPARK_KANBAN_RUN_ID": str(run_id),
        }
    )
    # run_agent imports a generic dotenv loader that otherwise overrides even
    # SPARK_HOME/claim variables. We loaded the assigned profile explicitly;
    # prevent a second loader from replacing the dispatch identity in this worker.
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    fence: kb.WorkerFence = {"claim_token": token, "run_id": run_id}
    stop = threading.Event()
    lost = threading.Event()
    agent = None
    session_db = None

    def renew() -> None:
        while not stop.wait(min(30.0, ttl / 3)):
            try:
                kb.heartbeat(task_id, "Worker lease renewal", **fence)
            except Exception:
                # Losing ownership or the ability to renew must stop new work.
                # Unknown effects are reconciled for review, never redispatched.
                lost.set()
                if agent is not None:
                    agent.interrupt()
                return

    def handoff_metadata(limitation: str) -> dict:
        return {
            "changed_files": [],
            "verification": [],
            "limitations": [limitation],
            "verified": False,
        }

    try:
        kb.heartbeat(task_id, "Worker starting", **fence)
        kb.record_worker_execution(
            task_id,
            **fence,
            execution={
                "board_home": str(board),
                "profile_home": str(execution),
                "profile": profile,
            },
        )
        detail = kb.get_task_detail(task_id)
        if not detail:
            raise kb.WorkerClaimError("Task not found")
    except kb.WorkerClaimError as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 2

    thread = threading.Thread(target=renew, name="kanban-lease", daemon=True)
    thread.start()
    try:
        try:
            from core.run_agent import AIAgent
            from core.spark_state import SessionDB
            from spark_cli.model_config import read_global_model_config
            from spark_cli.runtime_provider import resolve_runtime_provider

            cfg = load_config()
            model = read_global_model_config(cfg).model
            runtime = resolve_runtime_provider(requested=None)
            session_db = SessionDB()
            agent = AIAgent(
                model=model or "",
                max_iterations=int(os.getenv("SPARK_KANBAN_MAX_ITER", "40")),
                quiet_mode=True,
                platform="kanban",
                session_id=f"kanban_{task_id}_{run_id}",
                session_db=session_db,
                enabled_toolsets=[
                    "terminal",
                    "file",
                    "web",
                    "browser",
                    "skills",
                    "todo",
                    "session_search",
                    "kanban",
                ],
                **_agent_runtime_kwargs(runtime),
            )
            refs = {
                key: reference
                for key in (
                    "session_id",
                    "root_run_id",
                    "attempt_id",
                    "node_id",
                    "parent_session_id",
                    "child_session_id",
                    "parent_node_id",
                    "subagent_id",
                )
                if (reference := getattr(agent, key, None)) is not None
            }
            kb.record_worker_execution(task_id, **fence, execution=refs)
        except kb.WorkerClaimError:
            return 2
        except Exception as error:
            kb.block_task(
                task_id,
                f"Worker failed to start agent: {error}",
                metadata=handoff_metadata("Agent startup failed; no completed work verified"),
                **fence,
            )
            return 3

        if lost.is_set():
            kb.block_task(
                task_id, "Lease renewal failed before execution; review required", **fence
            )
            return 4
        system_extra = (
            "You are a Spark task worker. Read kanban_show first. Execute the objective, then call "
            "kanban_complete with summary and metadata (changed_files, verification, limitations), "
            "or kanban_block if blocked. Completion requests user review; do not claim independent verification.\n\n"
            f"=== TASK CONTEXT ===\n{detail.get('worker_context', '')}"
        )
        result = (
            agent.run_conversation(
                "Execute this Kanban task now. Follow worker_context.",
                system_message=system_extra,
            )
            or {}
        )
        current = kb.get_task(task_id)
        if current and current["claim_token"] == token and current["current_run_id"] == run_id:
            final = result.get("final_response") or ""
            if (
                lost.is_set()
                or not final
                or result.get("backend_error_class")
                or result.get("interrupted")
                or result.get("failed")
                or result.get("error")
                or result.get("completed") is False
                or result.get("partial")
            ):
                kb.block_task(
                    task_id,
                    "Worker stopped without verified completion; review side effects before retry",
                    metadata=handoff_metadata("Execution ended without a confirmed completion"),
                    **fence,
                )
                return 4
            kb.complete_task(
                task_id,
                summary=str(final)[:8000],
                result="worker finished (unverified)",
                metadata={
                    "auto_closed": True,
                    **handoff_metadata(
                        "Text-only result; changed files and verification were not independently checked"
                    ),
                },
                **fence,
            )
        else:
            own_run = next(
                (
                    run
                    for run in (kb.get_task_detail(task_id) or {}).get("runs", [])
                    if run["id"] == run_id
                ),
                None,
            )
            if not own_run or own_run["outcome"] not in {"completed", "blocked"}:
                return 2  # Replacement/uncertain attempt; never report its success.
        return 0
    except kb.WorkerClaimError:
        return 2
    except Exception as error:
        try:
            kb.block_task(
                task_id,
                f"Worker exception: {error}",
                metadata=handoff_metadata("Execution failed; side effects may be incomplete"),
                **fence,
            )
        except kb.WorkerClaimError:
            return 2
        return 4
    finally:
        stop.set()
        thread.join(timeout=5)
        close = getattr(agent, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                logging.getLogger(__name__).exception("Worker resource cleanup failed")
        if session_db is not None:
            session_db.close()


if __name__ == "__main__":
    raise SystemExit(main())
