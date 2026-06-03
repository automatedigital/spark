"""/think <off|low|med|high> maps to reasoning effort (off → none, med → medium)."""

from __future__ import annotations

import pytest

from core.cli import commands_mixin
from core.cli.commands_mixin import _CommandHandlersMixin


class _Stub(_CommandHandlersMixin):
    def __init__(self):
        self.reasoning_config = None
        self.agent = "sentinel"


@pytest.fixture
def captured(monkeypatch):
    seen = {"effort": None, "saved": None}
    monkeypatch.setattr(commands_mixin, "_parse_reasoning_config", lambda e: {"effort": e})
    monkeypatch.setattr(commands_mixin, "save_config_value", lambda k, v: seen.__setitem__("saved", (k, v)) or True)
    monkeypatch.setattr(commands_mixin, "_cprint", lambda *a, **k: None)
    return seen


@pytest.mark.parametrize("arg,expected", [
    ("high", "high"),
    ("low", "low"),
    ("med", "medium"),
    ("off", "none"),
])
def test_think_maps_levels(captured, arg, expected):
    stub = _Stub()
    stub._handle_think_command(f"/think {arg}")
    assert stub.reasoning_config == {"effort": expected}
    assert captured["saved"] == ("agent.reasoning_effort", expected)
    assert stub.agent is None  # forces agent re-init


def test_think_unknown_level_is_rejected(captured):
    stub = _Stub()
    stub._handle_think_command("/think bogus")
    # unchanged — no config set, no save
    assert stub.reasoning_config is None
    assert captured["saved"] is None
