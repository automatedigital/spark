"""A tiny thread-safe in-memory TTL store for the relay.

Holds two short-lived secrets during a flow:
  - state → {pkce_verifier, instance_callback}   (~10 min, between /session and /callback)
  - ticket → tokens                               (~2 min, between /callback and /claim)

In-memory is sufficient for a single relay process. For a horizontally-scaled
deployment, swap this for Redis behind the same get/set/pop interface.
"""

from __future__ import annotations

import threading
import time
from typing import Any


class TTLStore:
    def __init__(self) -> None:
        self._data: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def set(self, key: str, value: Any, ttl: int) -> None:
        with self._lock:
            self._data[key] = (time.time() + ttl, value)

    def pop(self, key: str) -> Any | None:
        """Return and remove the value if present and unexpired, else None."""
        with self._lock:
            entry = self._data.pop(key, None)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at < time.time():
            return None
        return value

    def sweep(self) -> int:
        """Drop expired entries; return how many were removed."""
        now = time.time()
        with self._lock:
            expired = [k for k, (exp, _) in self._data.items() if exp < now]
            for k in expired:
                self._data.pop(k, None)
        return len(expired)

    def __len__(self) -> int:
        return len(self._data)
