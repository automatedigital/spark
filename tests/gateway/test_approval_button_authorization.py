"""Caller authorization at actual adapter handlers; local SDK boundaries only."""
import socket
from types import SimpleNamespace

import pytest

from gateway.config import Platform
from gateway.run import GatewayRunner
from gateway.session import SessionSource
from tests.gateway.test_approval_button_ids import KEY, transport
from tools import approval

pytestmark = [pytest.mark.serial, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
def isolated_auth(monkeypatch):
    for name in ("GATEWAY", "SLACK", "TELEGRAM", "DISCORD", "FEISHU"):
        monkeypatch.delenv(f"{name}_ALLOWED_USERS", raising=False)
        monkeypatch.delenv(f"{name}_ALLOW_ALL_USERS", raising=False)
    monkeypatch.setenv("FEISHU_GROUP_POLICY", "open")
    connect = socket.socket.connect

    def local_only(sock, address):
        assert sock.family not in (socket.AF_INET, socket.AF_INET6), "No external sockets allowed"
        return connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", local_only)
    approval.clear_session(KEY)
    yield
    approval.unregister_gateway_notify(KEY)
    approval.clear_session(KEY)


def policy_runner():
    runner = object.__new__(GatewayRunner)
    runner.pairing_store = SimpleNamespace(is_approved=lambda platform, user: False)
    return runner


@pytest.mark.parametrize("kind", ["slack", "telegram", "discord", "feishu"])
@pytest.mark.parametrize("choice", ["once", "session", "always", "deny"])
async def test_global_policy_rejects_stranger_before_consuming_button(monkeypatch, kind, choice):
    monkeypatch.setenv("GATEWAY_ALLOWED_USERS", "123")
    runner = policy_runner()
    wire = transport(kind, monkeypatch)
    wire.adapter._allowed_user_ids = set()
    # Attach the real inbound handler as production does, with no provider work.
    wire.adapter.set_message_handler(runner._handle_message)
    wire.adapter.set_approval_authorizer(runner._is_user_authorized)
    source = SessionSource(platform=Platform(kind), chat_id="unused", user_id="stranger", chat_type="group")
    assert not runner._is_user_authorized(source)
    entry = approval._ApprovalEntry({"command": "synthetic, never executed"})
    with approval._lock:
        approval._gateway_queues[KEY] = [entry]
    await wire.send(entry.data)
    await wire.click(wire.cards[0], caller="stranger", choice=choice)
    assert not entry.event.is_set(), f"{kind} stranger bypassed gateway authorization"
    await wire.click(wire.cards[0], caller="123", choice=choice)
    assert entry.result == choice, "Unauthorized click consumed the owner's request"


async def test_feishu_group_policy_rejects_excluded_caller_before_consuming_card(monkeypatch):
    monkeypatch.setenv("FEISHU_ALLOWED_USERS", "123")
    monkeypatch.setenv("FEISHU_GROUP_POLICY", "allowlist")
    runner = policy_runner()
    wire = transport("feishu", monkeypatch)
    wire.adapter.set_message_handler(runner._handle_message)
    wire.adapter.set_approval_authorizer(runner._is_user_authorized)
    assert not wire.adapter._allow_group_message(SimpleNamespace(open_id="stranger", user_id=None), "oc_123")
    entry = approval._ApprovalEntry({"command": "synthetic, never executed"})
    with approval._lock:
        approval._gateway_queues[KEY] = [entry]
    await wire.send(entry.data)
    await wire.click(wire.cards[0], caller="stranger", token="not-consumed-by-stranger")
    assert not entry.event.is_set(), "Feishu excluded group caller resolved the approval"
    assert "not-consumed-by-stranger" not in wire.adapter._card_action_tokens
    await wire.click(wire.cards[0], caller="123", token="not-consumed-by-stranger")
    assert entry.result == "once", "Unauthorized click consumed the owner's request"


@pytest.mark.parametrize("kind", ["slack", "telegram", "discord", "feishu"])
@pytest.mark.parametrize("policy,allowed", [
    ("default_deny", False), ("platform_member", True), ("platform_excluded", False),
    ("global_member", True), ("global_excluded", False), ("platform_wildcard", True),
    ("global_wildcard", True), ("platform_open", True), ("global_open", True),
    ("global_open_with_allowlist", False), ("platform_open_with_allowlist", True),
    ("paired", True),
])
async def test_button_policy_matches_inbound_policy(monkeypatch, kind, policy, allowed):
    prefix = kind.upper()
    settings = {
        "platform_member": {f"{prefix}_ALLOWED_USERS": "123"},
        "platform_excluded": {f"{prefix}_ALLOWED_USERS": "owner"},
        "global_member": {"GATEWAY_ALLOWED_USERS": "123"},
        "global_excluded": {"GATEWAY_ALLOWED_USERS": "owner"},
        "platform_wildcard": {f"{prefix}_ALLOWED_USERS": "*"},
        "global_wildcard": {"GATEWAY_ALLOWED_USERS": "*"},
        "platform_open": {f"{prefix}_ALLOW_ALL_USERS": "true"},
        "global_open": {"GATEWAY_ALLOW_ALL_USERS": "true"},
        "global_open_with_allowlist": {"GATEWAY_ALLOW_ALL_USERS": "true", "GATEWAY_ALLOWED_USERS": "owner"},
        "platform_open_with_allowlist": {f"{prefix}_ALLOW_ALL_USERS": "true", "GATEWAY_ALLOWED_USERS": "owner"},
    }
    for name, value in settings.get(policy, {}).items():
        monkeypatch.setenv(name, value)
    wire = transport(kind, monkeypatch)
    if policy == "paired":
        wire.runner.pairing_store.is_approved = lambda platform, user: platform == kind and user == "123"
    source = SessionSource(platform=Platform(kind), chat_id="unused", user_id="123", chat_type="group")
    assert wire.runner._is_user_authorized(source) is allowed
    entry = approval._ApprovalEntry({"command": "synthetic"})
    with approval._lock:
        approval._gateway_queues[KEY] = [entry]
    assert (await wire.send(entry.data)).success
    await wire.click(wire.cards[0])
    assert entry.event.is_set() is allowed
    if not allowed:
        # Policy changes are evaluated on click, not cached at prompt creation.
        monkeypatch.setenv(f"{prefix}_ALLOW_ALL_USERS", "true")
        await wire.click(wire.cards[0])
        assert entry.result == "once"


@pytest.mark.parametrize("kind", ["slack", "telegram", "discord", "feishu"])
@pytest.mark.parametrize("invalid", ["missing_user", "missing_chat", "wrong_chat", "missing_source", "wrong_platform", "missing_policy"])
async def test_invalid_callback_context_preserves_authorized_retry(monkeypatch, kind, invalid):
    monkeypatch.setenv("GATEWAY_ALLOW_ALL_USERS", "true")
    wire = transport(kind, monkeypatch)
    entry = approval._ApprovalEntry({"command": "synthetic"})
    with approval._lock:
        approval._gateway_queues[KEY] = [entry]
    assert (await wire.send(entry.data)).success
    kwargs = {}
    def restore():
        pass
    if invalid == "missing_user":
        kwargs["caller"] = ""
    elif invalid in ("missing_chat", "wrong_chat"):
        kwargs["chat_id"] = "" if invalid == "missing_chat" else "somewhere-else"
    elif invalid == "missing_policy":
        wire.adapter._approval_authorizer = None
        def restore():
            wire.adapter.set_approval_authorizer(wire.runner._is_user_authorized)
    else:
        if kind == "slack":
            state = wire.adapter._approval_sources
            key = wire.cards[0]["ts"]
        elif kind == "discord":
            state = vars(wire.cards[0]["view"])
            key = "source"
        else:
            state = next(iter(wire.adapter._approval_state.values()))
            key = "source"
        saved = state[key]
        if invalid == "missing_source":
            state[key] = None
        else:
            from dataclasses import replace
            state[key] = replace(saved, platform=Platform.LOCAL)
        def restore():
            state[key] = saved
    await wire.click(wire.cards[0], **kwargs)
    assert not entry.event.is_set()
    restore()
    await wire.click(wire.cards[0])
    assert entry.result == "once"


@pytest.mark.parametrize("kind", ["slack", "telegram", "discord", "feishu"])
async def test_thread_approval_requires_original_destination(monkeypatch, kind):
    monkeypatch.setenv("GATEWAY_ALLOWED_USERS", "123")
    wire = transport(kind, monkeypatch)
    chat = {"slack": "C1", "telegram": "123", "discord": "123", "feishu": "oc_123"}[kind]
    source = SessionSource(platform=Platform(kind), chat_id=chat, user_id="123", chat_type="group", thread_id="456")
    entry = approval._ApprovalEntry({"command": "synthetic", "source": source, "metadata": {"thread_id": "456"}})
    with approval._lock:
        approval._gateway_queues[KEY] = [entry]
    assert (await wire.send(entry.data)).success
    bad = {"thread_id": "999"}
    good = {"thread_id": "456"}
    if kind == "discord":
        bad, good = {"chat_id": "999"}, {"chat_id": "456"}
    elif kind == "feishu":
        bad, good = {"message_id": "other-message"}, {}
    await wire.click(wire.cards[0], **bad)
    assert not entry.event.is_set()
    await wire.click(wire.cards[0], **good)
    assert entry.result == "once"


@pytest.mark.parametrize("policy,allowed", [("open", True), ("disabled", False), ("allowlist", False), ("admin_only", False), ("blacklist", True)])
async def test_feishu_reuses_group_policy_with_gateway_authorization(monkeypatch, policy, allowed):
    monkeypatch.setenv("GATEWAY_ALLOWED_USERS", "123")
    monkeypatch.setenv("FEISHU_GROUP_POLICY", policy)
    wire = transport("feishu", monkeypatch)
    entry = approval._ApprovalEntry({"command": "synthetic"})
    with approval._lock:
        approval._gateway_queues[KEY] = [entry]
    await wire.send(entry.data)
    await wire.click(wire.cards[0])
    assert entry.event.is_set() is allowed
    if not allowed:
        wire.adapter._admins = frozenset({"123"})
        await wire.click(wire.cards[0])
        assert entry.result == "once"


async def test_feishu_dm_does_not_apply_group_disabled_policy(monkeypatch):
    monkeypatch.setenv("GATEWAY_ALLOWED_USERS", "123")
    monkeypatch.setenv("FEISHU_GROUP_POLICY", "disabled")
    wire = transport("feishu", monkeypatch)
    source = SessionSource(platform=Platform.FEISHU, chat_id="oc_123", chat_type="dm")
    entry = approval._ApprovalEntry({"command": "synthetic", "source": source})
    with approval._lock:
        approval._gateway_queues[KEY] = [entry]
    await wire.send(entry.data)
    await wire.click(wire.cards[0])
    assert entry.result == "once"


@pytest.mark.parametrize("choice", ["once", "session", "always", "deny"])
@pytest.mark.parametrize("route", ["dm_direct", "dm_precedence", "dm_legacy_thread", "forum"])
async def test_telegram_approval_routes_from_inbound_builder(monkeypatch, choice, route):
    from gateway.platforms import telegram
    from gateway.platforms.base import MessageType

    monkeypatch.setenv("GATEWAY_ALLOWED_USERS", "123")
    wire = transport("telegram", monkeypatch)
    monkeypatch.setattr(telegram, "ChatType", SimpleNamespace(
        PRIVATE="private", GROUP="group", SUPERGROUP="supergroup", CHANNEL="channel"))
    monkeypatch.setattr(wire.adapter, "_get_dm_topic_info", lambda chat_id, thread_id: None)
    direct_topic = 77 if route in ("dm_direct", "dm_precedence") else None
    message_thread = None if route == "dm_direct" else 11 if route == "dm_precedence" else 77
    inbound = SimpleNamespace(
        chat=SimpleNamespace(id=123, type="supergroup" if route == "forum" else "private", title=None, full_name="fixture"),
        from_user=SimpleNamespace(id=123, full_name="owner"),
        message_thread_id=message_thread,
        direct_messages_topic=SimpleNamespace(topic_id=direct_topic),
        forum_topic_created=None, reply_to_message=None, text="synthetic", message_id=1, date=None,
    )
    source = wire.adapter._build_message_event(inbound, MessageType.TEXT).source
    assert source.thread_id == "77"
    assert source.direct_messages_topic_id == ("77" if direct_topic else None)
    assert source.chat_type == ("group" if route == "forum" else "dm")
    entry = approval._ApprovalEntry({
        "command": "synthetic", "source": source,
        "metadata": wire.adapter.source_metadata(source),
    })
    with approval._lock:
        approval._gateway_queues[KEY] = [entry]
    assert (await wire.send(entry.data)).success
    if direct_topic:
        wrong = {"thread_id": 77, "topic_id": 999}
    else:
        wrong = {"thread_id": 999, "topic_id": 77 if route == "forum" else None}
    await wire.click(wire.cards[0], choice=choice, **wrong)
    assert not entry.event.is_set()
    # Private direct topics take precedence even if message_thread_id differs
    # or is absent. Forum routing must keep the message thread authoritative.
    await wire.click(wire.cards[0], choice=choice, thread_id=message_thread,
                     topic_id=direct_topic if route != "forum" else 999)
    assert entry.result == choice, f"Matching {route} callback rejected"
    assert approval.resolve_gateway_approval(KEY, "once") == 0


@pytest.mark.parametrize("choice", ["once", "session", "always", "deny"])
async def test_feishu_per_group_rule_precedes_default_and_preserves_retry(monkeypatch, choice):
    from gateway.platforms.feishu import FeishuGroupRule

    monkeypatch.setenv("GATEWAY_ALLOWED_USERS", "123,stranger")
    wire = transport("feishu", monkeypatch)
    wire.adapter._group_rules["oc_123"] = FeishuGroupRule(policy="blacklist", blacklist={"stranger"})
    entry = approval._ApprovalEntry({"command": "synthetic"})
    with approval._lock:
        approval._gateway_queues[KEY] = [entry]
    await wire.send(entry.data)
    await wire.click(wire.cards[0], caller="stranger", choice=choice)
    assert not entry.event.is_set()
    wire.adapter._resolve_sender_profile.assert_not_awaited()
    await wire.click(wire.cards[0], choice=choice)
    assert entry.result == choice
