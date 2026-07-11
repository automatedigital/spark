import sys
import types

from spark_cli.main import _prompt_reasoning_effort_selection


class _FakeTerminalMenu:
    last_choices = None

    def __init__(self, choices, **kwargs):
        _FakeTerminalMenu.last_choices = choices
        self._cursor_index = kwargs.get("cursor_index")

    def show(self):
        return self._cursor_index


def test_reasoning_menu_uses_webui_labels_and_returns_stored_value(monkeypatch):
    fake_module = types.SimpleNamespace(TerminalMenu=_FakeTerminalMenu)
    monkeypatch.setitem(sys.modules, "simple_term_menu", fake_module)

    selected = _prompt_reasoning_effort_selection(
        ["low", "minimal", "medium", "high"],
        current_effort="medium",
    )

    assert selected == "medium"
    assert _FakeTerminalMenu.last_choices[:4] == [
        "  light",
        "  medium",
        "  high  ← currently in use",
        "  extra-high",
    ]


def test_reasoning_menu_labels_xhigh_as_ultra(monkeypatch):
    fake_module = types.SimpleNamespace(TerminalMenu=_FakeTerminalMenu)
    monkeypatch.setitem(sys.modules, "simple_term_menu", fake_module)

    selected = _prompt_reasoning_effort_selection(
        ["minimal", "low", "medium", "high", "xhigh"],
        current_effort="xhigh",
    )

    assert selected == "xhigh"
    assert _FakeTerminalMenu.last_choices[:5] == [
        "  light",
        "  medium",
        "  high",
        "  extra-high",
        "  ultra  ← currently in use",
    ]
