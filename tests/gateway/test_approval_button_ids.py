"""Real platform send/click handlers and real approval guards; SDK I/O is local."""
import asyncio
import contextvars
import importlib.util
import json
import socket
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.fixtures.app_upgrade.gateway.transport import until
from tools import approval

KEY = "synthetic-button-session"
pytestmark = [pytest.mark.serial, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setenv("SPARK_GATEWAY_SESSION", "1")
    monkeypatch.setenv("TIRITH_ENABLED", "false")
    monkeypatch.delenv("SPARK_YOLO_MODE", raising=False)
    for platform in ("SLACK", "TELEGRAM", "DISCORD"):
        monkeypatch.setenv(f"{platform}_ALLOWED_USERS", "123")
    monkeypatch.setattr(approval, "_permanent_approved", set())
    monkeypatch.setattr(approval, "_get_approval_config", lambda: {"mode": "manual", "gateway_timeout": 3})
    connect = socket.socket.connect

    def no_external(sock, address):
        assert sock.family not in (socket.AF_INET, socket.AF_INET6), "No external sockets allowed"
        return connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", no_external)
    approval.clear_session(KEY)
    yield
    approval.unregister_gateway_notify(KEY)
    approval.clear_session(KEY)


def context(owner):
    result = contextvars.copy_context()
    result.run(approval.set_current_session_key, KEY, owner=owner)
    return result


def discord_module(monkeypatch):
    """Load application code against a minimal local optional-SDK UI boundary."""
    from tests.gateway.test_discord_send import _ensure_discord_mock
    _ensure_discord_mock()
    import discord

    class LocalView:
        def __init__(self, **kwargs):
            self.children = []

    class LocalEmbed:
        def __init__(self, **kwargs):
            self.footer = ""
            self.color = kwargs.get("color")

        def add_field(self, **kwargs):
            pass

        def set_footer(self, *, text):
            self.footer = text

    monkeypatch.setattr(discord.ui, "View", LocalView)
    monkeypatch.setattr(discord, "Embed", LocalEmbed)
    name = "gateway.platforms._approval_discord_sdk_boundary"
    path = Path(__file__).resolve().parents[2] / "src/gateway/platforms/discord.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def transport(kind, monkeypatch):
    cards, labels = [], []
    if kind == "slack":
        from tests.gateway.test_slack_approval_buttons import _make_adapter
        adapter = _make_adapter()

        async def post(**kwargs):
            card = {"ts": str(len(cards) + 1), **kwargs}
            cards.append(card)
            return {"ts": card["ts"]}

        async def edit(**kwargs):
            labels.append(kwargs["text"])

        adapter._team_clients["T1"] = SimpleNamespace(chat_postMessage=post, chat_update=edit)

        async def send(data):
            return await adapter.send_exec_approval("C1", data["command"], KEY, action_id=data.get("action_id"))

        async def click(card):
            body = {"message": card, "channel": {"id": "C1"}, "user": {"id": "123", "name": "fixture"}}
            await adapter._handle_approval_action(AsyncMock(), body, card["blocks"][1]["elements"][0])

    elif kind == "telegram":
        from gateway.platforms import telegram
        from tests.gateway.test_telegram_approval_buttons import _make_adapter
        adapter = _make_adapter()
        monkeypatch.setattr(telegram, "InlineKeyboardButton", lambda text, **kwargs: SimpleNamespace(**kwargs))
        monkeypatch.setattr(telegram, "InlineKeyboardMarkup", lambda rows: rows)

        async def post(**kwargs):
            cards.append(kwargs)
            return SimpleNamespace(message_id=len(cards))

        adapter._bot.send_message = post

        async def send(data):
            return await adapter.send_exec_approval("123", data["command"], KEY, action_id=data.get("action_id"))

        async def click(card):
            query = SimpleNamespace(data=card["reply_markup"][0][0].callback_data,
                from_user=SimpleNamespace(id=123, first_name="fixture"), answer=AsyncMock(), edit_message_text=AsyncMock())
            await adapter._handle_callback_query(SimpleNamespace(callback_query=query), None)
            labels.extend(call.kwargs["text"] for call in query.answer.call_args_list)

    elif kind == "feishu":
        from tests.gateway.test_feishu_approval_buttons import _make_adapter, _make_card_action_data
        adapter = _make_adapter()

        async def post(**kwargs):
            cards.append(json.loads(kwargs["payload"]))
            return SimpleNamespace(success=lambda: True, data=SimpleNamespace(message_id=str(len(cards))))

        async def edit(message_id, label, user_name, choice):
            labels.append(label)

        # SDK send/profile/update boundaries only; sender and callback stay real.
        monkeypatch.setattr(adapter, "_feishu_send_with_retry", post)
        monkeypatch.setattr(adapter, "_resolve_sender_profile", AsyncMock(return_value={"user_name": "fixture"}))
        monkeypatch.setattr(adapter, "_update_approval_card", edit)

        async def send(data):
            return await adapter.send_exec_approval("oc_123", data["command"], KEY, action_id=data.get("action_id"))

        async def click(card):
            value = card["elements"][1]["actions"][0]["value"]
            await adapter._handle_card_action_event(_make_card_action_data(value, token=""))

    else:
        from gateway.config import PlatformConfig
        module = discord_module(monkeypatch)
        adapter = module.DiscordAdapter(PlatformConfig(enabled=True, token="synthetic"))
        adapter._allowed_user_ids = {"123"}

        async def post(**kwargs):
            cards.append(kwargs)
            return SimpleNamespace(id=len(cards))

        adapter._client = SimpleNamespace(get_channel=lambda channel: SimpleNamespace(send=post))

        async def send(data):
            return await adapter.send_exec_approval("123", data["command"], KEY, action_id=data.get("action_id"))

        async def click(card):
            interaction = SimpleNamespace(user=SimpleNamespace(id=123, display_name="fixture"),
                message=SimpleNamespace(embeds=[card["embed"]]), response=SimpleNamespace(edit_message=AsyncMock(), send_message=AsyncMock()))
            await card["view"]._resolve(interaction, "once", module.discord.Color.green(), "Approved once")
            labels.append(card["embed"].footer)

    return SimpleNamespace(send=send, click=click, cards=cards, labels=labels)


@pytest.mark.parametrize("kind", ["slack", "telegram", "discord", "feishu"])
@pytest.mark.parametrize("scenario", ["cancelled", "parallel", "missing_id"])
async def test_buttons_resolve_only_their_original_entry(monkeypatch, kind, scenario):
    wire = transport(kind, monkeypatch)
    loop = asyncio.get_running_loop()

    def notify(data):
        result = asyncio.run_coroutine_threadsafe(wire.send(data), loop).result(3)
        assert result.success, result.error

    with ThreadPoolExecutor(max_workers=2) as pool:
        owner = approval.register_gateway_notify(KEY, notify)
        first = pool.submit(context(owner).run, approval.check_all_command_guards, "rm -rf /synthetic-A", "local")
        try:
            await until(lambda: len(wire.cards) == 1, "first platform prompt")
            if scenario == "cancelled":
                approval.unregister_gateway_notify(KEY)
                owner = approval.register_gateway_notify(KEY, notify)
            second = pool.submit(context(owner).run, approval.check_all_command_guards, "chmod 777 /synthetic-B", "local")
            await until(lambda: len(wire.cards) == 2, "second platform prompt")
            if scenario == "missing_id":
                result = await wire.send({"command": "historical prompt"})
                assert result.success
                await wire.click(wire.cards[-1])
                assert len(approval._gateway_queues[KEY]) == 2
                assert "Approved" not in wire.labels[-1]
            elif scenario == "cancelled":
                await wire.click(wire.cards[0])
                assert len(approval._gateway_queues[KEY]) == 1
                assert "Approved" not in wire.labels[-1]
            # Resolve second while first is still pending: no FIFO substitution.
            await wire.click(wire.cards[1])
            await until(second.done, "second command's own button")
            assert second.result()["user_approved"] is True
            if scenario != "cancelled":
                assert not first.done() and len(approval._gateway_queues[KEY]) == 1
                await wire.click(wire.cards[0])
                await until(first.done, "first command's own button")
                assert first.result()["user_approved"] is True
            else:
                await until(first.done, "cancelled first waiter")
                assert first.result()["approved"] is False
            assert not approval.has_blocking_approval(KEY)
            assert approval.resolve_gateway_approval(KEY, "once") == 0
        finally:
            approval.unregister_gateway_notify(KEY)
