"""Die after actual gateway dispatch; invoked with only temporary profile paths."""
import asyncio
import json
import os
import socket
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parents[4]))

from gateway.config import (
    GatewayConfig,
    Platform,
    PlatformConfig,
    SessionResetPolicy,
    StreamingConfig,
)
from gateway.run import GatewayRunner
from gateway.session import build_session_key
from tests.fixtures.app_upgrade.gateway.transport import GatewayHTTP, LocalPlatform, until
from tools import tirith_security


def no_network(*args, **kwargs):
    raise AssertionError("Gateway crash fixture forbids external sockets")


async def main():
    wire = GatewayHTTP(Path(sys.argv[1]))
    httpx.HTTPTransport.handle_request = lambda self, request: wire.handle(request)
    tirith_security.ensure_installed = lambda **kwargs: False
    real_connect = socket.socket.connect

    def connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            no_network()
        return real_connect(sock, address)

    socket.socket.connect = connect
    platform = PlatformConfig(enabled=True, token="synthetic-local-token")
    runner = GatewayRunner(GatewayConfig(
        platforms={Platform.TELEGRAM: platform},
        sessions_dir=Path(os.environ["SPARK_HOME"]) / "sessions",
        default_reset_policy=SessionResetPolicy(mode="none"),
        unauthorized_dm_behavior="ignore", streaming=StreamingConfig(enabled=False, transport="off"),
    ))
    adapter = LocalPlatform(platform)
    runner.adapters[Platform.TELEGRAM] = adapter
    adapter.set_message_handler(runner._handle_message)
    adapter.set_busy_session_handler(runner._handle_active_session_busy_message)
    adapter.set_session_store(runner.session_store)
    event = await adapter.inbound_text(wire.script["root_prompt"])
    await until(lambda: wire.root.entered.is_set() and all(
        gate.entered.is_set() for gate in wire.children.values()), "gateway accepted children")
    parent = runner._agent_cache[build_session_key(event.source)][0]
    accepted = next(c["messages"][-1]["content"] for c in wire.calls
                    if c["messages"][-1].get("tool_call_id") == "dispatch-1")
    print("GATEWAY_CRASH=" + json.dumps({"session_id": parent.session_id,
          "acceptance": json.loads(accepted), "child_calls": len(wire.child_calls()),
          "inbound": len(adapter.inbound), "sends": len(adapter.sends)}), flush=True)
    os._exit(73)


asyncio.run(main())
