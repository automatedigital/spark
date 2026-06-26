"""Unit tests for the dashboard SSE event bus."""

from __future__ import annotations

import asyncio
import json


def test_web_event_bus_publishes_to_subscriber():
    from spark_cli.web_events import WebEventBus

    async def run():
        bus = WebEventBus()
        queue = bus.subscribe()
        bus.publish("chat.token", {"t": "hi"}, "sess1", loop=asyncio.get_running_loop())
        return await asyncio.wait_for(queue.get(), timeout=2.0)

    envelope = asyncio.run(run())

    assert envelope["topic"] == "chat.token"
    assert envelope["session_id"] == "sess1"
    assert envelope["data"] == {"t": "hi"}


def test_web_event_bus_priority_event_makes_room():
    from spark_cli.web_events import WebEventBus

    async def run():
        bus = WebEventBus()
        queue = asyncio.Queue(maxsize=2)
        bus.subscribers.add(queue)
        loop = asyncio.get_running_loop()
        bus.publish("chat.token", {"t": "a"}, "sess1", loop=loop)
        bus.publish("chat.token", {"t": "b"}, "sess1", loop=loop)
        bus.publish("chat.turn_done", {"ok": True}, "sess1", loop=loop)
        await asyncio.sleep(0.05)
        items = []
        while not queue.empty():
            items.append(queue.get_nowait())
        return items

    envelopes = asyncio.run(run())

    assert len(envelopes) <= 2
    assert any(envelope["topic"] == "chat.turn_done" for envelope in envelopes)


def test_web_event_bus_stream_filters_topics():
    from spark_cli.web_events import WebEventBus

    class Request:
        def __init__(self):
            self.calls = 0

        async def is_disconnected(self):
            self.calls += 1
            return self.calls > 2

    async def run():
        bus = WebEventBus()
        stream = bus.event_stream(Request(), ("sessions",))
        next_payload = asyncio.create_task(stream.__anext__())
        while not bus.subscribers:
            await asyncio.sleep(0)
        queue = next(iter(bus.subscribers))
        await queue.put({"topic": "chat.token", "session_id": "s", "ts": 1, "data": {}})
        await queue.put({"topic": "sessions.changed", "session_id": "s", "ts": 2, "data": {"ok": True}})
        payload = await asyncio.wait_for(next_payload, timeout=2.0)
        await stream.aclose()
        return payload

    payload = asyncio.run(run())

    assert json.loads(payload.removeprefix("data: ").strip())["topic"] == "sessions.changed"
