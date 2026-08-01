"""Versioned, resumable state envelopes for the Spark web client.

The existing SSE topics remain available for the compatibility release.  This
module adds a small committed replay journal and a strict v1 envelope around
them.  The journal is deliberately bounded: clients outside its retention
window are told to fetch a fresh authoritative snapshot.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

WEB_STATE_SCHEMA_VERSION = 1
WEB_STATE_PROJECTION_VERSION = 1
WEB_STATE_RETENTION_SECONDS = 15 * 60
WEB_STATE_RETENTION_EVENTS = 8_192
WEB_STATE_SERVER_EPOCH = uuid.uuid4().hex


@dataclass(frozen=True)
class WebStateResume:
    events: tuple[dict[str, Any], ...]
    requires_snapshot: bool
    reason: str | None = None


def validate_web_event_envelope(value: Any) -> dict[str, Any]:
    """Validate and return a v1 envelope without importing a schema SDK."""
    if not isinstance(value, dict):
        raise ValueError("event envelope must be an object")
    required: dict[str, type[Any] | tuple[type[Any], ...]] = {
        "schema_version": int,
        "topic": str,
        "entity_id": (str, type(None)),
        "sequence": int,
        "projection_version": int,
        "timestamp": (int, float),
        "payload": dict,
        "server_epoch": str,
    }
    for field, expected in required.items():
        if field not in value or not isinstance(value[field], expected):
            raise ValueError(f"invalid web event field: {field}")
    if value["schema_version"] != WEB_STATE_SCHEMA_VERSION:
        raise ValueError("unsupported web event schema version")
    if value["projection_version"] != WEB_STATE_PROJECTION_VERSION:
        raise ValueError("unsupported web state projection version")
    if value["sequence"] < 1 or not value["topic"]:
        raise ValueError("event topic and positive sequence are required")
    sequence_start = value.get("sequence_start")
    if sequence_start is not None and (
        not isinstance(sequence_start, int)
        or sequence_start < 1
        or sequence_start > value["sequence"]
    ):
        raise ValueError("invalid web event field: sequence_start")
    return value


class WebStateJournal:
    """Thread-safe append-only replay window for committed SSE envelopes."""

    def __init__(
        self,
        *,
        max_events: int = WEB_STATE_RETENTION_EVENTS,
        retention_seconds: float = WEB_STATE_RETENTION_SECONDS,
        server_epoch: str = WEB_STATE_SERVER_EPOCH,
    ) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=max(1, max_events))
        self._retention_seconds = max(1.0, retention_seconds)
        self._server_epoch = server_epoch
        self._sequence = 0
        self._lock = threading.RLock()

    @property
    def server_epoch(self) -> str:
        return self._server_epoch

    @property
    def latest_sequence(self) -> int:
        with self._lock:
            return self._sequence

    def append(
        self,
        topic: str,
        payload: dict[str, Any],
        entity_id: str | None = None,
        *,
        timestamp: float | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self._prune(timestamp or time.time())
            self._sequence += 1
            envelope = validate_web_event_envelope(
                {
                    "schema_version": WEB_STATE_SCHEMA_VERSION,
                    "topic": topic,
                    "entity_id": entity_id,
                    "session_id": entity_id,  # compatibility for v0 consumers
                    "sequence": self._sequence,
                    "projection_version": WEB_STATE_PROJECTION_VERSION,
                    "timestamp": timestamp or time.time(),
                    "ts": timestamp or time.time(),  # compatibility
                    "payload": dict(payload),
                    "data": dict(payload),  # compatibility
                    "server_epoch": self._server_epoch,
                }
            )
            self._events.append(envelope)
            return dict(envelope)

    def resume(
        self,
        after_sequence: int,
        *,
        projection_version: int,
        server_epoch: str,
        entity_ids: Iterable[str] | None = None,
    ) -> WebStateResume:
        with self._lock:
            self._prune(time.time())
            if projection_version != WEB_STATE_PROJECTION_VERSION:
                return WebStateResume((), True, "projection_version_changed")
            if server_epoch != self._server_epoch:
                return WebStateResume((), True, "server_restarted")
            if after_sequence < 0 or after_sequence > self._sequence:
                return WebStateResume((), True, "invalid_sequence")
            oldest = self._events[0]["sequence"] if self._events else self._sequence + 1
            if after_sequence < oldest - 1:
                return WebStateResume((), True, "retention_expired")
            allowed = frozenset(entity_ids or ())
            events = tuple(
                dict(event)
                for event in self._events
                if event["sequence"] > after_sequence
                and (not allowed or event["entity_id"] is None or event["entity_id"] in allowed)
            )
            return WebStateResume(events, False)

    def reset_for_test(self) -> None:
        with self._lock:
            self._events.clear()
            self._sequence = 0

    def _prune(self, now: float) -> None:
        cutoff = now - self._retention_seconds
        while self._events and self._events[0]["timestamp"] < cutoff:
            self._events.popleft()


web_state_journal = WebStateJournal()
