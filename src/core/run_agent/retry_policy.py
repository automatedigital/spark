"""Cache-stable retry policy boundary for the AIAgent turn loop."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any

from agent.retry_utils import jittered_backoff


@dataclass(slots=True)
class RetryState:
    """Mutable per-call retry state kept separate from provider payloads."""

    maximum: int
    attempts: int = 0

    @property
    def exhausted(self) -> bool:
        return self.attempts >= self.maximum

    def record_failure(self) -> int:
        self.attempts += 1
        return self.attempts


__all__ = ["RetryState", "RetryBudget", "RetryStatus", "jittered_backoff", "retry_after_seconds", "wait_for_retry"]


@dataclass(slots=True)
class RetryBudget:
    """Elapsed retry envelope, independent of wall-clock changes and payloads.

    The existing three-attempt policy permits two waits capped at 120s each.
    Reuse that 240s envelope instead of inventing a shorter policy default.
    The first request is outside this budget; subsequent request time counts.
    The initial request retains its provider/watchdog timeout. In-flight
    retries share this deadline through the existing transport abort path.
    """

    seconds: float
    started: float | None = None

    def start(self) -> None:
        if self.started is None:
            self.started = time.monotonic()

    @property
    def elapsed(self) -> float:
        return max(0.0, time.monotonic() - self.started) if self.started is not None else 0.0

    @property
    def remaining(self) -> float:
        return max(0.0, self.seconds - self.elapsed)

    @property
    def exhausted(self) -> bool:
        return self.started is not None and self.remaining <= 0


class RetryStatus(str):
    """Readable legacy callback text carrying a safe structured projection."""

    data: dict[str, Any]

    def __new__(cls, data: dict[str, Any]):
        text = (
            f"Retrying: {data['reason_class'].replace('_', ' ')} "
            f"(attempt {data['attempt']}/{data['max_attempts']}) "
            f"in {data['next_delay_seconds']:.1f}s"
        )
        value = super().__new__(cls, text)
        value.data = data
        return value


def retry_after_seconds(error: Exception) -> float | None:
    """Respect numeric and HTTP-date Retry-After, including zero; reject junk."""
    headers = getattr(getattr(error, "response", None), "headers", None)
    if not headers or not hasattr(headers, "get"):
        return None
    raw = headers.get("retry-after") or headers.get("Retry-After")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (ValueError, TypeError):
        try:
            value = parsedate_to_datetime(str(raw)).timestamp() - time.time()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0.0, value) if math.isfinite(value) else None


def wait_for_retry(
    agent: Any, budget: RetryBudget, *, reason: str, attempt: int,
    max_attempts: int, delay: float,
) -> str:
    """Publish one deadline then wait interruptibly, never dispatch early.

    A Retry-After beyond the remaining envelope ends the retry rather than
    shortening the provider's requested wait. No per-second backend events.
    """
    budget.start()
    if agent._interrupt_requested:
        return "interrupted"
    if budget.exhausted or delay >= budget.remaining:
        return "exhausted"
    delay = max(0.0, delay)
    now = time.time()
    status = RetryStatus({
        "version": 1, "reason_class": reason, "attempt": attempt,
        "max_attempts": max_attempts, "next_delay_seconds": delay,
        "next_attempt_at": now + delay, "observed_at": now,
        "elapsed_seconds": budget.elapsed, "budget_seconds": budget.seconds,
        "budget_deadline_at": now + budget.remaining,
        **({"run_id": agent._root_run_id} if isinstance(getattr(agent, "_root_run_id", None), str) else {}),
    })
    agent._emit_status(status)
    end = time.monotonic() + delay
    touch_at = time.monotonic() + 30
    while True:
        if agent._interrupt_requested:
            return "interrupted"
        if budget.exhausted:
            return "exhausted"
        remaining = end - time.monotonic()
        if remaining <= 0:
            agent._emit_status("Calling model…")
            return "ready"
        time.sleep(min(0.05, remaining, budget.remaining))
        if time.monotonic() >= touch_at:
            agent._touch_activity(f"retry backoff ({attempt}/{max_attempts})")
            # Sparse liveness keeps the existing 45s web-stall detector honest.
            # Reuse the same absolute deadlines, never restart the countdown.
            agent._emit_status(status)
            touch_at = time.monotonic() + 30


class RetryBudgetExceeded(TimeoutError):
    """An in-flight retry reached its elapsed envelope."""


def retry_budget_exhausted(agent: Any) -> bool:
    budget = getattr(agent, "_active_retry_budget", None)
    return isinstance(budget, RetryBudget) and budget.exhausted


def retry_poll_timeout(agent: Any) -> float:
    budget = getattr(agent, "_active_retry_budget", None)
    return min(0.3, budget.remaining) if isinstance(budget, RetryBudget) and budget.started is not None else 0.3


def call_with_retry_budget(agent: Any, budget: RetryBudget, call: Any, *args: Any, **kwargs: Any) -> Any:
    """Scope a transport-only deadline without changing any provider arguments."""
    if budget.exhausted:
        raise RetryBudgetExceeded("Elapsed retry budget exhausted")
    previous = getattr(agent, "_active_retry_budget", None)
    agent._active_retry_budget = budget
    try:
        result = call(*args, **kwargs)
        if budget.exhausted:
            raise RetryBudgetExceeded("Elapsed retry budget exhausted")
        return result
    finally:
        agent._active_retry_budget = previous
