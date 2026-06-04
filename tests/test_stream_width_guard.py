"""The per-token width guard must exactly match the real display-width check."""

from __future__ import annotations

import random
import string

from prompt_toolkit.utils import get_cwidth

from core.cli.streaming_mixin import _StreamingMixin


class _Probe(_StreamingMixin):
    @staticmethod
    def _status_bar_display_width(text: str) -> int:
        return get_cwidth(text or "")


def test_guard_matches_real_width_check():
    probe = _Probe()
    alphabet = string.ascii_letters + "  汉字🙂"  # mix narrow, wide, emoji
    for _ in range(5000):
        n = random.randint(0, 200)
        buf = "".join(random.choice(alphabet) for _ in range(n))
        max_width = random.randint(5, 150)
        assert probe._buf_width_exceeds(buf, max_width) == (get_cwidth(buf) > max_width)


def test_short_buffers_skip_expensive_scan():
    calls = {"n": 0}

    class Counting(_StreamingMixin):
        @staticmethod
        def _status_bar_display_width(text: str) -> int:
            calls["n"] += 1
            return get_cwidth(text or "")

    probe = Counting()
    # 2*len <= max_width must short-circuit without calling get_cwidth.
    assert probe._buf_width_exceeds("a" * 30, 120) is False
    assert calls["n"] == 0
    # Longer buffer must fall through to the real measurement.
    probe._buf_width_exceeds("a" * 100, 120)
    assert calls["n"] == 1
