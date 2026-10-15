"""P03 gateway acceptance through real adapter, handler, sessions, SDK and SQLite.

Only platform I/O, HTTP I/O and the optional security-binary installer are fake.
No agent/delegation/session/delivery method is replaced or child state fabricated.
"""
from __future__ import annotations

import copy
import os
import socket
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
import yaml

from gateway.config import (
    GatewayConfig,
    Platform,
    PlatformConfig,
    SessionResetPolicy,
    StreamingConfig,
)
from gateway.session import build_session_key
from tests.fixtures.app_upgrade.gateway.transport import GatewayHTTP, LocalPlatform, until
from tools.delegate_tool import delegate_task

pytestmark = [pytest.mark.serial, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def gateway(monkeypatch, tmp_path):
    # Import after the suite's autouse profile isolation; rebind legacy cached
    # profile paths when another gateway test imported these modules earlier.
    from gateway import run

    home = Path(os.environ["SPARK_HOME"])
    wire = GatewayHTTP(tmp_path)
    runtime = {"provider": "custom", "base_url": wire.script["origin"],
               "api_key": "synthetic-no-credentials", "model": wire.script["model"]}
    config = {
        "model": {**runtime, "default": wire.script["model"], "context_length": 128000},
        "platform_toolsets": {"telegram": ["file", "delegation", "no_mcp"]},
        "compression": {"enabled": False},
        "delegation": {"async_enabled": True, "max_iterations": 4, "max_concurrent_children": 3},
        "memory": {"memory_enabled": False, "user_profile_enabled": False},
        "agent": {"tool_use_enforcement": False},
        "terminal": {"backend": "local", "cwd": str(tmp_path)},
        "display": {"tool_progress": "off", "interim_assistant_messages": False},
        "auxiliary": {"title_generation": runtime},
    }
    (home / "config.yaml").write_text(yaml.safe_dump(config))
    # CLI tests can import this process-global config during collection, before
    # this isolated profile exists. Bind the synthetic runtime config too: the
    # real delegate loader prefers CLI_CONFIG over config.yaml when populated.
    import core.cli as cli
    monkeypatch.setattr(cli, "CLI_CONFIG", config)
    for name, value in {
        "TELEGRAM_HOME_CHANNEL": "fixture-parent",
        "TELEGRAM_ALLOWED_USERS": "fixture-owner", "TELEGRAM_ALLOW_ALL_USERS": "false",
        "GATEWAY_ALLOW_ALL_USERS": "false", "GATEWAY_ALLOWED_USERS": "",
        "OPENAI_BASE_URL": wire.script["origin"], "OPENAI_API_KEY": "synthetic-no-credentials",
        "SPARK_AGENT_NOTIFY_INTERVAL": "0", "TERMINAL_CWD": str(tmp_path),
        "SPARK_HUMAN_DELAY_MODE": "off",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(run, "_spark_home", home)
    monkeypatch.setattr(run, "_config_path", home / "config.yaml")
    monkeypatch.setattr(run, "_env_path", home / ".env")
    monkeypatch.setattr("tools.tirith_security.ensure_installed", lambda **kwargs: False)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda self, request: wire.handle(request))

    def no_network(*args, **kwargs):
        raise AssertionError("Gateway fixture forbids external sockets")

    # Includes async networking; AF_UNIX event-loop/socketpair traffic is local.
    real_connect = socket.socket.connect

    def connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            no_network()
        return real_connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    runners = []

    def new_runner():
        platform = PlatformConfig(enabled=True, token="synthetic-local-token")
        runner = run.GatewayRunner(GatewayConfig(
            platforms={Platform.TELEGRAM: platform}, sessions_dir=home / "sessions",
            default_reset_policy=SessionResetPolicy(mode="none"),
            unauthorized_dm_behavior="ignore", streaming=StreamingConfig(enabled=False, transport="off"),
        ))
        adapter = LocalPlatform(platform)
        runner.adapters[Platform.TELEGRAM] = adapter
        adapter.set_message_handler(runner._handle_message)
        adapter.set_busy_session_handler(runner._handle_active_session_busy_message)
        adapter.set_session_store(runner.session_store)
        runners.append(runner)
        return runner, adapter

    runner, adapter = new_runner()
    harness = SimpleNamespace(runner=runner, adapter=adapter, wire=wire, new_runner=new_runner,
                              db=runner._session_db, home=home)
    try:
        yield harness
    finally:
        wire.release_all()
        for runner in runners:
            for parent, _signature in runner._agent_cache.values():
                parent.interrupt()
        for runner in runners:
            adapter = runner.adapters[Platform.TELEGRAM]
            await until(lambda: not adapter._background_tasks, "adapter cleanup")
            for parent, _signature in runner._agent_cache.values():
                await until(lambda: not parent._active_children, "child cleanup")
                parent.close()
            runner._session_db.close()
            if runner.session_store._db:
                runner.session_store._db.close()


def deliveries(db, sid):
    return [m for m in db.get_messages(sid) if "Delivery child-result:" in (m["content"] or "")]


async def launched(g):
    event = await g.adapter.inbound_text(g.wire.script["root_prompt"])
    await until(lambda: g.wire.root.entered.is_set() and all(
        gate.entered.is_set() for gate in g.wire.children.values()), "SDK dispatch and both file tools")
    key = build_session_key(event.source)
    parent = await until(lambda: g.runner._agent_cache.get(key, (None,))[0], "cached gateway parent")
    await until(lambda: g.runner._running_agents.get(key) is parent, "gateway active owner")
    runs = {r["task"]: r for r in g.db.list_subagent_runs(parent.session_id)}
    assert len(runs) == 2
    assert g.runner.session_store.get_or_create_session(event.source).session_id == parent.session_id
    return key, parent, runs


async def terminal(g, run, status="completed"):
    return await until(lambda: (r if (r := g.db.get_subagent_run(run["id"]))["status"] == status else None),
                       f"{run['id']} {status}")


async def idle(adapter):
    await until(lambda: not adapter._background_tasks and not adapter._active_sessions, "gateway handler idle")


@pytest.mark.parametrize("order", [("alpha", "beta"), ("beta", "alpha")])
async def test_gateway_busy_chat_switch_idle_then_explicit_delivery_once(gateway, order):
    g = gateway
    key, parent, runs = await launched(g)
    prefix = copy.deepcopy(g.wire.calls[0]["messages"])
    system, tools = parent._cached_system_prompt, copy.deepcopy(parent.tools)
    # A different real inbound session runs while the parent and children wait.
    other_event = await g.adapter.inbound_text("GATEWAY: other chat", chat_id="fixture-other")
    other_key = build_session_key(other_event.source)
    await until(lambda: any(s["chat_id"] == "fixture-other" for s in g.adapter.sends), "other chat reply")
    other = g.runner._agent_cache[other_key][0]
    assert other.session_id != parent.session_id
    for name in order:
        g.wire.children["GATEWAY: " + name].release.set()
        await terminal(g, runs["GATEWAY: " + name])
    await until(lambda: not parent._active_children, "both child workers finished")
    assert g.runner._running_agents[key] is parent
    assert not deliveries(g.db, parent.session_id)
    assert not deliveries(g.db, other.session_id)
    assert [s["chat_id"] for s in g.adapter.sends] == ["fixture-other"]
    assert parent._cached_system_prompt == system and parent.tools == tools
    assert g.wire.calls[0]["messages"] == prefix
    assert len(g.wire.child_calls()) == 4  # Two SDK requests and one real file tool per child.
    g.wire.root.release.set()
    await idle(g.adapter)
    assert len(g.adapter.sends) == 2
    assert not deliveries(g.db, parent.session_id)  # Idle completion never wakes a parent.
    assert all(j["delivered_message_id"] is None for j in g.db.list_async_child_jobs())
    await g.adapter.inbound_text("GATEWAY: explicit follow-up")
    await idle(g.adapter)
    result_messages = deliveries(g.db, parent.session_id)
    assert len(result_messages) == 2
    assert g.wire.script["children"]["GATEWAY: " + order[0]] in result_messages[0]["content"]
    delivered_ids = [j["delivered_message_id"] for j in g.db.list_async_child_jobs()]
    assert len(set(delivered_ids)) == 2 and all(delivered_ids)
    await g.adapter.inbound_text("GATEWAY: second explicit follow-up")
    await idle(g.adapter)
    assert deliveries(g.db, parent.session_id) == result_messages
    assert [j["delivered_message_id"] for j in g.db.list_async_child_jobs()] == delivered_ids
    assert len(g.adapter.inbound) == len(g.adapter.sends) == 4
    assert len(g.wire.child_calls()) == 4
    assert len(g.wire.parent_calls()) == 5  # Four explicit turns, one delegate tool round trip.
    assert parent._cached_system_prompt == system and parent.tools == tools
    assert all(s["reply_to"].startswith("inbound-") for s in g.adapter.sends)


async def test_idle_disconnected_children_wait_for_explicit_inbound_after_gateway_reconstruction(gateway):
    g = gateway
    _, parent, runs = await launched(g)
    g.wire.root.release.set()
    await idle(g.adapter)
    assert len(g.adapter.sends) == 1
    await g.adapter.disconnect()
    before = len(g.wire.calls)
    for goal, gate in g.wire.children.items():
        gate.release.set()
        await terminal(g, runs[goal])
    await until(lambda: not parent._active_children, "disconnected children cleanup")
    assert len(g.wire.calls) == before  # Completing already requested HTTP responses adds no app turn.
    assert len(g.adapter.sends) == 1
    assert not deliveries(g.db, parent.session_id)
    runner, adapter = g.new_runner()  # Fresh runner/cache/store/connections, same persisted profile.
    assert runner._agent_cache == {} and runner._running_agents == {}
    assert runner._session_db.db_path == g.db.db_path
    assert len(g.wire.calls) == before and adapter.sends == []
    await adapter.inbound_text("GATEWAY: explicit reconnect")
    await idle(adapter)
    resumed = next(iter(runner._agent_cache.values()))[0]
    assert resumed is not parent and resumed.session_id == parent.session_id
    result_messages = deliveries(g.db, parent.session_id)
    assert len(result_messages) == 2
    assert len(adapter.sends) == len(adapter.inbound) == 1
    runner2, adapter2 = g.new_runner()
    before_restart = len(g.wire.calls)
    assert adapter2.sends == [] and len(g.wire.calls) == before_restart
    await adapter2.inbound_text("GATEWAY: explicit second restart")
    await idle(adapter2)
    assert next(iter(runner2._agent_cache.values()))[0].session_id == parent.session_id
    assert deliveries(g.db, parent.session_id) == result_messages
    assert len(g.wire.child_calls()) == 4
    assert len(adapter2.sends) == 1
    assert len(g.wire.parent_calls()) == 4  # Three explicit turns, one delegate round trip.


async def test_cancel_one_real_gateway_child_leaves_sibling_and_root_running(gateway):
    import json

    g = gateway
    key, parent, runs = await launched(g)
    # This is the production child-control tool, on the parent actually owned by
    # GatewayRunner. No gateway-specific child-cancel slash command exists.
    run = runs["GATEWAY: alpha"]
    acknowledgement = json.loads(delegate_task(parent_agent=parent, mode="cancel",
        handle=run["id"], request_id="gateway-stop-one"))
    assert acknowledgement["status"] == "stopping"
    assert json.loads(delegate_task(parent_agent=parent, mode="cancel", handle=run["id"],
                                   request_id="gateway-stop-one")) == acknowledgement
    await terminal(g, run, "interrupted")
    assert g.db.get_subagent_run(runs["GATEWAY: beta"]["id"])["status"] in {"running", "working"}
    assert g.runner._running_agents[key] is parent
    assert g.adapter.sends == []
    g.wire.children["GATEWAY: alpha"].release.set()
    g.wire.children["GATEWAY: beta"].release.set()
    await terminal(g, runs["GATEWAY: beta"])
    assert g.runner._running_agents[key] is parent
    assert g.adapter.sends == [] and not deliveries(g.db, parent.session_id)
    g.wire.root.release.set()
    await idle(g.adapter)
    await g.adapter.inbound_text("GATEWAY: explicit after partial stop")
    await idle(g.adapter)
    assert len(deliveries(g.db, parent.session_id)) == 2
    assert g.db.get_subagent_run(run["id"])["status"] == "interrupted"
    assert len(g.wire.child_calls()) == 4
    assert len(g.adapter.sends) == len(g.adapter.inbound) == 2
    assert len(g.wire.parent_calls()) == 3


async def test_actual_gateway_stop_cascades_then_explicit_resume_delivers_once(gateway):
    g = gateway
    key, parent, runs = await launched(g)
    await g.adapter.inbound_text("/stop")  # Base adapter command bypass and real gateway stop handler.
    assert key not in g.runner._running_agents
    for run in runs.values():
        await terminal(g, run, "interrupted")
    assert all(j["delivered_message_id"] is None for j in g.db.list_async_child_jobs())
    g.wire.release_all()
    await idle(g.adapter)
    await until(lambda: not parent._active_children, "stopped worker convergence")
    assert {r["status"] for r in g.db.list_subagent_runs(parent.session_id)} == {"interrupted"}
    assert not deliveries(g.db, parent.session_id)
    # Any hidden continuation after /stop must be exposed by these exact counts.
    users = [m["content"] for m in g.db.get_messages(parent.session_id) if m["role"] == "user"]
    assert users == [g.wire.script["root_prompt"]]
    assert any("stopped" in s["content"].lower() for s in g.adapter.sends)
    await g.adapter.inbound_text("GATEWAY: explicit resume after stop")
    await idle(g.adapter)
    assert len(deliveries(g.db, parent.session_id)) == 2
    assert len(g.wire.child_calls()) == 4
    await g.adapter.inbound_text("GATEWAY: explicit second resume")
    await idle(g.adapter)
    assert len(deliveries(g.db, parent.session_id)) == 2


async def test_gateway_authorization_and_session_ownership_do_not_consume_other_results(gateway):
    import json

    g = gateway
    _, parent, runs = await launched(g)
    g.wire.release_all()
    for run in runs.values():
        await terminal(g, run)
    await idle(g.adapter)
    before = len(g.wire.calls)
    await g.adapter.inbound_text("GATEWAY: unauthorized", user_id="fixture-stranger")
    await idle(g.adapter)
    assert len(g.wire.calls) == before
    assert len(g.adapter.sends) == 1
    assert not deliveries(g.db, parent.session_id)
    event = await g.adapter.inbound_text("GATEWAY: independent owner", chat_id="fixture-other")
    await idle(g.adapter)
    other = g.runner._agent_cache[build_session_key(event.source)][0]
    for mode in ("status", "cancel"):
        response = json.loads(delegate_task(parent_agent=other, mode=mode,
            handle=runs["GATEWAY: alpha"]["id"], request_id="foreign-control"))
        assert "Owned child not found" in response["error"]
    assert not deliveries(g.db, parent.session_id)
    assert not deliveries(g.db, other.session_id)
    assert all(j["delivered_message_id"] is None for j in g.db.list_async_child_jobs())
    assert len(g.wire.child_calls()) == 4
    assert len(g.wire.parent_calls()) == 3  # Unauthorized inbound never starts inference.


async def test_real_gateway_process_loss_reconciles_only_on_explicit_turn_without_redispatch(gateway):
    import asyncio
    import json
    import sys

    g = gateway
    script = Path(__file__).parents[1] / "fixtures/app_upgrade/gateway/process_loss.py"
    process = await asyncio.create_subprocess_exec(sys.executable, str(script), str(g.wire.path.parent),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=dict(os.environ))
    stdout, stderr = await asyncio.wait_for(process.communicate(), 15)
    assert process.returncode == 73, stdout.decode() + stderr.decode()
    evidence = json.loads(next(line.split("=", 1)[1] for line in stdout.decode().splitlines()
                              if line.startswith("GATEWAY_CRASH=")))
    assert evidence["inbound"] == 1 and evidence["sends"] == 0 and evidence["child_calls"] == 4
    sid = evidence["session_id"]
    assert len(g.db.list_async_child_jobs()) == 2
    runner, adapter = g.new_runner()
    assert g.wire.calls == [] and adapter.sends == [] and runner._agent_cache == {}
    # Reconstructing a gateway never invokes provider/tools or invents a turn.
    assert not deliveries(g.db, sid)
    await adapter.inbound_text("GATEWAY: explicit recovery after crash")
    await idle(adapter)
    parent = next(iter(runner._agent_cache.values()))[0]
    assert parent.session_id == sid
    assert {j["state"] for j in g.db.list_async_child_jobs()} == {"uncertain"}
    result_messages = deliveries(g.db, sid)
    assert len(result_messages) == 2 and all("uncertain" in m["content"] for m in result_messages)
    assert g.wire.child_calls() == []
    assert json.loads(delegate_task(parent_agent=parent, **g.wire.script["dispatch"])) == evidence["acceptance"]
    rejected = json.loads(delegate_task(parent_agent=parent, mode="retry",
        handle=evidence["acceptance"]["handles"][0]["id"], request_id="gateway-unsafe-retry"))
    assert "uncertain effects need review" in rejected["error"]
    assert g.wire.child_calls() == [] and len(g.db.list_async_child_jobs()) == 2
    await adapter.inbound_text("GATEWAY: explicit second recovery")
    await idle(adapter)
    assert deliveries(g.db, sid) == result_messages
    assert len(adapter.sends) == len(adapter.inbound) == 2
    assert len(g.wire.calls) == 2  # One SDK request per explicit recovery event.


async def test_gateway_stop_of_idle_parent_cancels_its_background_children(gateway):
    g = gateway
    _, parent, runs = await launched(g)
    g.wire.root.release.set()
    await idle(g.adapter)
    assert parent._active_children
    assert g.runner._running_agents == {}
    # A different authorized chat's idle /stop cannot select this cached parent.
    await g.adapter.inbound_text("/stop", chat_id="fixture-other")
    await idle(g.adapter)
    assert "No active task to stop" in g.adapter.sends[-1]["content"]
    assert all(g.db.get_subagent_run(run["id"])["status"] == "working" for run in runs.values())
    await g.adapter.inbound_text("/stop")
    await idle(g.adapter)
    assert "No active task to stop" not in g.adapter.sends[-1]["content"]
    for run in runs.values():
        await terminal(g, run, "interrupted")
    assert not deliveries(g.db, parent.session_id)
    g.wire.release_all()
    await g.adapter.inbound_text("GATEWAY: explicit after idle stop")
    await idle(g.adapter)
    assert len(deliveries(g.db, parent.session_id)) == 2
    assert len(g.wire.child_calls()) == 4
