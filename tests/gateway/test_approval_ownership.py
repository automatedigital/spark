"""Approval ownership through real adapter/runner/AIAgent/plugin/guard APIs.

The independent /tmp/spark-gateway-ownership-review/test_approval_overlap.py
proved the original failure (1 passed in 11.21s). Keep its overlap ordering,
then require the replacement to survive and accept an actual inbound approval.
Only synthetic HTTP/platform transport is used; commands are never executed.
"""
import json
import threading
from dataclasses import replace

import pytest

from gateway.session import build_session_key
from tests.fixtures.app_upgrade.gateway.transport import Gate, until
from tests.gateway.test_async_delegation_delivery import deliveries, idle
from tests.gateway.test_async_delegation_delivery import gateway as gateway
from tests.gateway.test_stop_ownership import replace_adapter

pytestmark = [pytest.mark.serial, pytest.mark.asyncio]
COMMAND = "rm -rf /synthetic-never-executed"


@pytest.fixture
def approval_hooks(monkeypatch):
    from spark_cli import plugins
    from tools import approval

    monkeypatch.setenv("SPARK_GATEWAY_SESSION", "1")
    monkeypatch.setenv("TIRITH_ENABLED", "false")
    monkeypatch.delenv("SPARK_YOLO_MODE", raising=False)
    monkeypatch.setattr(approval, "_permanent_approved", set())
    manager = plugins.PluginManager()
    context = plugins.PluginContext(plugins.PluginManifest(name="synthetic-approval-ownership"), manager)
    monkeypatch.setattr(plugins, "_plugin_manager", manager)
    return context


async def test_old_exit_preserves_replacement_approval_until_actual_user_choice(gateway, approval_hooks):
    from tools import approval

    g = gateway
    old, new = "GATEWAY: review old", "GATEWAY: review replacement"
    old_gate, after_approval_gate = Gate(), Gate()
    decision = {}

    def before_llm(**kwargs):
        if kwargs["user_message"] == old:
            old_gate.wait()
        elif kwargs["user_message"] == new:
            decision.update(approval.check_all_command_guards(COMMAND, "local"))
            after_approval_gate.wait()

    approval_hooks.register_hook("pre_llm_call", before_llm)
    replacement = None
    try:
        event = await g.adapter.inbound_text(old)
        await until(old_gate.entered.is_set, "old pre_llm hook")
        key = build_session_key(event.source)
        old_parent = g.runner._agent_cache[key][0]
        await until(lambda: g.runner._running_agents.get(key) is old_parent, "old runtime tracking")
        await g.adapter.inbound_text("/stop")
        replacement = replace_adapter(g)
        await replacement.inbound_text(new)
        await until(lambda: approval.has_blocking_approval(key), "replacement queued approval")
        await until(lambda: any("Dangerous command requires approval" in s["content"] for s in replacement.sends), "approval notification")
        cb = approval._gateway_notify_cbs[key]
        assert g.runner._agent_cache[key][0] is not old_parent
        old_gate.release.set()
        await idle(g.adapter)
        assert approval._gateway_notify_cbs.get(key) is cb
        assert approval.has_blocking_approval(key)
        assert decision == {}
        print("OWNERSHIP_REPAIRED " + json.dumps({"callback_is_replacement": True, "blocking_approval": True, "decision": decision}))
        await replacement.inbound_text("/approve")
        await until(after_approval_gate.entered.is_set, "actual approval resolves replacement")
        assert decision["approved"] is True and decision["user_approved"] is True
        assert not approval.has_blocking_approval(key)
        assert approval.resolve_gateway_approval(key, "once") == 0
        assert approval._gateway_notify_cbs.get(key) is cb
        after_approval_gate.release.set()
        await idle(replacement)
        assert key not in approval._gateway_notify_cbs
        assert key not in approval._gateway_queues
        assert len(g.wire.parent_calls()) == 1
    finally:
        old_gate.release.set()
        after_approval_gate.release.set()
        if replacement:
            await idle(replacement)


@pytest.mark.parametrize("after_second_turn", ["continue", "stop"])
async def test_async_child_guards_survive_sequential_parent_turns_and_deliver_once(gateway, approval_hooks, after_second_turn):
    """Two ordinary roots finish while both generations of real children wait."""
    from tools import approval

    g = gateway
    g.wire.script["dispatch"]["tasks"] = [{"goal": "GATEWAY: alpha"}]
    release = threading.Event()
    entered, decisions = [], []
    records_lock = threading.Lock()

    def before_llm(**kwargs):
        if kwargs["user_message"] not in g.wire.children:
            return
        owner = approval._approval_session_key.get()[1]
        with records_lock:
            entered.append(owner)
        # Two normal parent turns can each spend five seconds draining gateway
        # streaming. Keep this authored hook bounded beyond those two drains.
        assert release.wait(25), "Sequential-turn child hook not released"
        result = {
            "safe": approval.check_all_command_guards("pwd", "local"),
            "dangerous": approval.check_all_command_guards(COMMAND, "local"),
        }
        with records_lock:
            decisions.append(result)

    approval_hooks.register_hook("pre_llm_call", before_llm)
    try:
        event = await g.adapter.inbound_text(g.wire.script["root_prompt"])
        key = build_session_key(event.source)
        await until(lambda: len(entered) == 1, "first generation paused before safe guard")
        parent = g.runner._agent_cache[key][0]
        g.wire.root.release.set()
        await idle(g.adapter)
        assert parent._active_children and key not in approval._gateway_notify_cbs
        # A second explicit request dispatches another owned generation. Neither
        # parent is stopped or overlapped; both return before the child guards.
        g.wire.script["dispatch"]["request_id"] = "gateway-dispatch-sequential-2"
        await g.adapter.inbound_text(g.wire.script["root_prompt"])
        await until(lambda: len(entered) == 2, "both generations remain live")
        await idle(g.adapter)
        assert len(set(entered)) == 2
        latest_parent = g.runner._agent_cache[key][0]
        parents = {id(agent): agent for agent in (parent, latest_parent)}
        assert latest_parent.session_id == parent.session_id
        assert sum(len(agent._active_children) for agent in parents.values()) == 2
        assert key not in approval._gateway_notify_cbs
        assert not deliveries(g.db, parent.session_id)
        if after_second_turn == "stop":
            await g.adapter.inbound_text("/stop")
            await idle(g.adapter)
        release.set()
        g.wire.release_all()
        await until(lambda: len(decisions) == 2, "all earlier child contexts check their guards")
        assert all(result["safe"]["approved"] is (after_second_turn == "continue") for result in decisions), decisions
        assert all(result["dangerous"]["approved"] is False for result in decisions)
        assert not approval.has_blocking_approval(key) and key not in approval._pending
        await until(lambda: all(not agent._active_children for agent in parents.values()), "both generations reach terminal acknowledgement")
        runs = g.db.list_subagent_runs(parent.session_id)
        assert len(runs) == 2
        if after_second_turn == "continue":
            assert all(run["status"] == "completed" for run in runs)
        else:
            assert all("cancelled" in result["safe"]["message"] for result in decisions)
        assert not deliveries(g.db, parent.session_id)
        await g.adapter.inbound_text("GATEWAY: collect sequential child outcomes")
        await idle(g.adapter)
        delivered = deliveries(g.db, parent.session_id)
        assert len(delivered) == 2
        await g.adapter.inbound_text("GATEWAY: collect again without duplicate delivery")
        await idle(g.adapter)
        assert deliveries(g.db, parent.session_id) == delivered
        assert len({job["delivered_message_id"] for job in g.db.list_async_child_jobs()}) == 2
    finally:
        release.set()
        g.wire.release_all()
        await idle(g.adapter)


@pytest.mark.parametrize("stop_path", ["inbound", "normal_dispatch"])
async def test_stop_without_replacement_cancels_pending_approval(gateway, approval_hooks, stop_path):
    from tools import approval

    decision, late = {}, {}
    after = Gate()

    def before_llm(**kwargs):
        decision.update(approval.check_all_command_guards(COMMAND, "local"))
        after.wait()
        late.update(approval.check_all_command_guards(COMMAND, "local"))

    approval_hooks.register_hook("pre_llm_call", before_llm)
    try:
        event = await gateway.adapter.inbound_text("GATEWAY: stop approval")
        key = build_session_key(event.source)
        await until(lambda: approval.has_blocking_approval(key), "old approval pending")
        if stop_path == "inbound":
            await gateway.adapter.inbound_text("/stop")
        else:
            await gateway.runner._handle_stop_command(replace(event, text="/stop"))
        await until(after.entered.is_set, "Stop cancels waiter before worker exit")
        assert decision["approved"] is False and "cancelled" in decision["message"]
        assert key not in approval._gateway_notify_cbs
        assert not approval.has_blocking_approval(key)
        after.release.set()
        await idle(gateway.adapter)
        assert late["approved"] is False and "cancelled" in late["message"]
        assert key not in approval._pending and key not in approval._gateway_queues
        assert not gateway.wire.parent_calls()
    finally:
        after.release.set()


@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_parallel_child_approvals_retain_old_owner_across_stop_and_replacement(gateway, approval_hooks, mode):
    from tools import approval

    g = gateway
    g.wire.script["dispatch"]["mode"] = mode
    children = tuple(g.wire.children)
    gates = {child: Gate() for child in children}
    decisions, late, replacement_decision = {}, {}, {}
    new = "GATEWAY: replacement beside children"
    replacement = None

    def before_llm(**kwargs):
        message = kwargs["user_message"]
        if message in children:
            decisions[message] = approval.check_all_command_guards(COMMAND, "local")
            gates[message].wait()
            late[message] = approval.check_all_command_guards(COMMAND, "local")
        elif message == new:
            replacement_decision.update(approval.check_all_command_guards(COMMAND, "local"))

    approval_hooks.register_hook("pre_llm_call", before_llm)
    try:
        event = await g.adapter.inbound_text(g.wire.script["root_prompt"])
        key = build_session_key(event.source)
        await until(lambda: len(approval._gateway_queues.get(key, [])) == 2, "two real child approvals on parent session")
        parent = g.runner._agent_cache[key][0]
        await g.adapter.inbound_text("/stop")
        await until(lambda: all(gate.entered.is_set() for gate in gates.values()), "both old child waiters cancelled")
        assert all(not result["approved"] and "cancelled" in result["message"] for result in decisions.values())
        replacement = replace_adapter(g)
        await replacement.inbound_text(new)
        await until(lambda: approval.has_blocking_approval(key), "replacement approval beside stopped children")
        cb = approval._gateway_notify_cbs[key]
        for gate in gates.values():
            gate.release.set()
        g.wire.release_all()
        await until(lambda: not parent._active_children, "old child terminal acknowledgement")
        await idle(g.adapter)
        assert len(late) == 2
        assert all(not result["approved"] and "cancelled" in result["message"] for result in late.values())
        assert approval._gateway_notify_cbs.get(key) is cb
        assert len(approval._gateway_queues[key]) == 1 and replacement_decision == {}
        await replacement.inbound_text("/approve")
        await idle(replacement)
        assert replacement_decision["approved"] is True
        assert not approval.has_blocking_approval(key)
        assert key not in approval._pending and key not in approval._gateway_notify_cbs
    finally:
        for gate in gates.values():
            gate.release.set()
        g.wire.release_all()
        if replacement:
            await idle(replacement)


@pytest.mark.parametrize("after_parent", ["normal", "stop", "next_turn"])
async def test_async_child_guard_after_normal_parent_completion(gateway, approval_hooks, after_parent):
    """An ended notification registration is distinct from a cancelled child."""
    from tools import approval

    g = gateway
    gates = {child: Gate() for child in g.wire.children}
    decisions = {}
    replacement_gate = Gate()
    replacement = None
    new = "GATEWAY: replacement while background children remain"

    def before_llm(**kwargs):
        message = kwargs["user_message"]
        if message in gates:
            gates[message].wait()
            decisions[message] = {
                "safe": approval.check_all_command_guards("pwd", "local"),
                "dangerous": approval.check_all_command_guards(COMMAND, "local"),
            }
        elif message == new:
            replacement_gate.wait()

    approval_hooks.register_hook("pre_llm_call", before_llm)
    try:
        event = await g.adapter.inbound_text(g.wire.script["root_prompt"])
        key = build_session_key(event.source)
        await until(lambda: all(gate.entered.is_set() for gate in gates.values()), "both async children paused before guard")
        parent = g.runner._agent_cache[key][0]
        g.wire.root.release.set()
        await idle(g.adapter)
        assert parent._active_children and key not in approval._gateway_notify_cbs
        if after_parent == "stop":
            await g.adapter.inbound_text("/stop")
            # Normal command dispatch runs in the adapter's background task.
            # Observe its completion before letting children check their guards.
            await idle(g.adapter)
        elif after_parent == "next_turn":
            replacement = replace_adapter(g)
            await replacement.inbound_text(new)
            await until(replacement_gate.entered.is_set, "replacement owns callback")
        for gate in gates.values():
            gate.release.set()
        g.wire.release_all()
        await until(lambda: len(decisions) == 2, "safe and dangerous child guards after parent exit")
        assert all(result["safe"]["approved"] is (after_parent != "stop") for result in decisions.values()), decisions
        assert all(result["dangerous"]["approved"] is False for result in decisions.values())
        if after_parent == "stop":
            assert all("cancelled" in result["safe"]["message"] for result in decisions.values())
        assert not approval.has_blocking_approval(key) and key not in approval._pending
        await until(lambda: not parent._active_children, "background children finished")
        if after_parent != "stop":
            assert all(run["status"] == "completed" for run in g.db.list_subagent_runs(parent.session_id))
    finally:
        for gate in gates.values():
            gate.release.set()
        replacement_gate.release.set()
        g.wire.release_all()
        if replacement:
            await idle(replacement)
