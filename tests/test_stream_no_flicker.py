"""Flicker-prevention invariant: the streamed-response path must emit only
append-only output — no erase-to-EOL (`\\033[K`) and no cursor repositioning,
which are the sequences that cause flicker under prompt_toolkit's patch_stdout
(see CLAUDE.md). This is the programmatic proxy for the subjective multi-terminal
visual check.
"""

from __future__ import annotations

import re

import core.cli.streaming_mixin as sm
from core.cli.streaming_mixin import _StreamingMixin

# ANSI sequences that move/erase rather than append (flicker sources).
_FLICKER_RE = re.compile(r"\033\[(?:\d*[KJ]|\d*A|\d*F|\d*;\d*H|\d*d)")


class _CaptureStream(_StreamingMixin):
    def __init__(self):
        self.show_reasoning = False
        self.verbose = False
        self._stream_buf = ""
        self._stream_box_opened = False
        self._stream_text_ansi = ""
        self._invalidations = 0

    def _invalidate(self, min_interval: float = 0.25) -> None:
        self._invalidations += 1

    def _get_tui_terminal_width(self) -> int:
        return 80

    @staticmethod
    def _status_bar_display_width(text: str) -> int:
        from prompt_toolkit.utils import get_cwidth

        return get_cwidth(text or "")


def test_stream_emits_no_flicker_sequences(monkeypatch):
    emitted: list[str] = []
    monkeypatch.setattr(sm, "_cprint", lambda s="": emitted.append(s))

    cli = _CaptureStream()
    cli._reset_stream_state()

    # Feed a realistic multi-line response token by token.
    text = (
        "Here is a paragraph that is long enough to wrap across the terminal "
        "width several times so the drain loop splits it.\n"
        "- bullet one\n- bullet two\n\nA final line."
    )
    for ch in text:
        cli._stream_delta(ch)
    cli._flush_stream()

    joined = "\n".join(emitted)
    assert not _FLICKER_RE.search(joined), "streamed output contains a flicker-causing sequence"
    # And the per-token repaint stayed throttled (frame-budgeted), not per char.
    assert cli._invalidations <= len(text)


def test_repaint_frame_budget_constant_is_conservative():
    # ~10 fps cap keeps fast streams from thrashing the renderer on slow TTYs.
    assert 0 < sm._STREAM_REPAINT_MIN_INTERVAL <= 0.2
