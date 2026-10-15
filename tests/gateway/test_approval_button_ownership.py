"""Real gateway notification + Slack button handlers with local SDK I/O only."""
import asyncio
import json

import pytest

from gateway.config import Platform
from gateway.session import build_session_key
from tests.fixtures.app_upgrade.gateway.transport import Gate, LocalPlatform, until
from tests.gateway.test_approval_ownership import approval_hooks as approval_hooks
from tests.gateway.test_async_delegation_delivery import gateway as gateway
from tests.gateway.test_async_delegation_delivery import idle
from tests.gateway.test_slack_approval_buttons import _make_adapter

pytestmark = [pytest.mark.serial, pytest.mark.asyncio]


class SlackWire:
    """The only Slack boundary: record local SDK sends/edits, never connect."""
    def __init__(self):
        self.posts = []
        self.edits = []
        self.delay_first = False
        self.release_first = asyncio.Event()

    async def chat_postMessage(self, **kwargs):
        message = {"ts": f"{len(self.posts) + 1}.000", **kwargs}
        self.posts.append(message)
        if self.delay_first and len(self.posts) == 1:
            await self.release_first.wait()
        return {"ts": message["ts"]}

    async def chat_update(self, **kwargs):
        self.edits.append(kwargs)
        return {"ts": kwargs["ts"]}


@pytest.mark.parametrize("delayed_send", [False, True])
async def test_cancelled_slack_button_cannot_approve_replacement_gateway_command(gateway, approval_hooks, monkeypatch, delayed_send):
    from tools import approval

    g = gateway
    wire = SlackWire()
    wire.delay_first = delayed_send
    slack = _make_adapter()
    slack._channel_team["fixture-parent"] = "T1"
    slack._team_clients["T1"] = wire
    monkeypatch.setenv("SLACK_ALLOWED_USERS", "fixture-owner")

    class LocalSlackButtons(LocalPlatform):
        async def send_exec_approval(self, **kwargs):
            # Preserve actual GatewayRunner notification arguments all the way
            # into the real Slack sender; only the SDK transport is synthetic.
            return await slack.send_exec_approval(**kwargs)

    def adapter():
        local = LocalSlackButtons(g.adapter.config)
        local.set_message_handler(g.runner._handle_message)
        local.set_busy_session_handler(g.runner._handle_active_session_busy_message)
        local.set_session_store(g.runner.session_store)
        g.runner.adapters[Platform.TELEGRAM] = local
        return local

    old_adapter = adapter()
    g.adapter = old_adapter
    after = {"GATEWAY: button A": Gate(), "GATEWAY: button B": Gate()}
    commands = {"GATEWAY: button A": "rm -rf /synthetic-never-executed-A",
                "GATEWAY: button B": "chmod 777 /synthetic-never-executed-B"}
    decisions = {}

    def before_llm(**kwargs):
        message = kwargs["user_message"]
        if message in commands:
            decisions[message] = approval.check_all_command_guards(commands[message], "local")
            after[message].wait()

    approval_hooks.register_hook("pre_llm_call", before_llm)
    new_adapter = None
    try:
        event = await old_adapter.inbound_text("GATEWAY: button A")
        key = build_session_key(event.source)
        await until(lambda: len(wire.posts) == 1, "old Slack send entered")
        if not delayed_send:
            await until(lambda: slack._approval_resolved.get(wire.posts[0]["ts"]) is False, "actual old Slack prompt sent")
        old_prompt = wire.posts[0]
        old_button = old_prompt["blocks"][1]["elements"][0]
        await old_adapter.inbound_text("/stop")
        assert not approval.has_blocking_approval(key)
        new_adapter = adapter()
        await new_adapter.inbound_text("GATEWAY: button B")
        await until(lambda: len(wire.posts) == 2 and approval.has_blocking_approval(key), "different B command queued and notified")
        wire.release_first.set()
        await until(lambda: slack._approval_resolved.get(old_prompt["ts"]) is False, "old send completes even if cancelled")
        await until(after["GATEWAY: button A"].entered.is_set, "Stop cancels A approval")
        assert decisions["GATEWAY: button A"]["approved"] is False
        body = {"message": old_prompt, "channel": {"id": "fixture-parent"},
                "user": {"name": "synthetic owner", "id": "fixture-owner"}}

        async def ack():
            pass

        await slack._handle_approval_action(ack, body, old_button)
        await until(lambda: decisions.get("GATEWAY: button B") or approval.has_blocking_approval(key), "stale click outcome")
        print("STALE_BUTTON_PROOF " + json.dumps({
            "replacement_still_waiting": approval.has_blocking_approval(key),
            "replacement_decision": decisions.get("GATEWAY: button B"),
            "old_prompt_label": wire.edits[-1]["text"] if wire.edits else "",
        }, sort_keys=True))
        assert approval.has_blocking_approval(key), "A's stale button resolved B's different command"
        assert "GATEWAY: button B" not in decisions
        assert wire.edits and "Approved" not in wire.edits[-1]["text"]
        # The correct replacement button still resolves exactly its own command.
        new_prompt = wire.posts[1]
        await slack._handle_approval_action(ack, {**body, "message": new_prompt}, new_prompt["blocks"][1]["elements"][0])
        await until(after["GATEWAY: button B"].entered.is_set, "B's own button resolves B")
        assert decisions["GATEWAY: button B"]["user_approved"] is True
        assert approval.resolve_gateway_approval(key, "once") == 0
    finally:
        wire.release_first.set()
        for gate in after.values():
            gate.release.set()
        if new_adapter:
            await new_adapter.inbound_text("/stop")
            await idle(new_adapter)
        await idle(old_adapter)
