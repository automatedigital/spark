"""Run the Spark Web UI dashboard server (async, embeddable in gateway)."""

from __future__ import annotations

import logging

_log = logging.getLogger(__name__)

_uvicorn_server = None


async def run_dashboard_server(
    host: str,
    port: int,
    *,
    open_browser: bool = False,
) -> None:
    """Serve the FastAPI app until ``should_exit`` is set or task cancelled."""
    try:
        import uvicorn
    except ImportError:
        _log.warning("uvicorn not installed; dashboard unavailable")
        return

    from spark_cli.web_server import app

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
    )
    global _uvicorn_server
    server = uvicorn.Server(config)
    _uvicorn_server = server

    if open_browser:
        import threading
        import time
        import webbrowser

        browse_host = "127.0.0.1" if host in ("0.0.0.0", "::", "[::]") else host

        def _open() -> None:
            time.sleep(0.8)
            webbrowser.open(f"http://{browse_host}:{port}")

        threading.Thread(target=_open, daemon=True).start()

    try:
        await server.serve()
    finally:
        _uvicorn_server = None


def stop_dashboard_server() -> None:
    """Signal the embedded uvicorn server to stop."""
    s = _uvicorn_server
    if s is not None:
        s.should_exit = True
