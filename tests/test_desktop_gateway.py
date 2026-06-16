"""Tests for the desktop gateway autostart supervisor and config opt-out."""

import asyncio

from spark_cli import desktop_gateway
from spark_cli.config import DEFAULT_CONFIG


def test_config_has_desktop_gateway_autostart_default():
    assert DEFAULT_CONFIG["desktop"]["gateway_autostart"] is True
    # Migration must be bumped so existing configs gain the new block.
    assert DEFAULT_CONFIG["_config_version"] >= 25


def test_is_desktop_app(monkeypatch):
    monkeypatch.delenv("SPARK_DESKTOP", raising=False)
    assert desktop_gateway.is_desktop_app() is False
    monkeypatch.setenv("SPARK_DESKTOP", "1")
    assert desktop_gateway.is_desktop_app() is True


def test_autostart_enabled_default(monkeypatch):
    monkeypatch.setattr(desktop_gateway, "load_config", lambda: {}, raising=False)
    # No desktop block -> default True
    assert desktop_gateway.gateway_autostart_enabled() is True


def test_autostart_disabled_via_config(monkeypatch):
    import spark_cli.config as cfg

    monkeypatch.setattr(
        cfg, "load_config", lambda: {"desktop": {"gateway_autostart": False}}
    )
    assert desktop_gateway.gateway_autostart_enabled() is False


def test_maybe_start_noop_when_not_desktop(monkeypatch):
    monkeypatch.delenv("SPARK_DESKTOP", raising=False)
    sup = desktop_gateway.DesktopGatewaySupervisor()
    assert sup.maybe_start() is False
    assert sup.started_by_us is False


def test_maybe_start_noop_when_disabled(monkeypatch):
    monkeypatch.setenv("SPARK_DESKTOP", "1")
    monkeypatch.setattr(desktop_gateway, "gateway_autostart_enabled", lambda: False)
    sup = desktop_gateway.DesktopGatewaySupervisor()
    assert sup.maybe_start() is False
    assert sup.started_by_us is False


def test_maybe_start_does_not_adopt_external_gateway(monkeypatch):
    """If a gateway is already running, the desktop app must not manage it."""
    monkeypatch.setenv("SPARK_DESKTOP", "1")
    monkeypatch.setattr(desktop_gateway, "gateway_autostart_enabled", lambda: True)
    import gateway.status as status

    monkeypatch.setattr(status, "get_running_pid", lambda: 4242)
    sup = desktop_gateway.DesktopGatewaySupervisor()
    assert sup.maybe_start() is False
    assert sup.started_by_us is False


def test_maybe_start_launches_when_clear(monkeypatch):
    """Desktop + enabled + no existing gateway -> starts and owns it."""
    monkeypatch.setenv("SPARK_DESKTOP", "1")
    monkeypatch.setattr(desktop_gateway, "gateway_autostart_enabled", lambda: True)
    import gateway.status as status

    monkeypatch.setattr(status, "get_running_pid", lambda: None)

    started = asyncio.Event()

    async def _fake_start_gateway(*args, on_runner=None, **kwargs):
        # Never launch a real gateway; just signal and idle briefly.
        started.set()
        await asyncio.sleep(0.05)
        return True

    import gateway.run as run

    monkeypatch.setattr(run, "start_gateway", _fake_start_gateway)

    sup = desktop_gateway.DesktopGatewaySupervisor()
    try:
        assert sup.maybe_start() is True
        assert sup.started_by_us is True
        # Second call is a no-op while the thread is alive.
        assert sup.maybe_start() is False
    finally:
        sup.stop(timeout=2.0)
    assert sup.started_by_us is False


def test_stop_noop_when_not_owner():
    sup = desktop_gateway.DesktopGatewaySupervisor()
    # Never started -> stop must be a safe no-op.
    sup.stop(timeout=0.1)
    assert sup.started_by_us is False
