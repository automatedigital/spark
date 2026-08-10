"""Shared predicate for provider stream events.

Lives in its own module so both AIAgent and the Codex mixin can import it
without either importing the other.
"""

from __future__ import annotations


def _stream_event_is_progress(event_type) -> bool:
    """Return True when a streamed provider event represents real progress.

    Transport keep-alive / ping / heartbeat events (and untyped events) must
    NOT reset the stale-call watchdog's progress timestamp: a provider can
    keep the socket warm with pings while never producing content, which
    would mask a genuine stall indefinitely.
    """
    if not event_type:
        return False
    _et = str(event_type).lower()
    return not any(marker in _et for marker in ("ping", "keep_alive", "keep-alive", "heartbeat"))
