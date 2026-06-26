"""Desktop gateway autostart/shutdown.

On the macOS desktop app, the messaging gateway should run in the background
whenever the app is open, so platforms (Telegram, Discord, …) can reach Spark
even while the user is just chatting locally.

The desktop sidecar is a frozen PyInstaller binary whose only entry point is the
FastAPI web server — it cannot re-exec itself as ``spark gateway run`` in a
subprocess. So we run the gateway **in-process** on a dedicated background
thread with its own asyncio event loop. ``start_gateway()`` writes the PID file
with this process's PID, which is exactly what ``get_running_pid()`` (and hence
``/api/status``) checks — so the footer/status flips to "running" automatically.

Ownership tracking: we only ever stop a gateway *we* started. If a gateway is
already running when the app launches (e.g. a user-managed external gateway or a
launchd service), we leave it completely alone and never touch its lifecycle.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from gateway.run import GatewayRunner

logger = logging.getLogger(__name__)


def is_desktop_app() -> bool:
    """True when running as the local desktop sidecar (Tauri sets SPARK_DESKTOP=1)."""
    return os.environ.get("SPARK_DESKTOP") == "1"


def gateway_autostart_enabled() -> bool:
    """Return the ``desktop.gateway_autostart`` config setting (default True)."""
    try:
        from spark_cli.config import load_config

        cfg = load_config()
        desktop = cfg.get("desktop") if isinstance(cfg, dict) else None
        if isinstance(desktop, dict) and "gateway_autostart" in desktop:
            return bool(desktop["gateway_autostart"])
    except Exception:
        logger.debug("Failed reading desktop.gateway_autostart", exc_info=True)
    return True


class DesktopGatewaySupervisor:
    """Owns the background gateway started by the desktop app.

    Lifecycle is bound to the sidecar process: ``start()`` on app launch,
    ``stop()`` on app quit. Only stops a gateway this supervisor started.
    """

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._runner: GatewayRunner | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._started_by_us = False
        self._lock = threading.Lock()

    @property
    def started_by_us(self) -> bool:
        return self._started_by_us

    def maybe_start(self) -> bool:
        """Start the gateway in the background if appropriate.

        Returns True when this call launched a gateway thread. No-ops (returning
        False) when: not the desktop app, autostart disabled, a gateway is
        already running (we never adopt or stop an external one), or already
        started by this supervisor.
        """
        if not is_desktop_app():
            return False
        if not gateway_autostart_enabled():
            logger.info("Desktop gateway autostart disabled via config; skipping.")
            return False

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False

            # Never touch a gateway we didn't start (user-managed / launchd).
            try:
                from gateway.status import get_running_pid

                existing = get_running_pid()
            except Exception:
                existing = None
            if existing is not None:
                logger.info(
                    "Gateway already running (PID %s); desktop app will not manage it.",
                    existing,
                )
                return False

            self._started_by_us = True
            self._thread = threading.Thread(
                target=self._run,
                name="desktop-gateway",
                daemon=True,
            )
            self._thread.start()
            logger.info("Started background gateway for desktop app.")
            return True

    def _capture_runner(self, runner: GatewayRunner) -> None:
        self._runner = runner

    def _run(self) -> None:
        """Run the gateway to completion on its own event loop."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            from gateway.run import start_gateway

            loop.run_until_complete(
                start_gateway(on_runner=self._capture_runner)
            )
        except SystemExit:
            pass
        except Exception:
            logger.warning("Background desktop gateway exited with error", exc_info=True)
        finally:
            try:
                loop.close()
            except Exception:
                pass
            self._loop = None
            self._runner = None

    def stop(self, timeout: float = 15.0) -> None:
        """Gracefully stop the gateway, but only if this supervisor started it."""
        with self._lock:
            if not self._started_by_us:
                return
            runner = self._runner
            loop = self._loop
            thread = self._thread

        if runner is not None and loop is not None and not loop.is_closed():
            try:
                # ``stop()`` is a coroutine that must run on the gateway's loop.
                asyncio.run_coroutine_threadsafe(runner.stop(), loop)
            except Exception:
                logger.debug("Failed scheduling gateway stop", exc_info=True)

        if thread is not None:
            thread.join(timeout=timeout)
            if thread.is_alive():
                logger.warning(
                    "Background gateway did not stop within %.0fs; leaving daemon thread.",
                    timeout,
                )

        with self._lock:
            self._started_by_us = False
            self._thread = None
            self._runner = None
            self._loop = None


# Process-global supervisor for the desktop sidecar.
_supervisor = DesktopGatewaySupervisor()


def start_desktop_gateway() -> bool:
    """Entry point called from the web server lifespan on startup."""
    return _supervisor.maybe_start()


def stop_desktop_gateway() -> None:
    """Entry point called from the web server lifespan on shutdown."""
    _supervisor.stop()
