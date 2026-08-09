"""Small shared helpers for the web server and its route modules.

`_run_blocking` lived in web_server.py, but the extracted route modules need
it too and must not import web_server (that would be circular).
"""

from __future__ import annotations

import os
import secrets

from core.async_runtime import get_async_runtime


async def _run_blocking(function, /, *args, **kwargs):
    """Run web-server blocking work in Spark's bounded process worker pool."""
    return await get_async_runtime().run_blocking(function, *args, **kwargs)


# Bearer token for this server process; several route modules check it.
_SESSION_TOKEN = secrets.token_urlsafe(32)


def _is_desktop_app() -> bool:
    """True when running as a bundled desktop sidecar."""
    return os.environ.get("SPARK_DESKTOP") == "1"


def _desktop_app_version() -> str | None:
    """Version of the running .app shell, injected by Tauri at spawn time."""
    return os.environ.get("SPARK_DESKTOP_VERSION") or None
