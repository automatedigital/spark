"""Process-local efficiency counters shared by the DB and web runtime."""

from __future__ import annotations

import os
import threading
from collections import defaultdict
from typing import Any

_lock = threading.Lock()
_counters: defaultdict[str, float] = defaultdict(float)


def detailed_enabled() -> bool:
    return os.getenv("SPARK_EFFICIENCY_METRICS", "").strip().lower() in {"1", "true", "yes", "on"}


def increment(name: str, value: int | float = 1) -> None:
    with _lock:
        _counters[name] += value


def snapshot(*, reset: bool = False) -> dict[str, Any]:
    with _lock:
        result = {key: value for key, value in sorted(_counters.items())}
        if reset:
            _counters.clear()
    return {"version": "1.0", "counters": result}


def reset() -> None:
    with _lock:
        _counters.clear()
