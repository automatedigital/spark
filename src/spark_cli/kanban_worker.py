#!/usr/bin/env python3
"""One-shot Kanban worker process — run as subprocess from gateway dispatcher."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Ensure src/ on path when run as -m spark_cli.kanban_worker
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def main() -> int:
    task_id = os.getenv("SPARK_KANBAN_TASK", "").strip()
    if not task_id:
        print("SPARK_KANBAN_TASK not set", file=sys.stderr)
        return 2

    from core import kanban_db as kb
    from core.run_agent import AIAgent
    from spark_cli.config import load_config

    detail = kb.get_task_detail(task_id)
    if not detail:
        print("Task not found", file=sys.stderr)
        return 2

    cfg = load_config()
    model_cfg = cfg.get("model", "")
    if isinstance(model_cfg, dict):
        model = str(model_cfg.get("default") or model_cfg.get("name") or "")
    else:
        model = str(model_cfg or "")
    model = model.strip() or "anthropic/claude-sonnet-4.6"

    system_extra = (
        "You are a Spark task worker. Treat the task as a /goal-style objective: "
        "work toward the stated outcome, keep task context current, and stop only when "
        "the objective is ready for user review or blocked on human input. You MUST use "
        "kanban_show first to read context, then use terminal/file/web tools as needed. "
        "When finished call kanban_complete with a clear summary and metadata "
        "(changed_files, verification). If blocked on a human decision, call "
        "kanban_block with a short reason.\n\n"
        f"=== TASK CONTEXT ===\n{detail.get('worker_context', '')}"
    )

    try:
        agent = AIAgent(
            model=model,
            max_iterations=int(os.getenv("SPARK_KANBAN_MAX_ITER", "40")),
            quiet_mode=True,
            platform="kanban",
            session_id=f"kanban_{task_id}",
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
        )
    except Exception as e:
        kb.block_task(task_id, f"Worker failed to start agent: {e}")
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        return 3

    user_msg = (
        "Execute this Kanban task now. Follow worker_context. "
        "Start with kanban_show if you need the full structured task payload."
    )
    try:
        result = agent.run_conversation(user_msg, system_message=system_extra)
        final = (result or {}).get("final_response") or ""
        if final and "kanban_complete" not in str(final).lower():
            # Ensure closure if model returned text only
            st = kb.get_task(task_id)
            if st and st.get("status") == "running":
                kb.complete_task(
                    task_id,
                    summary=(final or "")[:8000],
                    metadata={"auto_closed": True},
                    result="worker finished (auto)",
                )
    except KeyboardInterrupt:
        raise
    except Exception as e:
        kb.block_task(task_id, f"Worker exception: {e}")
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
