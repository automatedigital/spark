#!/usr/bin/env python3
"""Append-only audit log for agent browser actions (PLAN.md 2b).

Every agent browser action (navigate / click / type / press / scroll / a11y /
permission decisions) is recorded to an append-only JSONL file tied to the
shared workspace preview session, so the preview pane can display an auditable
transcript of what the agent did.

The log path lives under ``get_spark_home()`` — never hardcode ``~/.spark``.
When the agent is bound to a WebUI preview (``SPARK_BROWSER_PREVIEW_SESSION``)
the log is keyed by that session slug so the pane and the agent agree on the
same file.  Otherwise it falls back to a generic ``default`` bucket.

This module has no heavy dependencies and is import-safe; failures to write the
log must never break a browser action, so all writers swallow ``Exception``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()

# Cap how many lines we return / retain in a single read so a long-running
# session can't blow up the pane or memory.
MAX_LOG_LINES = 2000


def _safe_slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "-", value) or "default"


def _session_slug() -> str:
    """Derive the log bucket from the shared preview session binding.

    ``SPARK_BROWSER_PREVIEW_SESSION`` is ``spark-preview-<slug>``; strip the
    prefix so the on-disk path matches the workspace slug the pane uses.
    """
    name = (os.environ.get("SPARK_BROWSER_PREVIEW_SESSION") or "").strip()
    if name:
        return _safe_slug(name.removeprefix("spark-preview-"))
    return "default"


def _log_dir(slug: Optional[str] = None) -> Path:
    from core.spark_constants import get_spark_home

    bucket = _safe_slug(slug) if slug else _session_slug()
    return get_spark_home() / "browser" / bucket


def log_path(slug: Optional[str] = None) -> Path:
    """Absolute path to the action-log JSONL for the given (or current) session."""
    return _log_dir(slug) / "action_log.jsonl"


def record_action(
    action: str,
    *,
    status: str = "ok",
    detail: Optional[dict[str, Any]] = None,
    task_id: Optional[str] = None,
    slug: Optional[str] = None,
) -> None:
    """Append one action record to the session's audit log.

    Never raises — a logging failure must not break the browser action.

    Args:
        action: Action name, e.g. ``navigate``, ``click``, ``type``, ``a11y``,
                ``permission_required``, ``permission_granted``.
        status: ``ok`` | ``blocked`` | ``error`` | ``needs_confirmation``.
        detail: JSON-serialisable extra context (url, ref, classification…).
        task_id: Agent task id for correlation.
        slug: Override the session bucket (defaults to the env binding).
    """
    try:
        entry = {
            "ts": time.time(),
            "action": str(action),
            "status": str(status),
            "task_id": task_id,
            "detail": detail or {},
        }
        directory = _log_dir(slug)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "action_log.jsonl"
        line = json.dumps(entry, ensure_ascii=False)
        with _lock:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception as exc:  # noqa: BLE001 — logging must never break actions
        logger.debug("Failed to record browser action %r: %s", action, exc)


def read_actions(
    slug: Optional[str] = None,
    *,
    limit: int = MAX_LOG_LINES,
    since_ts: Optional[float] = None,
) -> list[dict[str, Any]]:
    """Return recorded actions for a session, newest-last, oldest dropped.

    Args:
        slug: Session bucket (defaults to the env binding).
        limit: Max number of entries to return (most recent).
        since_ts: If set, only return entries with ``ts`` strictly greater.
    """
    path = log_path(slug)
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        with _lock:
            with open(path, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
        for raw in lines[-max(limit, 1) * 2 :]:
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if since_ts is not None and float(entry.get("ts", 0)) <= since_ts:
                continue
            out.append(entry)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed to read browser action log: %s", exc)
        return []
    return out[-max(limit, 1):]
