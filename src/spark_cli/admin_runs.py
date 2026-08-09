"""Shared machinery for long-running admin actions.

The admin, mcp, plugins and gateway route families all start a subprocess,
stream its output through a queue, and expose the run by id. That plumbing
lived in web_server.py; it sits here so those route modules can share it
without importing web_server.
"""

from __future__ import annotations

import logging
import os
import queue as thread_queue
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

_log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.resolve()


_admin_runs: dict[str, dict[str, Any]] = {}


_admin_run_queues: dict[str, thread_queue.Queue] = {}


def _queue_admin_event(run_id: str, event: dict) -> None:
    queue = _admin_run_queues.get(run_id)
    if queue is None:
        return
    try:
        queue.put_nowait(event)
    except Exception:
        _log.debug("Ignoring error in _queue_admin_event()", exc_info=True)


def _append_admin_output(run_id: str, stream: str, text: str) -> None:
    run = _admin_runs.get(run_id)
    if not run:
        return
    tail = run.setdefault("output_tail", [])
    tail.append({"stream": stream, "text": text, "ts": time.time()})
    del tail[:-200]


class AdminActionStart(BaseModel):
    args: dict[str, Any] = {}
    confirm: bool = False


class AdminAction:
    def __init__(
        self,
        action_id: str,
        label: str,
        description: str,
        risk: str,
        command: Callable[[dict[str, Any]], list[str]],
        *,
        requires_confirmation: bool = False,
        long_running: bool = False,
        args_schema: dict | None = None,
        availability: Callable[[], tuple[bool, str | None]] | None = None,
    ):
        self.id = action_id
        self.label = label
        self.description = description
        self.risk = risk
        self.command = command
        self.requires_confirmation = requires_confirmation
        self.long_running = long_running
        self.args_schema = args_schema or {"type": "object", "properties": {}}
        self.availability = availability

    def to_metadata(self) -> dict:
        available = True
        reason = None
        if self.availability:
            available, reason = self.availability()
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "risk": self.risk,
            "requires_confirmation": self.requires_confirmation,
            "long_running": self.long_running,
            "args_schema": self.args_schema,
            "available": available,
            "unavailable_reason": reason,
        }


def _spark_command(*parts: str) -> list[str]:
    return [sys.executable, "-m", "spark_cli.main", *parts]


def _new_admin_run(action_id: str, args: dict) -> tuple[str, thread_queue.Queue]:
    run_id = uuid.uuid4().hex
    queue: thread_queue.Queue = thread_queue.Queue(maxsize=512)
    _admin_runs[run_id] = {
        "run_id": run_id,
        "action_id": action_id,
        "args": args,
        "status": "queued",
        "started_at": None,
        "finished_at": None,
        "exit_code": None,
        "output_tail": [],
        "error": None,
    }
    _admin_run_queues[run_id] = queue
    return run_id, queue


def _run_admin_action(run_id: str, action: AdminAction, args: dict) -> None:
    run = _admin_runs[run_id]
    run["status"] = "running"
    run["started_at"] = time.time()
    _queue_admin_event(run_id, {"type": "state", "status": "running"})
    try:
        cmd = action.command(args)
        _queue_admin_event(run_id, {"type": "output", "stream": "system", "text": " ".join(cmd)})
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTHONUNBUFFERED"] = "1"
        proc = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        if proc.stdout is not None:
            for line in proc.stdout:
                text = line.rstrip("\n")
                _append_admin_output(run_id, "stdout", text)
                _queue_admin_event(run_id, {"type": "output", "stream": "stdout", "text": text})
        exit_code = proc.wait()
        run["exit_code"] = exit_code
        run["status"] = "done" if exit_code == 0 else "failed"
    except Exception as exc:
        run["status"] = "failed"
        run["error"] = str(exc)
        _queue_admin_event(run_id, {"type": "output", "stream": "stderr", "text": str(exc)})
    finally:
        run["finished_at"] = time.time()
        _queue_admin_event(run_id, {"type": "done", "run": run})


def _gateway_command(action: str) -> list[str]:
    return _spark_command("gateway", action)


def _update_command(check_only: bool) -> list[str]:
    try:
        from core.spark_constants import get_spark_home
        spark_home = get_spark_home()
        # Always clear the cache so we do a fresh git fetch, not a stale 6-hour result
        (spark_home / ".update_check").unlink(missing_ok=True)
        if not check_only:
            # Pre-write "y" so _gateway_prompt auto-accepts the "run installer?" question
            (spark_home / ".update_response").write_text("y")
    except Exception:
        _log.debug("Ignoring error in _update_command()", exc_info=True)
    if check_only:
        return _spark_command("version")
    return _spark_command("update", "--gateway")


def _debug_command(args: dict[str, Any]) -> list[str]:
    lines = int(args.get("lines") or 200)
    lines = max(20, min(lines, 2000))
    return _spark_command("debug", "share", "--local", "--lines", str(lines))


ADMIN_ACTIONS: dict[str, AdminAction] = {
    "gateway.start": AdminAction(
        "gateway.start",
        "Start gateway",
        "Start the configured messaging gateway service.",
        "medium",
        lambda _args: _gateway_command("start"),
        requires_confirmation=True,
        long_running=True,
    ),
    "gateway.stop": AdminAction(
        "gateway.stop",
        "Stop gateway",
        "Stop the configured messaging gateway service.",
        "high",
        lambda _args: _gateway_command("stop"),
        requires_confirmation=True,
    ),
    "gateway.restart": AdminAction(
        "gateway.restart",
        "Restart gateway",
        "Restart the configured messaging gateway service.",
        "high",
        lambda _args: _gateway_command("restart"),
        requires_confirmation=True,
        long_running=True,
    ),
    "gateway.install": AdminAction(
        "gateway.install",
        "Install gateway service",
        "Install the OS service wrapper for the gateway.",
        "high",
        lambda _args: _gateway_command("install"),
        requires_confirmation=True,
        long_running=True,
    ),
    "gateway.uninstall": AdminAction(
        "gateway.uninstall",
        "Uninstall gateway service",
        "Remove the OS service wrapper for the gateway.",
        "high",
        lambda _args: _gateway_command("uninstall"),
        requires_confirmation=True,
    ),
    "gateway.status": AdminAction(
        "gateway.status",
        "Gateway service status",
        "Read foreground, runtime, and service status.",
        "low",
        lambda _args: _gateway_command("status"),
    ),
    "diagnostics.doctor": AdminAction(
        "diagnostics.doctor",
        "Run doctor",
        "Run Spark diagnostics and report configuration issues.",
        "low",
        lambda _args: _spark_command("doctor"),
    ),
    "diagnostics.doctor_fix": AdminAction(
        "diagnostics.doctor_fix",
        "Run doctor fix",
        "Run Spark doctor with repair mode where supported.",
        "medium",
        lambda _args: _spark_command("doctor", "--fix"),
        requires_confirmation=True,
    ),
    "diagnostics.debug": AdminAction(
        "diagnostics.debug",
        "Build debug report",
        "Generate a local debug preview with bounded log output.",
        "low",
        _debug_command,
        args_schema={
            "type": "object",
            "properties": {"lines": {"type": "integer", "minimum": 20, "maximum": 2000}},
        },
    ),
    "backup.quick": AdminAction(
        "backup.quick",
        "Quick backup",
        "Create a quick Spark backup.",
        "medium",
        lambda _args: _spark_command("backup", "--quick"),
        requires_confirmation=True,
        long_running=True,
    ),
    "backup.full": AdminAction(
        "backup.full",
        "Full backup",
        "Create a full Spark backup.",
        "medium",
        lambda _args: _spark_command("backup"),
        requires_confirmation=True,
        long_running=True,
    ),
    "update.check": AdminAction(
        "update.check",
        "Check for updates",
        "Check whether a Spark update is available.",
        "low",
        lambda _args: _update_command(True),
        long_running=True,
    ),
    "update.run": AdminAction(
        "update.run",
        "Run update",
        "Run Spark's update flow.",
        "high",
        lambda _args: _update_command(False),
        requires_confirmation=True,
        long_running=True,
    ),
}
