"""/backend command: show + set the execution backend."""

from __future__ import annotations

import pytest

from core.cli import commands_mixin
from core.cli.commands_mixin import _CommandHandlersMixin


class _Stub(_CommandHandlersMixin):
    pass


@pytest.fixture
def captured(monkeypatch):
    seen = {"saved": None}
    monkeypatch.setattr(commands_mixin, "save_config_value", lambda k, v: seen.__setitem__("saved", (k, v)) or True)
    monkeypatch.setattr(commands_mixin, "_cprint", lambda *a, **k: None)
    return seen


@pytest.mark.parametrize("backend", ["local", "docker", "ssh", "singularity", "modal", "daytona"])
def test_set_valid_backend(captured, backend):
    _Stub()._handle_backend_command(f"/backend {backend}")
    assert captured["saved"] == ("terminal.backend", backend)


def test_invalid_backend_rejected(captured):
    _Stub()._handle_backend_command("/backend nope")
    assert captured["saved"] is None


def test_show_current_backend_no_arg(captured, monkeypatch):
    monkeypatch.setattr(commands_mixin, "load_config", lambda: {"terminal": {"backend": "docker"}}, raising=False)
    _Stub()._handle_backend_command("/backend")
    assert captured["saved"] is None  # no set on bare command
