"""Opt-in, process-local child workers with durable acceptance and result delivery.

The shared AsyncRuntime owns threads. SQLite owns lifecycle/receipts/results.
A lost worker is uncertain, never re-executed here. Like existing process
completion notifications, results become appended user context at a safe turn
boundary; the volatile process queue cannot provide our delivery acknowledgement.
"""

from __future__ import annotations

import copy
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Any

from agent import subagents
from core.orchestration.capabilities import TERMINAL_CHILD_STATES, owned_live_child
from core.spark_state import SessionDB

logger = logging.getLogger(__name__)
_BUILD_LOCK = threading.Lock()


def reconcile_lost_children(db: SessionDB) -> int:
    """Reconcile only proven owner loss, without timeout-based provider retries."""
    jobs = db.list_async_child_jobs(active_only=True)
    if not jobs:
        return 0
    from gateway.status import _get_process_start_time, _is_process_alive

    changed = 0
    for job in jobs:
        if job["state"] in TERMINAL_CHILD_STATES:
            continue
        pid = job["owner_pid"]
        start = _get_process_start_time(pid)
        lost = not _is_process_alive(pid)
        if job["owner_start"] is not None and start is not None:
            lost = lost or str(start) != job["owner_start"]
        if not lost:
            continue
        run = db.get_subagent_run(job["id"])
        if run is None:
            continue
        result = db.commit_subagent_lifecycle(
            {**run, "status": "uncertain", "error": "Worker process was lost; external effects are unknown",
             "exit_reason": "worker_lost"},
            {"event_id": f"{job['id']}:worker-lost", "event": "uncertain"},
        )
        changed += int(result["created"])
        db.mark_runtime_command(job["session_id"], job["command_kind"], job["request_id"], "uncertain")
    return changed


def reconcile_profile_children() -> int:
    db = SessionDB()
    try:
        return reconcile_lost_children(db)
    finally:
        db.close()


def deliver_results_at_turn_boundary(agent: Any, messages: list[dict[str, Any]]) -> None:
    """Common CLI/web/gateway boundary, with no automatic root run or external send."""
    db = getattr(agent, "_session_db", None)
    if not isinstance(db, SessionDB) or getattr(agent, "_delegate_depth", 0) != 0:
        return
    reconcile_lost_children(db)
    for message in db.deliver_async_child_results(agent.session_id):
        # Already committed atomically with delivery_id; normal flush must skip it.
        messages.append({"role": "user", "content": message["content"], "_internal": True})


def _worker(parent: Any, child: Any, run: dict[str, Any], goal: str) -> None:
    from tools.delegate_tool import _run_single_child

    try:
        if getattr(parent._async_owner, "_interrupt_requested", False):
            child.interrupt("Parent stopped before child execution")
        _run_single_child(run["task_index"], goal, child, parent, run)
    except Exception:
        logger.exception("Async child worker failed; preserving uncertain outcome")
        try:
            current = parent._session_db.get_subagent_run(run["id"]) or run
            parent._session_db.commit_subagent_lifecycle(
                {**current, "status": "uncertain", "error": "Worker failed outside acknowledged execution"},
                {"event_id": f"{run['id']}:worker-error", "event": "uncertain"},
            )
        except Exception:
            logger.exception("Unable to persist uncertain child; reconcile after process loss")
    finally:
        # _run_single_child normally unregisters/closes. Also cover failure before
        # its try/finally (e.g. a failed started commit). Cleanup is idempotent.
        with parent._active_children_lock:
            if child in parent._active_children:
                parent._active_children.remove(child)
        child.close()
        parent._session_db.close()


def dispatch_async_children(
    parent: Any, tasks: list[dict[str, Any]], *, request_id: str, payload: dict[str, Any],
    creds: dict[str, Any], max_iterations: int, max_children: int,
    retry_of: str | None = None, command_kind: str = "subagent.dispatch",
    owner_session_id: str | None = None,
) -> dict[str, Any]:
    from core.async_runtime import get_async_runtime
    from gateway.status import _get_process_start_time
    from tools.delegate_tool import (
        DELEGATE_BLOCKED_TOOLS,
        _build_child_agent,
        _resolve_workspace_hint,
    )

    db = getattr(parent, "_session_db", None)
    if not isinstance(db, SessionDB) or not db.get_session(parent.session_id):
        raise ValueError("Async delegation requires a durable owning session")
    reconcile_lost_children(db)
    owner = owner_session_id or parent.session_id
    existing = db.get_runtime_command(owner, command_kind, request_id, payload)
    if existing:
        return dict(existing["acceptance"])
    children: list[dict[str, Any]] = []
    for index, task in enumerate(tasks):
        run = subagents.make_run_record(
            parent_session_id=owner, root_run_id=getattr(parent, "_root_run_id", None),
            attempt_id=uuid.uuid4().hex, node_id=uuid.uuid4().hex,
            parent_node_id=getattr(parent, "_execution_node_id", None), task_index=index,
            task_count=len(tasks), task=task["goal"], context=task.get("context"),
            model=creds.get("model") or parent.model,
            provider=creds.get("provider") or getattr(parent, "provider", None),
            toolsets=task.get("toolsets") or [],
        )
        run.update({"execution_mode": "async", "worker_token": uuid.uuid4().hex,
                    "status": "created", "max_iterations": max_iterations,
                    "blocked_tools": sorted(DELEGATE_BLOCKED_TOOLS),
                    "workspace_path": _resolve_workspace_hint(parent), "retry_of": retry_of})
        started = _get_process_start_time(os.getpid())
        children.append({"run": run, "task": {**task, "max_iterations": max_iterations}, "owner_pid": os.getpid(),
                         "owner_start": str(started) if started is not None else None})
    handles = [{key: child["run"].get(key) for key in
                ("id", "parent_session_id", "root_run_id", "attempt_id", "node_id", "status")}
               for child in children]
    receipt = db.accept_runtime_command(
        owner, command_kind, request_id, payload,
        {"mode": "async", "status": "accepted", "handles": handles},
        {"children": [h["id"] for h in handles], "worker_kind": "process_local"},
        children=children, max_children=max_children,
    )
    if not receipt["created"]:
        return dict(receipt["acceptance"])
    import core.model_tools as model_tools

    for child_job in children:
        run, task = child_job["run"], child_job["task"]
        worker_parent = copy.copy(parent)
        worker_parent._session_db = SessionDB(Path(db.db_path))
        worker_parent._async_owner = parent
        child = None
        try:
            with _BUILD_LOCK:
                saved = list(model_tools._last_resolved_tool_names)
                try:
                    child = _build_child_agent(
                        task_index=run["task_index"], goal=task["goal"], context=task.get("context"),
                        toolsets=task.get("toolsets"), model=creds.get("model"),
                        max_iterations=max_iterations, parent_agent=worker_parent,
                        override_provider=creds.get("provider"), override_base_url=creds.get("base_url"),
                        override_api_key=creds.get("api_key"), override_api_mode=creds.get("api_mode"),
                        override_reasoning_effort=creds.get("reasoning_effort"),
                        override_acp_command=task.get("acp_command"), override_acp_args=task.get("acp_args"),
                        lifecycle_run=run, task_count=len(tasks),
                    )
                    child._delegate_saved_tool_names = saved
                finally:
                    model_tools._last_resolved_tool_names = saved
            child._spark_async_child = True
            if getattr(child, "_spark_async_cancel_event", None) is None:
                child._spark_async_cancel_event = threading.Event()
            run["child_session_id"] = child.session_id
            run["model"] = child.model
            run["provider"] = child.provider
            run["workspace_path"] = child.working_dir
            run["toolsets"] = list(getattr(child, "enabled_toolsets", None) or [])
            subagents.emit(worker_parent, run, "status", {"status": "created"})
            get_async_runtime().submit_named("delegated-children", max_children, _worker,
                                             worker_parent, child, run, task["goal"])
        except Exception as exc:
            worker_parent._session_db.commit_subagent_lifecycle(
                {**run, "status": "failed", "error": f"Child setup failed: {exc}"},
                {"event_id": f"{run['id']}:setup-failed", "event": "failed"},
            )
            if child is not None:
                with parent._active_children_lock:
                    if child in parent._active_children:
                        parent._active_children.remove(child)
                child.close()
            worker_parent._session_db.close()
    db.mark_runtime_command(owner, command_kind, request_id, "dispatched")
    return dict(receipt["acceptance"])


def child_control(parent: Any, mode: str, handle: str, request_id: str | None) -> dict[str, Any]:
    """Inspect or cooperatively cancel a durable child owned by this session family."""
    db = getattr(parent, "_session_db", None)
    if not isinstance(db, SessionDB):
        raise ValueError("Child controls require a durable owning session")
    reconcile_lost_children(db)
    run = db.get_subagent_run(handle)
    if not run or run.get("parent_session_id") not in db.resolve_compression_chain(parent.session_id):
        raise ValueError("Owned child not found")
    if mode == "status":
        return {"handle": handle, "subagent": run}
    if mode != "cancel":
        raise ValueError("Unsupported child control")
    if not request_id:
        raise ValueError("Async cancellation requires request_id")
    owner = run["parent_session_id"]
    payload = {"subagent_id": handle, "message": None}
    existing = db.get_runtime_command(owner, "subagent.interrupt", request_id, payload)
    if existing:
        return dict(existing["acceptance"])
    child = owned_live_child(parent, run)
    if child is None:
        raise ValueError("No live owned child is available")
    receipt = db.accept_runtime_command(owner, "subagent.interrupt", request_id, payload,
                                        {"ok": True, "subagent_id": handle, "status": "stopping"},
                                        {"subagent_id": handle, "action": "interrupt"})
    if receipt["created"]:
        try:
            child.interrupt(None)
            subagents.emit(parent, run, "status", {"status": "stopping", "preview": "Interrupt requested"})
            db.mark_runtime_command(owner, "subagent.interrupt", request_id, "dispatched")
        except Exception:
            db.mark_runtime_command(owner, "subagent.interrupt", request_id, "uncertain")
            raise
    return dict(receipt["acceptance"])


def retry_async_child(parent: Any, handle: str, request_id: str) -> dict[str, Any]:
    """Explicitly retry a known failed/stopped attempt, preserving the earlier one."""
    from tools.delegate_tool import (
        _get_max_concurrent_children,
        _load_config,
        _resolve_subagent_credentials,
    )

    db = getattr(parent, "_session_db", None)
    if not isinstance(db, SessionDB):
        raise ValueError("Retry requires a durable owning session")
    run = db.get_subagent_run(handle)
    if not run or run.get("parent_session_id") not in db.resolve_compression_chain(parent.session_id):
        raise ValueError("Owned child not found")
    owner = run["parent_session_id"]
    payload = {"retry_of": handle}
    existing = db.get_runtime_command(owner, "subagent.retry", request_id, payload)
    if existing:
        return dict(existing["acceptance"])
    cfg = _load_config()
    if cfg.get("async_enabled") is not True:
        raise ValueError("Async execution is disabled")
    if run.get("status") not in {"failed", "interrupted", "cancelled"}:
        raise ValueError("Retry requires an acknowledged failed or stopped child; uncertain effects need review")
    job = next((job for job in db.list_async_child_jobs(owner) if job["id"] == handle), None)
    if job is None:
        raise ValueError("Only stored async attempts can be retried")
    return dispatch_async_children(
        parent, [job["task"]], request_id=request_id, payload=payload,
        creds=_resolve_subagent_credentials(cfg, parent),
        max_iterations=job["task"].get("max_iterations") or cfg.get("max_iterations", 50),
        max_children=_get_max_concurrent_children(), retry_of=handle,
        command_kind="subagent.retry", owner_session_id=owner,
    )
