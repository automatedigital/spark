"""Active web chat turn state helpers.

This module is intentionally independent of FastAPI so the dashboard backend can
exercise turn lifecycle behavior directly while ``web_server.py`` remains the
import-compatible route entrypoint.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)


@dataclass
class WebActiveTurn:
    started_at: float
    last_event_at: float
    status: str
    interrupt_requested: bool
    active_agent_session_id: str | None
    phase: str
    stream_text: str = ""
    stream_revision: int = 0


_web_active_turns: dict[str, WebActiveTurn] = {}


def _turns(
    turns: MutableMapping[str, WebActiveTurn] | None = None,
) -> MutableMapping[str, WebActiveTurn]:
    return _web_active_turns if turns is None else turns


def _open_session_db(session_db_factory: Callable[[], Any] | None) -> Any:
    if session_db_factory is not None:
        return session_db_factory()

    from core.spark_state import SessionDB

    return SessionDB()


def resolve_web_turn_ids(
    session_id: str | None,
    *,
    session_db_factory: Callable[[], Any] | None = None,
) -> dict[str, str | None]:
    """Resolve a user-facing session id to the latest active conversation leaf."""
    if not session_id:
        return {"requested": session_id, "resolved": session_id, "latest": session_id}
    try:
        db = _open_session_db(session_db_factory)
        try:
            resolved = db.resolve_session_id(session_id) or session_id
            latest = db.resolve_latest_descendant(resolved) if resolved else resolved
            return {"requested": session_id, "resolved": resolved, "latest": latest or resolved}
        finally:
            close = getattr(db, "close", None)
            if close:
                close()
    except Exception:
        _log.debug("web turn id resolution failed session=%s", session_id, exc_info=True)
        return {"requested": session_id, "resolved": session_id, "latest": session_id}


def web_turn_candidates(
    session_id: str | None,
    *,
    session_db_factory: Callable[[], Any] | None = None,
) -> set[str]:
    ids = resolve_web_turn_ids(session_id, session_db_factory=session_db_factory)
    return {str(v) for v in ids.values() if v}


def web_turn_key(
    session_id: str,
    *,
    session_db_factory: Callable[[], Any] | None = None,
) -> str:
    ids = resolve_web_turn_ids(session_id, session_db_factory=session_db_factory)
    return str(ids.get("latest") or ids.get("resolved") or session_id)


def mark_web_turn_active(
    session_id: str,
    *,
    status: str = "Starting…",
    phase: str = "starting",
    active_agent_session_id: str | None = None,
    turns: MutableMapping[str, WebActiveTurn] | None = None,
    session_db_factory: Callable[[], Any] | None = None,
    clock: Callable[[], float] = time.time,
) -> WebActiveTurn:
    key = web_turn_key(session_id, session_db_factory=session_db_factory)
    now = clock()
    turn = WebActiveTurn(
        started_at=now,
        last_event_at=now,
        status=status,
        interrupt_requested=False,
        active_agent_session_id=active_agent_session_id,
        phase=phase,
    )
    _turns(turns)[key] = turn
    return turn


def touch_web_turn(
    session_id: str | None,
    *,
    status: str | None = None,
    phase: str | None = None,
    interrupt_requested: bool | None = None,
    active_agent_session_id: str | None = None,
    turns: MutableMapping[str, WebActiveTurn] | None = None,
    session_db_factory: Callable[[], Any] | None = None,
    clock: Callable[[], float] = time.time,
) -> None:
    if not session_id:
        return
    active_turns = _turns(turns)
    for candidate in web_turn_candidates(session_id, session_db_factory=session_db_factory):
        turn = active_turns.get(candidate)
        if not turn:
            continue
        turn.last_event_at = clock()
        if status is not None:
            turn.status = status
        if phase is not None:
            turn.phase = phase
        if interrupt_requested is not None:
            turn.interrupt_requested = interrupt_requested
        if active_agent_session_id is not None:
            turn.active_agent_session_id = active_agent_session_id
        return


def append_web_turn_token(
    session_id: str | None,
    token: str,
    *,
    turns: MutableMapping[str, WebActiveTurn] | None = None,
    session_db_factory: Callable[[], Any] | None = None,
    clock: Callable[[], float] = time.time,
) -> None:
    if not session_id or not token:
        return
    active_turns = _turns(turns)
    for candidate in web_turn_candidates(session_id, session_db_factory=session_db_factory):
        turn = active_turns.get(candidate)
        if not turn:
            continue
        turn.last_event_at = clock()
        turn.phase = "streaming"
        turn.stream_text += token
        turn.stream_revision += 1
        return


def clear_web_turn(
    session_id: str,
    *,
    turns: MutableMapping[str, WebActiveTurn] | None = None,
    session_db_factory: Callable[[], Any] | None = None,
) -> None:
    active_turns = _turns(turns)
    for candidate in web_turn_candidates(session_id, session_db_factory=session_db_factory):
        active_turns.pop(candidate, None)


def get_web_turn(
    session_id: str,
    *,
    turns: MutableMapping[str, WebActiveTurn] | None = None,
    session_db_factory: Callable[[], Any] | None = None,
) -> tuple[str | None, WebActiveTurn | None]:
    active_turns = _turns(turns)
    for candidate in web_turn_candidates(session_id, session_db_factory=session_db_factory):
        turn = active_turns.get(candidate)
        if turn:
            return candidate, turn
    return None, None


def is_web_turn_active(
    session_id: str | None,
    *,
    turns: MutableMapping[str, WebActiveTurn] | None = None,
    session_db_factory: Callable[[], Any] | None = None,
) -> bool:
    if not session_id:
        return False
    return get_web_turn(session_id, turns=turns, session_db_factory=session_db_factory)[1] is not None


def migrate_web_turn(
    old_id: str,
    new_id: str,
    *,
    status: str,
    phase: str = "streaming",
    active_agent_session_id: str | None = None,
    turns: MutableMapping[str, WebActiveTurn] | None = None,
    session_db_factory: Callable[[], Any] | None = None,
    clock: Callable[[], float] = time.time,
) -> tuple[str | None, WebActiveTurn | None]:
    """Move an active turn record when context compression changes session ids."""
    active_turns = _turns(turns)
    old_key, turn = get_web_turn(
        old_id,
        turns=active_turns,
        session_db_factory=session_db_factory,
    )
    if old_key and turn:
        active_turns.pop(old_key, None)
        turn.last_event_at = clock()
        turn.phase = phase
        turn.status = status
        turn.active_agent_session_id = active_agent_session_id or new_id
        active_turns[new_id] = turn
    return old_key, turn


def get_web_agent_for_turn(
    session_id: str,
    agents: Mapping[str, Any],
    *,
    turns: MutableMapping[str, WebActiveTurn] | None = None,
    session_db_factory: Callable[[], Any] | None = None,
) -> tuple[str | None, Any]:
    ids = resolve_web_turn_ids(session_id, session_db_factory=session_db_factory)
    candidates = [
        ids.get("latest"),
        ids.get("resolved"),
        ids.get("requested"),
    ]
    for candidate in candidates:
        if candidate and candidate in agents:
            return candidate, agents[candidate]
    _, turn = get_web_turn(session_id, turns=turns, session_db_factory=session_db_factory)
    if turn and turn.active_agent_session_id and turn.active_agent_session_id in agents:
        return turn.active_agent_session_id, agents[turn.active_agent_session_id]
    return None, None
