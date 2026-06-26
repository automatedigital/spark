"""Gateway-owned cron scheduler ticker."""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_CRON_TICK_INTERVAL_SECONDS = 60
IMAGE_CACHE_CLEANUP_EVERY_TICKS = 60
CHANNEL_DIRECTORY_REFRESH_EVERY_TICKS = 5


def start_cron_ticker(
    stop_event: threading.Event,
    adapters: dict[Any, Any] | None = None,
    loop: Any = None,
    interval: int = DEFAULT_CRON_TICK_INTERVAL_SECONDS,
) -> None:
    """Tick cron jobs and gateway maintenance until ``stop_event`` is set."""
    from cron.scheduler import tick as cron_tick
    from gateway.platforms.base import cleanup_document_cache, cleanup_image_cache

    logger.info("Cron ticker started (interval=%ds)", interval)
    tick_count = 0
    while not stop_event.is_set():
        try:
            cron_tick(verbose=False, adapters=adapters, loop=loop)
        except Exception as exc:
            logger.debug("Cron tick error: %s", exc)

        tick_count += 1

        if tick_count % CHANNEL_DIRECTORY_REFRESH_EVERY_TICKS == 0 and adapters:
            try:
                from gateway.channel_directory import build_channel_directory

                build_channel_directory(adapters)
            except Exception as exc:
                logger.debug("Channel directory refresh error: %s", exc)

        if tick_count % IMAGE_CACHE_CLEANUP_EVERY_TICKS == 0:
            try:
                removed = cleanup_image_cache(max_age_hours=24)
                if removed:
                    logger.info("Image cache cleanup: removed %d stale file(s)", removed)
            except Exception as exc:
                logger.debug("Image cache cleanup error: %s", exc)
            try:
                removed = cleanup_document_cache(max_age_hours=24)
                if removed:
                    logger.info("Document cache cleanup: removed %d stale file(s)", removed)
            except Exception as exc:
                logger.debug("Document cache cleanup error: %s", exc)

        stop_event.wait(timeout=interval)
    logger.info("Cron ticker stopped")


def start_cron_thread(
    *,
    adapters: dict[Any, Any] | None = None,
    loop: Any = None,
    interval: int = DEFAULT_CRON_TICK_INTERVAL_SECONDS,
) -> tuple[threading.Event, threading.Thread]:
    """Start the gateway cron ticker in a daemon thread."""
    cron_stop = threading.Event()
    cron_thread = threading.Thread(
        target=start_cron_ticker,
        args=(cron_stop,),
        kwargs={"adapters": adapters, "loop": loop, "interval": interval},
        daemon=True,
        name="cron-ticker",
    )
    cron_thread.start()
    return cron_stop, cron_thread
