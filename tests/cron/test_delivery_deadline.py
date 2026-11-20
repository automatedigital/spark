"""Live cron delivery deadlines at the gateway event loop boundary."""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cron import scheduler
from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import SendResult

JOB = {
    "id": "delivery-deadline",
    "deliver": "origin",
    "origin": {"platform": "telegram", "chat_id": "123", "thread_id": "456"},
}
ATTACHMENTS = "MEDIA:/tmp/fixture.png\nMEDIA:/tmp/fixture.pdf"


@pytest.fixture
def delivery_config(monkeypatch):
    platform_config = PlatformConfig(enabled=True)
    gateway_config = GatewayConfig(platforms={Platform.TELEGRAM: platform_config})
    monkeypatch.setattr("gateway.config.load_gateway_config", lambda: gateway_config)
    monkeypatch.setattr(scheduler, "load_config", lambda: {"cron": {"wrap_response": False}})
    standalone = AsyncMock(return_value={"success": True})
    monkeypatch.setattr("tools.send_message_tool._send_to_platform", standalone)
    return platform_config, standalone


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prefix,method,kind,deadline",
    [
        ("Report\n", "send", "text", 60),
        ("Report\n", "send_image_file", "media", 30),
        ("", "send_image_file", "media", 30),
    ],
    ids=["text", "media-after-text", "media-only"],
)
async def test_live_deadline_cancels_pending_send(
    monkeypatch, delivery_config, prefix, method, kind, deadline
):
    _, standalone = delivery_config
    started = threading.Event()
    cancelled = asyncio.Event()
    release = asyncio.Event()

    async def pending_send(*args, **kwargs):
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    adapter = SimpleNamespace(
        send=AsyncMock(return_value=SendResult(success=True)),
        send_image_file=AsyncMock(return_value=SendResult(success=True)),
        send_document=AsyncMock(return_value=SendResult(success=True)),
    )
    setattr(adapter, method, AsyncMock(side_effect=pending_send))
    submit = asyncio.run_coroutine_threadsafe
    submitted = []

    def submit_with_deadline(coro, loop):
        future = submit(coro, loop)
        submitted.append(future)
        if len(submitted) == (2 if prefix and kind == "media" else 1):
            result = future.result

            def expire(*, timeout):
                assert timeout == deadline
                assert started.wait(timeout=5)
                return result(timeout=0)

            monkeypatch.setattr(future, "result", expire)
        return future

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", submit_with_deadline)
    try:
        error = await asyncio.to_thread(
            scheduler._deliver_result,
            JOB,
            prefix + ATTACHMENTS,
            adapters={Platform.TELEGRAM: adapter},
            loop=asyncio.get_running_loop(),
        )
        assert error == (
            f"Delivery to telegram:123 is uncertain. The live adapter {kind} send timed out. "
            "Check the destination before resending."
        )
        await asyncio.wait_for(cancelled.wait(), timeout=5)
        assert submitted[-1].cancelled()
        standalone.assert_not_called()
        assert adapter.send.await_count == bool(prefix)
        assert adapter.send_image_file.await_count == (kind == "media")
        adapter.send_document.assert_not_called()
    finally:
        release.set()


@pytest.mark.asyncio
async def test_explicit_live_text_rejection_uses_standalone_sender(delivery_config):
    platform_config, standalone = delivery_config
    adapter = SimpleNamespace(
        send=AsyncMock(return_value=SendResult(success=False, error="Rejected")),
        send_image_file=AsyncMock(),
    )

    error = await asyncio.to_thread(
        scheduler._deliver_result,
        JOB,
        "Report\nMEDIA:/tmp/fixture.png",
        adapters={Platform.TELEGRAM: adapter},
        loop=asyncio.get_running_loop(),
    )

    assert error is None
    adapter.send.assert_awaited_once_with("123", "Report", metadata={"thread_id": "456"})
    adapter.send_image_file.assert_not_called()
    standalone.assert_awaited_once()
    args, kwargs = standalone.await_args
    assert args[:3] == (Platform.TELEGRAM, platform_config, "123")
    assert args[3].strip() == "Report"
    assert kwargs == {"thread_id": "456", "media_files": [("/tmp/fixture.png", False)]}
