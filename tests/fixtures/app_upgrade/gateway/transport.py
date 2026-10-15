"""External boundaries only: HTTP response script and local platform adapter."""
from __future__ import annotations

import asyncio
import copy
import json
import threading
from pathlib import Path

import httpx

from gateway.config import Platform
from gateway.platforms.base import BasePlatformAdapter, MessageEvent, MessageType, SendResult
from gateway.session import SessionSource

SCRIPT = Path(__file__).with_name("transport-v1.json")


class Gate:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()

    def wait(self):
        self.entered.set()
        assert self.release.wait(12), "Synthetic HTTP response gate not released"


class GatewayHTTP:
    """Below the real SDK. Child file tools, scheduler and persistence stay real."""
    def __init__(self, directory):
        self.script = json.loads(SCRIPT.read_text())
        self.path = directory / "gateway-input.txt"
        self.path.write_text(self.script["file_content"])
        self.calls = []
        self.root = Gate()
        self.children = {goal: Gate() for goal in self.script["children"]}
        self.lock = threading.Lock()

    @staticmethod
    def tool(name, arguments, identity):
        return {"content": None, "tool_calls": [{"id": identity, "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)}}]}

    def response(self, request, message, reason="stop"):
        body = {"id": "gateway-synthetic", "object": "chat.completion", "created": 1,
                "model": self.script["model"], "choices": [{"index": 0,
                "message": {"role": "assistant", **message}, "finish_reason": reason}],
                "usage": {"prompt_tokens": 80, "completion_tokens": 12, "total_tokens": 92}}
        if json.loads(request.content).get("stream"):
            delta = copy.deepcopy(message)
            if delta.get("tool_calls"):
                delta["tool_calls"] = [{"index": i, **c} for i, c in enumerate(delta["tool_calls"])]
            chunks = [
                {**body, "object": "chat.completion.chunk", "choices": [
                    {"index": 0, "delta": {"role": "assistant", **delta}, "finish_reason": None}]},
                {**body, "object": "chat.completion.chunk", "choices": [
                    {"index": 0, "delta": {}, "finish_reason": reason}]},
            ]
            content = "".join("data: " + json.dumps(c) + "\n\n" for c in chunks) + "data: [DONE]\n\n"
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=content.encode(), request=request)
        return httpx.Response(200, json=body, request=request)

    def handle(self, request):
        assert request.url.host == "gateway-replay.invalid", str(request.url)
        assert request.url.path == "/v1/chat/completions", str(request.url)
        body = json.loads(request.content)
        with self.lock:
            self.calls.append(copy.deepcopy(body))
        users = [m["content"] for m in body["messages"] if m["role"] == "user"]
        if users[0] in self.children:
            goal = users[0]
            if body["messages"][-1]["role"] != "tool":
                return self.response(request, self.tool("read_file", {"path": str(self.path)}, "read-1"), "tool_calls")
            assert self.script["file_content"].strip() in body["messages"][-1]["content"]
            self.children[goal].wait()
            return self.response(request, {"content": self.script["children"][goal]})
        # Title generation is also synthetic and separately counted.
        if any("Generate a short, descriptive title" in str(m.get("content")) for m in body["messages"]):
            return self.response(request, {"content": "Synthetic gateway replay"})
        if users[-1] == self.script["root_prompt"] and body["messages"][-1]["role"] != "tool":
            return self.response(request, self.tool("delegate_task", self.script["dispatch"], "dispatch-1"), "tool_calls")
        if body["messages"][-1].get("tool_call_id") == "dispatch-1":
            self.root.wait()
        return self.response(request, {"content": self.script["root_result"]})

    def release_all(self):
        self.root.release.set()
        for gate in self.children.values():
            gate.release.set()

    def child_calls(self):
        return [c for c in self.calls if next((m["content"] for m in c["messages"]
                if m["role"] == "user"), None) in self.children]

    def parent_calls(self):
        return [c for c in self.calls if c not in self.child_calls() and not any(
            "Generate a short, descriptive title" in str(m.get("content")) for m in c["messages"])]


class LocalPlatform(BasePlatformAdapter):
    """Real base inbound processing/retry/delivery, no messaging service connection."""
    def __init__(self, config):
        super().__init__(config, Platform.TELEGRAM)
        self.sends = []
        self.inbound = []
        self.connected = True

    async def connect(self):
        self.connected = True
        return True

    async def disconnect(self):
        self.connected = False

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        assert chat_id.startswith("fixture-"), "No external recipient permitted"
        assert self.connected, "Unexpected send while disconnected"
        self.sends.append({"chat_id": chat_id, "content": content, "reply_to": reply_to,
                           "metadata": copy.deepcopy(metadata)})
        return SendResult(success=True, message_id=f"local-{len(self.sends)}")

    async def get_chat_info(self, chat_id):
        return {"name": "Synthetic local chat", "type": "dm"}

    async def inbound_text(self, text, chat_id="fixture-parent", user_id="fixture-owner"):
        event = MessageEvent(text=text, message_type=MessageType.TEXT,
            source=SessionSource(platform=Platform.TELEGRAM, chat_id=chat_id,
                                 chat_type="dm", user_id=user_id),
            message_id=f"inbound-{len(self.inbound) + 1}")
        self.inbound.append(event)
        await self.handle_message(event)
        return event


async def until(predicate, description):
    async with asyncio.timeout(10):
        while True:
            result = predicate()
            if result:
                return result
            await asyncio.sleep(0.01)
