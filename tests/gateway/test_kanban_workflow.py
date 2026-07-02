"""Tests for gateway-side Kanban notification and wake workflow."""

from __future__ import annotations

import pytest


class FakeAdapter:
    def __init__(self):
        self.sent = []
        self.handled = []

    async def send(self, chat_id, content, metadata=None):
        self.sent.append((chat_id, content, metadata))
        return {"message_id": f"sent-{len(self.sent)}"}

    async def handle_message(self, event):
        self.handled.append(event)


def _gateway_config():
    from gateway.config import GatewayConfig, HomeChannel, Platform, PlatformConfig

    return GatewayConfig(
        platforms={
            Platform.TELEGRAM: PlatformConfig(
                enabled=True,
                token="token",
                home_channel=HomeChannel(
                    platform=Platform.TELEGRAM,
                    chat_id="home-chat",
                    name="Home",
                ),
            )
        }
    )


def _creator_source(chat_id: str = "creator-chat"):
    return {
        "platform": "telegram",
        "chat_id": chat_id,
        "chat_type": "dm",
        "user_id": "creator",
        "user_name": "Creator",
    }


@pytest.mark.asyncio
async def test_kanban_workflow_notifies_owner_once_per_status_and_comment():
    from core import kanban_db as kb
    from gateway.config import Platform
    from gateway.delivery import DeliveryRouter
    from gateway.kanban_workflow import run_workflow_tick

    adapter = FakeAdapter()
    config = _gateway_config()
    adapters = {Platform.TELEGRAM: adapter}
    router = DeliveryRouter(config, adapters)
    task = kb.create_task(
        title="Notify owner",
        owner_platform="telegram",
        owner_channel="owner-chat",
        notify_on_changes=True,
    )
    kb.patch_task(task["id"], status="ready", actor="Owner")
    kb.add_comment(task["id"], "Please review", "Reviewer")

    result = await run_workflow_tick(
        gateway_config=config,
        adapters=adapters,
        delivery_router=router,
        kanban_config={"workflow_in_gateway": True},
    )
    second = await run_workflow_tick(
        gateway_config=config,
        adapters=adapters,
        delivery_router=router,
        kanban_config={"workflow_in_gateway": True},
    )

    assert result["processed"] == 2
    assert result["notified"] == 2
    assert second["processed"] == 0
    assert len(adapter.sent) == 2
    assert adapter.sent[0][0] == "owner-chat"
    assert "Status: todo -> ready" in adapter.sent[0][1]
    assert "Comment from Reviewer: Please review" in adapter.sent[1][1]


@pytest.mark.asyncio
async def test_kanban_workflow_uses_home_channel_and_profile_local_cursor():
    from core import kanban_db as kb
    from core.spark_constants import get_spark_home
    from gateway.config import Platform
    from gateway.delivery import DeliveryRouter
    from gateway.kanban_workflow import run_workflow_tick

    adapter = FakeAdapter()
    config = _gateway_config()
    adapters = {Platform.TELEGRAM: adapter}
    router = DeliveryRouter(config, adapters)
    task = kb.create_task(
        title="Fallback owner",
        owner_platform="telegram",
        notify_on_changes=True,
    )
    kb.patch_task(task["id"], status="ready")

    result = await run_workflow_tick(
        gateway_config=config,
        adapters=adapters,
        delivery_router=router,
        kanban_config={"workflow_in_gateway": True},
    )

    assert result["notified"] == 1
    assert adapter.sent[0][0] == "home-chat"
    assert (get_spark_home() / "kanban_workflow_cursor.json").exists()


@pytest.mark.asyncio
async def test_kanban_workflow_wakes_creator_session_when_origin_differs():
    from core import kanban_db as kb
    from gateway.config import Platform
    from gateway.delivery import DeliveryRouter
    from gateway.kanban_workflow import run_workflow_tick

    adapter = FakeAdapter()
    config = _gateway_config()
    adapters = {Platform.TELEGRAM: adapter}
    router = DeliveryRouter(config, adapters)
    task = kb.create_task(
        title="Wake creator",
        creator_session_key="agent:main:telegram:dm:creator-chat",
        creator_session_source=_creator_source(),
        wake_on_changes=True,
    )
    kb.patch_task(
        task["id"],
        status="ready",
        actor="Reviewer",
        origin_session_key="agent:main:telegram:dm:reviewer-chat",
    )

    result = await run_workflow_tick(
        gateway_config=config,
        adapters=adapters,
        delivery_router=router,
        kanban_config={"workflow_in_gateway": True},
    )

    assert result["woke"] == 1
    assert len(adapter.handled) == 1
    wake_event = adapter.handled[0]
    assert wake_event.internal is True
    assert wake_event.source.chat_id == "creator-chat"
    assert "[Kanban wake]" in wake_event.text


@pytest.mark.asyncio
async def test_kanban_workflow_suppresses_self_wake_loop():
    from core import kanban_db as kb
    from gateway.config import Platform
    from gateway.delivery import DeliveryRouter
    from gateway.kanban_workflow import run_workflow_tick

    adapter = FakeAdapter()
    config = _gateway_config()
    adapters = {Platform.TELEGRAM: adapter}
    router = DeliveryRouter(config, adapters)
    creator_key = "agent:main:telegram:dm:creator-chat"
    task = kb.create_task(
        title="No loop",
        creator_session_key=creator_key,
        creator_session_source=_creator_source(),
        wake_on_changes=True,
    )
    kb.patch_task(
        task["id"],
        status="ready",
        actor="Creator",
        origin_session_key=creator_key,
    )

    result = await run_workflow_tick(
        gateway_config=config,
        adapters=adapters,
        delivery_router=router,
        kanban_config={"wake_creator_on_changes": True},
    )

    assert result["woke"] == 0
    assert adapter.handled == []
