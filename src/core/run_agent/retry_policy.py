"""Cache-stable retry policy boundary for the AIAgent turn loop."""

from __future__ import annotations

from dataclasses import dataclass

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


__all__ = ["RetryState", "jittered_backoff"]
