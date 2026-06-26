"""Small SSE event bus used by the Spark dashboard backend."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Any

_EVENT_QUEUE_SIZE = 512
_PRIORITY_EVENT_TOPICS = {
    "chat.turn_done",
    "chat.interrupted",
    "chat.session_migrated",
    "chat.approval_requested",
    "chat.approval_resolved",
}
_DROPPABLE_EVENT_TOPICS = {
    "chat.token",
    "chat.status",
    "chat.reasoning",
    "chat.tool_start",
    "chat.tool_end",
}


class WebEventBus:
    """Fan out dashboard events to SSE subscribers with bounded queues."""

    def __init__(self, logger: Any | None = None) -> None:
        self.logger = logger
        self.subscribers: set[asyncio.Queue] = set()
        self.drop_counts: dict[str, int] = {}

    def publish(
        self,
        topic: str,
        data: dict[str, Any],
        session_id: str | None = None,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        if loop is None:
            return
        envelope = {"topic": topic, "session_id": session_id, "ts": time.time(), "data": data}

        def _fanout() -> None:
            for queue in tuple(self.subscribers):
                try:
                    queue.put_nowait(envelope)
                    continue
                except asyncio.QueueFull:
                    if topic in _PRIORITY_EVENT_TOPICS and self.make_room_for_priority_event(queue):
                        try:
                            queue.put_nowait(envelope)
                            continue
                        except asyncio.QueueFull:
                            pass
                    self.record_drop(topic, session_id)
                except Exception:
                    self.subscribers.discard(queue)

        try:
            loop.call_soon_threadsafe(_fanout)
        except Exception:
            pass

    def record_drop(self, topic: str, session_id: str | None) -> None:
        key = f"{session_id or '-'}:{topic}"
        count = self.drop_counts.get(key, 0) + 1
        self.drop_counts[key] = count
        if count in {1, 10, 100} and self.logger is not None:
            self.logger.warning(
                "Dropped web SSE event due to slow subscriber session=%s topic=%s count=%s",
                session_id,
                topic,
                count,
            )

    def make_room_for_priority_event(self, queue: asyncio.Queue) -> bool:
        """Drop older low-value events so completion/control events can be delivered."""
        try:
            pending = queue._queue  # type: ignore[attr-defined]
        except Exception:
            return False
        for envelope in tuple(pending):
            if isinstance(envelope, dict) and envelope.get("topic") in _DROPPABLE_EVENT_TOPICS:
                try:
                    pending.remove(envelope)
                    self.record_drop(
                        str(envelope.get("topic") or "unknown"),
                        envelope.get("session_id"),
                    )
                    return True
                except ValueError:
                    return not queue.full()
        return not queue.full()

    @staticmethod
    def topic_allowed(topic: str, prefixes: tuple[str, ...]) -> bool:
        if not prefixes:
            return True
        return any(topic == prefix or topic.startswith(prefix + ".") for prefix in prefixes)

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=_EVENT_QUEUE_SIZE)
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self.subscribers.discard(queue)

    async def event_stream(
        self,
        request: Any,
        prefixes: tuple[str, ...],
    ) -> AsyncIterator[str]:
        queue = self.subscribe()
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    envelope = await asyncio.wait_for(queue.get(), timeout=30.0)
                except TimeoutError:
                    yield "event: ping\ndata: {}\n\n"
                    continue
                if not self.topic_allowed(envelope.get("topic", ""), prefixes):
                    continue
                try:
                    yield f"data: {json.dumps(envelope, default=str)}\n\n"
                except Exception:
                    continue
        finally:
            self.unsubscribe(queue)
