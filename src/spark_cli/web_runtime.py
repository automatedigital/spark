"""Small shared helpers for the web server and its route modules.

`_run_blocking` lived in web_server.py, but the extracted route modules need
it too and must not import web_server (that would be circular).
"""

from __future__ import annotations

from core.async_runtime import get_async_runtime


async def _run_blocking(function, /, *args, **kwargs):
    """Run web-server blocking work in Spark's bounded process worker pool."""
    return await get_async_runtime().run_blocking(function, *args, **kwargs)
