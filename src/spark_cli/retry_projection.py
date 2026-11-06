"""Retry-only projection through the existing string status/replay seam.

The versioned wire value fits the existing status snapshot without adding a
controller or DB schema. Legacy runtime consumers still receive readable text.
Only a live owning turn can publish it; historical records are evidence, never
an instruction to restart a countdown or replay a request after process loss.
"""

from __future__ import annotations

import json
from typing import Any

from core.run_agent.retry_policy import RetryStatus

RETRY_STATUS_PREFIX = "spark.retry.v1:"


def publish_retry_status(session_id: str, message: str, turn: Any) -> str:
    """Commit safe retry evidence before returning the status to publish."""
    from core.spark_state import SessionDB

    if not isinstance(message, RetryStatus):
        return message
    data = dict(message.data)
    data["turn_id"] = turn.turn_id
    db = SessionDB()
    try:
        key = f"retry.status:{turn.turn_id}:{data['attempt']}:{data['next_attempt_at']}"
        db.append_session_event(session_id, "retry.status", data, idempotency_key=key)
    finally:
        db.close()
    return RETRY_STATUS_PREFIX + json.dumps(data, separators=(",", ":"))
