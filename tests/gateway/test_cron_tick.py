from __future__ import annotations

import threading

from gateway.cron_tick import (
    DEFAULT_CRON_TICK_INTERVAL_SECONDS,
    start_cron_thread,
    start_cron_ticker,
)


class OneTickStop:
    def __init__(self) -> None:
        self.wait_timeouts: list[int] = []
        self._stopped = False

    def is_set(self) -> bool:
        return self._stopped

    def wait(self, timeout: int | None = None) -> bool:
        self.wait_timeouts.append(timeout)
        self._stopped = True
        return True


def test_cron_ticker_default_interval_stays_sixty_seconds(monkeypatch):
    calls = []

    def fake_tick(**kwargs):
        calls.append(kwargs)
        return 0

    monkeypatch.setattr("cron.scheduler.tick", fake_tick)
    stop = OneTickStop()

    start_cron_ticker(stop)  # type: ignore[arg-type]

    assert calls == [{"verbose": False, "adapters": None, "loop": None}]
    assert stop.wait_timeouts == [DEFAULT_CRON_TICK_INTERVAL_SECONDS]


def test_start_cron_thread_uses_gateway_ticker(monkeypatch):
    captured = {}

    class FakeThread:
        def __init__(self, *, target, args, kwargs, daemon, name):
            captured.update(
                target=target,
                args=args,
                kwargs=kwargs,
                daemon=daemon,
                name=name,
            )
            self.started = False

        def start(self):
            self.started = True

    monkeypatch.setattr(threading, "Thread", FakeThread)

    stop, thread = start_cron_thread(adapters={"telegram": object()}, loop="loop")

    assert isinstance(stop, threading.Event)
    assert captured["target"] is start_cron_ticker
    assert captured["kwargs"]["interval"] == DEFAULT_CRON_TICK_INTERVAL_SECONDS
    assert captured["kwargs"]["adapters"]
    assert captured["kwargs"]["loop"] == "loop"
    assert captured["daemon"] is True
    assert captured["name"] == "cron-ticker"
    assert thread.started is True


def test_gateway_run_keeps_import_compatible_entrypoints():
    import gateway.run as gateway_run

    assert hasattr(gateway_run, "GatewayRunner")
    assert hasattr(gateway_run, "start_gateway")
    assert hasattr(gateway_run, "_start_cron_ticker")
