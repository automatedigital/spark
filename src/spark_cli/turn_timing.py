"""Bounded, transcript-free per-root-turn diagnostics; all spans use one clock."""
from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TurnTiming:
    clock: Callable[[], float] = field(default=time.monotonic, repr=False)
    marks: dict[str, float] = field(default_factory=dict)
    route: dict[str, Any] = field(default_factory=dict)
    tool_seconds: float = 0.0
    tool_count: int = 0
    usage: dict[str, int] | None = None

    def mark(self, name: str) -> None:
        # Fixed allowlist keeps diagnostics bounded even with arbitrary statuses.
        if name in {"accepted", "preparation_ready", "execution_queued", "execution_started", "provider_start", "first_token", "finish"} and name not in self.marks:
            self.marks[name] = self.clock()

    def select_route(self, route: dict[str, Any]) -> None:
        runtime = route.get("runtime") or {}
        for key in ("model", "role", "routing_reason"):
            value = route.get(key)
            if isinstance(value, str):
                self.route[key] = value[:500]
        decision = route.get("routing_decision")
        if isinstance(decision, dict):
            safe: dict[str, Any] = {}
            for key in ("role", "desired_role", "reason"):
                if isinstance(decision.get(key), str):
                    safe[key] = decision[key][:500]
            for key in ("signals", "scores"):
                values = decision.get(key)
                if isinstance(values, dict):
                    safe[key] = {str(k)[:80]: v for k, v in list(values.items())[:32]
                                 if isinstance(v, (bool, int)) and abs(v) < 1_000_000}
            self.route["routing_decision"] = safe
        provider = runtime.get("provider")
        if isinstance(provider, str):
            self.route["provider"] = provider[:100]

    def account(self, result: Any, iteration_start: int = 0) -> None:
        # Session totals may include earlier turns. Reuse only this execution's
        # provider accounting rows, never treat estimated or absent usage as zero.
        efficiency = result.get("efficiency") if isinstance(result, dict) else None
        rows = efficiency.get("model_iterations") if isinstance(efficiency, dict) else None
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            return
        rows = rows[iteration_start:]
        keys = ("prompt_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "reasoning_tokens")
        if rows and all(row.get("usage_source") == "provider" for row in rows):
            self.usage = {key: sum(row[key] for row in rows) for key in keys
                          if all(isinstance(row.get(key), int) and row[key] >= 0 for row in rows)}

    def summary(self) -> dict[str, Any]:
        def span(start: str, end: str) -> float | None:
            if start not in self.marks or end not in self.marks:
                return None
            value = self.marks[end] - self.marks[start]
            return round(max(0.0, value), 6) if math.isfinite(value) else None

        return {
            "version": 1, "clock": "server_monotonic", "accepted": "accepted" in self.marks,
            "seconds": {
                "preparation": span("accepted", "preparation_ready"),
                "queue": span("execution_queued", "execution_started"),
                "provider_start": span("accepted", "provider_start"),
                "first_token": span("provider_start", "first_token"),
                "accepted_to_first_token": span("accepted", "first_token"),
                "tools": round(self.tool_seconds, 6) if self.tool_count else None,
                "finish": span("accepted", "finish"),
            },
            "tool_count": self.tool_count, "usage": self.usage,
            **self.route,
        }
