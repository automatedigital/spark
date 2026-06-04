"""Status bar surfaces thinking level + token/cost totals on wide terminals."""

from __future__ import annotations

from core.cli.status_bar_mixin import _StatusBarMixin


class _Stub(_StatusBarMixin):
    _status_bar_visible = True
    _model_picker_state = None

    def __init__(self, reasoning_config=None, width=120):
        self.reasoning_config = reasoning_config
        self._width = width

    def _get_tui_terminal_width(self):
        return self._width

    def _get_status_bar_snapshot(self):
        return {
            "model_short": "opus-4-8",
            "duration": "1m",
            "context_percent": 42,
            "context_length": 200000,
            "context_tokens": 84000,
            "session_total_tokens": 125000,
            "estimated_cost_usd": 1.2345,
        }


def _text(stub):
    return "".join(t for _, t in stub._get_status_bar_fragments())


def test_thinking_level_label():
    assert _Stub({"effort": "high"})._thinking_level_label() == "high"
    assert _Stub({"effort": "medium"})._thinking_level_label() == "med"
    assert _Stub({"enabled": False})._thinking_level_label() == "off"
    assert _Stub(None)._thinking_level_label() == "med"


def test_wide_bar_shows_thinking_tokens_cost():
    text = _text(_Stub({"effort": "high"}, width=120))
    assert "high" in text
    assert "125K" in text
    assert "$1.23" in text


def test_narrow_bar_omits_extras():
    # Below the 96-col threshold the extras are dropped to avoid overflow.
    text = _text(_Stub({"effort": "high"}, width=80))
    assert "$1.23" not in text
    assert "125K" not in text
