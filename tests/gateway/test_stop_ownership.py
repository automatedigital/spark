"""Stop races through real adapter/runner/agent/SQLite, gated at plugin/HTTP I/O."""
from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from gateway.config import Platform
from gateway.run import _AGENT_PENDING_SENTINEL
from gateway.session import build_session_key
from tests.fixtures.app_upgrade.gateway.transport import Gate, LocalPlatform, until
from tests.gateway.test_async_delegation_delivery import gateway as gateway
from tests.gateway.test_async_delegation_delivery import idle, launched

pytestmark = [pytest.mark.serial, pytest.mark.asyncio]


class PreparationHook:
    """Authored async gateway extension, never a substituted gateway method."""

    def __init__(self, runner, *messages):
        self.entered = {m: asyncio.Event() for m in messages}
        self.release = {m: asyncio.Event() for m in messages}
        runner.hooks._handlers.setdefault("agent:start", []).append(self)

    async def __call__(self, event, context):
        message = context["message"]
        if message in self.entered:
            self.entered[message].set()
            await self.release[message].wait()

    def release_all(self):
        for release in self.release.values():
            release.set()


def replace_adapter(g):
    """Reconnect to the same runner while an old adapter callback winds down."""
    adapter = LocalPlatform(g.adapter.config)
    adapter.set_message_handler(g.runner._handle_message)
    adapter.set_busy_session_handler(g.runner._handle_active_session_busy_message)
    adapter.set_session_store(g.runner.session_store)
    g.runner.adapters[Platform.TELEGRAM] = adapter
    return adapter


async def drained(adapter):
    # The unfixed queued-turn path waits twice for an absent stream consumer
    # (five seconds each). Allow it to finish so evidence is an assertion,
    # rather than the shared fixture's ten-second polling deadline.
    async with asyncio.timeout(20):
        while adapter._background_tasks or adapter._active_sessions:
            await asyncio.sleep(0.01)


@pytest.mark.parametrize("stop_path", ["inbound", "normal_dispatch"])
async def test_stop_during_preparation_never_starts_inference_and_preserves_explicit_queue(gateway, stop_path):
    g = gateway
    old, new = "GATEWAY: stopped preparation", "GATEWAY: genuine follow-up"
    hook = PreparationHook(g.runner, old)
    try:
        event = await g.adapter.inbound_text(old)
        await hook.entered[old].wait()
        key = build_session_key(event.source)
        assert g.runner._running_agents[key] is _AGENT_PENDING_SENTINEL
        assert not g.wire.parent_calls()
        if stop_path == "inbound":
            await g.adapter.inbound_text("/stop")
            acknowledgement = g.adapter.sends[-1]["content"]
        else:
            # Exercise the production fallback command handler too, without
            # substituting it or reconstructing session/runtime state.
            acknowledgement = await g.runner._handle_stop_command(replace(event, text="/stop"))
        assert key not in g.runner._running_agents
        assert "Stopped" in acknowledgement
        assert not g.wire.parent_calls()  # Prompt acknowledgement precedes terminal cleanup.
        await g.adapter.inbound_text(new)
        hook.release[old].set()
        await drained(g.adapter)
        requests = g.wire.parent_calls()
        assert len(requests) == 1
        assert [m["content"] for m in requests[0]["messages"] if m["role"] == "user"] == [new]
        parent = g.runner._agent_cache[key][0]
        users = [m["content"] for m in g.db.get_messages(parent.session_id) if m["role"] == "user"]
        assert users == [new]
        assert len(g.adapter.sends) == (2 if stop_path == "inbound" else 1)
    finally:
        hook.release_all()


async def test_stopped_preparation_cannot_clear_replacement_sentinel_or_timestamp(gateway):
    g = gateway
    old, new = "GATEWAY: old preparation", "GATEWAY: replacement preparation"
    hook = PreparationHook(g.runner, old, new)
    replacement = None
    try:
        event = await g.adapter.inbound_text(old)
        await hook.entered[old].wait()
        key = build_session_key(event.source)
        await g.adapter.inbound_text("/stop")
        replacement = replace_adapter(g)
        await replacement.inbound_text(new)
        await hook.entered[new].wait()
        timestamp = g.runner._running_agents_ts[key]
        hook.release[old].set()
        await idle(g.adapter)
        assert g.runner._running_agents.get(key) is _AGENT_PENDING_SENTINEL
        assert g.runner._running_agents_ts.get(key) == timestamp
        assert not g.wire.parent_calls()
        hook.release[new].set()
        await idle(replacement)
        assert len(g.wire.parent_calls()) == 1
    finally:
        hook.release_all()
        if replacement:
            await idle(replacement)


async def test_stop_before_runtime_ack_never_reuses_live_cached_agent(gateway, monkeypatch):
    from spark_cli import plugins

    g = gateway
    old, new = "GATEWAY: old plugin gate", "GATEWAY: new plugin gate"
    gates = {old: Gate(), new: Gate()}
    manager = plugins.PluginManager()
    context = plugins.PluginContext(plugins.PluginManifest(name="synthetic-stop-race"), manager)

    def before_llm(**kwargs):
        if gate := gates.get(kwargs["user_message"]):
            gate.wait()

    context.register_hook("pre_llm_call", before_llm)
    monkeypatch.setattr(plugins, "_plugin_manager", manager)
    replacement = None
    try:
        event = await g.adapter.inbound_text(old)
        await until(gates[old].entered.is_set, "old worker plugin hook")
        key = build_session_key(event.source)
        parent = g.runner._agent_cache[key][0]
        await until(lambda: g.runner._running_agents.get(key) is parent, "old worker tracking")
        await g.adapter.inbound_text("/stop")
        assert "Stopped" in g.adapter.sends[-1]["content"]
        assert not gates[old].release.is_set()  # Still no runtime terminal acknowledgement.
        replacement = replace_adapter(g)
        await replacement.inbound_text(new)
        await until(gates[new].entered.is_set, "replacement worker plugin hook")
        newer = g.runner._agent_cache[key][0]
        assert newer is not parent, "Stop must not allow concurrent run_conversation on the same AIAgent"
        await until(lambda: g.runner._running_agents.get(key) is newer, "replacement tracking")
        timestamp = g.runner._running_agents_ts[key]
        gates[old].release.set()
        await idle(g.adapter)
        assert g.runner._running_agents.get(key) is newer
        assert g.runner._running_agents_ts.get(key) == timestamp
        assert not g.wire.parent_calls(), "Stopped plugin preparation must not lose cancellation at startup"
        gates[new].release.set()
        await idle(replacement)
        assert len(g.wire.parent_calls()) == 1
    finally:
        for gate in gates.values():
            gate.release.set()
        if replacement:
            await idle(replacement)


async def test_genuine_busy_followup_runs_once_and_reuses_finished_parent_cache(gateway):
    g = gateway
    key, parent, _runs = await launched(g)
    frozen_prompt, frozen_tools = parent._cached_system_prompt, parent.tools
    followup = "GATEWAY: actual busy follow-up"
    await g.adapter.inbound_text(followup)
    await until(lambda: parent._interrupt_requested, "genuine adapter interrupt")
    g.wire.release_all()
    await drained(g.adapter)
    assert g.runner._agent_cache[key][0] is parent
    assert parent._cached_system_prompt == frozen_prompt and parent.tools is frozen_tools
    requests = g.wire.parent_calls()
    assert len(requests) == 3  # Delegate dispatch + blocked parent + one explicit follow-up.
    assert sum(any(m.get("content") == followup for m in r["messages"]) for r in requests) == 1
    users = [m["content"] for m in g.db.get_messages(parent.session_id)
             if m["role"] == "user" and "Delivery child-result:" not in (m["content"] or "")]
    assert users == [g.wire.script["root_prompt"], followup]
    assert len(g.adapter.sends) == 1
