"""Bounded admission and worker-owned reads for web chat preparation.

Admission covers both queued and running preparation, including a background
handoff after durable acceptance. Cancelling an HTTP waiter does not free a slot
while its SQLite/client worker is still running.
"""

from __future__ import annotations

import asyncio
import threading
import time
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from typing import Any

from fastapi import HTTPException

from core.async_runtime import get_async_runtime


@dataclass
class _Admission:
    pool: ChatPreparationPool
    references: int = 1
    claimed: tuple | None = None

    def retain(self):
        with self.pool.lock:
            self.references += 1

    def release(self):
        with self.pool.lock:
            self.references -= 1
            if not self.references:
                self.pool.pending -= 1


class ChatPreparationPool:
    """Cheap non-waiting admission, using the existing runtime worker pool."""

    def __init__(self, capacity: int = 8, runtime=get_async_runtime):
        self.runtime = runtime
        self.capacity = capacity
        self.pending = 0
        self.lock = threading.Lock()
        self.current: ContextVar[_Admission | None] = ContextVar("chat_preparation", default=None)
        self.claims: dict[tuple, list] = {}
        self.samples: list[dict[str, Any]] = []

    def admitted(self, handler):
        @wraps(handler)
        async def wrapped(*args, **kwargs):
            with self.lock:
                if self.pending >= self.capacity:
                    raise HTTPException(
                        503,
                        "Chat preparation is busy. Please try again shortly.",
                        headers={"Retry-After": "1"},
                    )
                self.pending += 1
            admission = _Admission(self)
            token = self.current.set(admission)
            try:
                return await handler(*args, **kwargs)
            finally:
                if admission.claimed:
                    self._release_claim(admission.claimed)
                self.current.reset(token)
                admission.release()

        return wrapped

    def _release_claim(self, key):
        entry = self.claims[key]
        entry[0].release()
        entry[1] -= 1
        if not entry[1]:
            del self.claims[key]

    async def claim(self, session_id: str):
        admission = self.current.get()
        assert admission is not None
        if admission.claimed is not None:
            self._release_claim(admission.claimed)
            admission.claimed = None
        key = (asyncio.get_running_loop(), session_id)
        entry = self.claims.setdefault(key, [asyncio.Lock(), 0])
        entry[1] += 1
        try:
            await entry[0].acquire()
        except BaseException:
            entry[1] -= 1
            if not entry[1]:
                del self.claims[key]
            raise
        admission.claimed = key

    async def load_session(self, session_id: str):
        # Compression may finish while a request waits for the session claim.
        # Claim the authoritative leaf, then verify it before accepting work.
        for _ in range(4):
            preparation = await self.run(load_chat_preparation, session_id)
            await self.claim(preparation.session_id)
            verified = await self.run(load_chat_preparation, preparation.session_id)
            if verified.session_id == preparation.session_id:
                return verified
            session_id = verified.session_id
        raise HTTPException(409, "Conversation changed during preparation. Please try again.")

    def handoff_claim(self, future):
        """Keep a warm worker serialized with sends after its HTTP reply."""
        admission = self.current.get()
        assert admission is not None and admission.claimed is not None
        key = admission.claimed
        admission.claimed = None
        loop = asyncio.get_running_loop()
        future.add_done_callback(lambda _: loop.call_soon_threadsafe(self._release_claim, key))

    def start(self, fn, /, *args, **kwargs):
        admission = self.current.get()
        if admission is None:
            raise RuntimeError("Chat preparation requires admission")
        admission.retain()
        queued = time.monotonic()

        def work():
            started = time.monotonic()
            try:
                return fn(*args, **kwargs)
            finally:
                sample = {
                    "stage": getattr(fn, "__name__", "preparation"),
                    "queue_ms": (started - queued) * 1000,
                    "work_ms": (time.monotonic() - started) * 1000,
                }
                with self.lock:
                    self.samples.append(sample)
                    del self.samples[:-128]

        try:
            future = self.runtime().submit_blocking(work)
        except Exception:
            admission.release()
            raise
        future.add_done_callback(lambda _: admission.release())
        return future

    async def run(self, fn, /, *args, **kwargs):
        return await asyncio.wrap_future(self.start(fn, *args, **kwargs))


async def await_preparation(future, cancelled: threading.Event):
    """Keep ownership until an uncancellable worker reaches its boundary."""
    waiting = asyncio.wrap_future(future)
    try:
        return await asyncio.shield(waiting)
    except asyncio.CancelledError:
        cancelled.set()
        try:
            await asyncio.shield(waiting)
        except Exception:
            pass
        raise


@dataclass(frozen=True)
class PreparedChatAgent:
    agent: Any
    history: list[dict[str, Any]] | None
    hydrated_at: float
    cached: bool


@dataclass(frozen=True)
class ChatPreparation:
    requested_session_id: str
    session_id: str
    row: dict[str, Any]
    history_count: int
    revision: Any = None

    def history(self):
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            history = db.get_messages_as_conversation(self.session_id)
            db.reopen_session(self.session_id)
            return history[: self.history_count]
        finally:
            db.close()

    def prepare_agent(self, server, message, callbacks, cancelled):
        if cancelled():
            raise InterruptedError("Chat preparation stopped")
        requested_session_id = self.requested_session_id
        selected_model = str(self.row.get("model") or "").strip()
        turn_route = server._resolve_web_turn_route(
            message,
            explicit_model=selected_model or None,
        )
        agent = server._get_web_cached_agent(self.session_id)
        conversation_history, verified_warm = server._web_agent_history_for_preparation(
            self, agent, turn_route["signature"]
        )
        history_hydrated_at = time.time()
        history_count = len(conversation_history)
        if cancelled():
            raise InterruptedError("Chat preparation stopped")
        cached_signature_matches = (
            agent is not None
            and server._web_agent_signatures.get(self.session_id) == turn_route["signature"]
        )
        server._log.info(
            "web follow-up hydrated requested=%s session=%s history_count=%s cached_agent=%s signature_match=%s",
            requested_session_id,
            self.session_id,
            history_count,
            bool(agent),
            cached_signature_matches,
        )
        if (
            agent
            and cached_signature_matches
            and (verified_warm or server._cached_web_agent_matches_history(
                self.session_id, agent, conversation_history
            ))
        ):
            if not verified_warm:
                server._hydrate_web_agent_from_history(agent, conversation_history)
            agent.stream_delta_callback = callbacks["token_callback"]
            agent.tool_start_callback = callbacks["tool_start_callback"]
            agent.tool_complete_callback = callbacks["tool_complete_callback"]
            agent.reasoning_callback = callbacks["reasoning_callback"]
            agent.status_callback = callbacks["status_callback"]
            agent.session_migrated_callback = callbacks["session_migrated_callback"]
            agent.subagent_event_callback = callbacks["subagent_event_callback"]
            agent.request_overrides = turn_route.get("request_overrides")
            conversation_history = None
        else:
            agent = server._new_web_agent(
                session_id=self.session_id,
                model=turn_route["model"],
                runtime=turn_route["runtime"],
                request_overrides=turn_route.get("request_overrides"),
                signature=turn_route["signature"],
                token_callback=callbacks["token_callback"],
                tool_start_callback=callbacks["tool_start_callback"],
                tool_complete_callback=callbacks["tool_complete_callback"],
                reasoning_callback=callbacks["reasoning_callback"],
                status_callback=callbacks["status_callback"],
                session_migrated_callback=callbacks["session_migrated_callback"],
                subagent_event_callback=callbacks["subagent_event_callback"],
            )
        server._update_web_session_model(self.session_id, turn_route["model"])
        return PreparedChatAgent(
            agent, conversation_history, history_hydrated_at, cached_signature_matches
        )


def load_chat_preparation(session_id: str) -> ChatPreparation:
    from core.spark_state import SessionDB

    db = SessionDB()
    try:
        from spark_cli.web_agent_cache import ensure_history_revisions, history_revision

        ensure_history_revisions(db)
        db._conn.execute("BEGIN")
        sid = db.resolve_session_id(session_id)
        if not sid:
            raise HTTPException(404, "Session not found")
        sid = db.resolve_latest_descendant(sid)
        row = db.get_session(sid)
        if not row:
            raise HTTPException(404, "Session not found")
        revision = history_revision(db, sid)
        return ChatPreparation(
            session_id,
            sid,
            row,
            revision.count,
            revision,
        )
    finally:
        db.close()
