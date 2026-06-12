#!/usr/bin/env python3
"""Take-over / pause control for the shared preview browser session (PLAN.md 2b).

When the user grabs control of the shared preview session mid-task (e.g. to
solve a login or CAPTCHA), the agent's mutating browser actions must pause and
queue rather than fight the user for the page. This module stores a tiny
per-session control flag on disk so both the WebUI routes (which toggle it) and
the agent's browser tool (which checks it) agree without any shared process.

The flag lives under ``get_spark_home()/browser/<slug>/control.json`` — never
hardcode ``~/.spark``. Keyed by the same workspace slug the action log uses, and
by the ``SPARK_BROWSER_PREVIEW_SESSION`` env binding when called from the agent.

Import-safe and dependency-free; all readers/writers swallow ``Exception`` so a
control-file glitch can never break a browser action.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()


def _safe_slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "-", value) or "default"


def _session_slug() -> str:
    name = (os.environ.get("SPARK_BROWSER_PREVIEW_SESSION") or "").strip()
    if name:
        return _safe_slug(name.removeprefix("spark-preview-"))
    return "default"


def _control_path(slug: str | None = None):
    from pathlib import Path

    from core.spark_constants import get_spark_home

    bucket = _safe_slug(slug) if slug else _session_slug()
    return Path(get_spark_home()) / "browser" / bucket / "control.json"


def set_paused(paused: bool, *, slug: str | None = None) -> None:
    """Set the take-over (pause) flag for a session.

    ``paused=True`` means the user has control; the agent must not execute
    mutating actions until the user hands control back (``paused=False``).
    """
    try:
        path = _control_path(slug)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"paused": bool(paused), "ts": time.time()}
        with _lock:
            path.write_text(json.dumps(payload), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 — control glitch must not break actions
        logger.debug("Failed to set browser pause flag: %s", exc)


def is_paused(slug: str | None = None) -> bool:
    """Return True when the user currently holds control of the session."""
    try:
        path = _control_path(slug)
        if not path.exists():
            return False
        with _lock:
            data: Any = json.loads(path.read_text(encoding="utf-8"))
        return bool(isinstance(data, dict) and data.get("paused"))
    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed to read browser pause flag: %s", exc)
        return False


def get_state(slug: str | None = None) -> dict[str, Any]:
    """Return the full control state ``{paused, ts}`` for surfacing in the pane."""
    try:
        path = _control_path(slug)
        if not path.exists():
            return {"paused": False, "ts": 0.0}
        with _lock:
            data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {"paused": bool(data.get("paused")), "ts": float(data.get("ts", 0.0))}
    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed to read browser control state: %s", exc)
    return {"paused": False, "ts": 0.0}
