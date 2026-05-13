"""Tests for cua-driver binary resolution (computer_use availability)."""

import json
import sys

import pytest


@pytest.fixture
def darwin(monkeypatch):
    import platform

    monkeypatch.setattr(platform, "system", lambda: "Darwin")


def test_is_available_finds_cua_in_dot_local_bin(tmp_path, monkeypatch, darwin):
    monkeypatch.delenv("SPARK_CUA_DRIVER_BIN", raising=False)
    home = tmp_path / "home"
    home.mkdir()
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    cua = bin_dir / "cua-driver"
    cua.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    cua.chmod(0o755)
    monkeypatch.setenv("HOME", str(home))

    fake_py = tmp_path / "venv" / "bin" / "python3"
    fake_py.parent.mkdir(parents=True)
    fake_py.touch()
    monkeypatch.setattr(sys, "executable", str(fake_py))

    import tools.computer_use.cua_backend as cb

    monkeypatch.setattr(cb.shutil, "which", lambda _n: None)

    from tools.computer_use.cua_backend import is_available

    assert is_available() is True


def test_resolution_hint_uses_official_cua_installer(tmp_path, monkeypatch, darwin):
    fake_py = tmp_path / "conda" / "bin" / "python3"
    fake_py.parent.mkdir(parents=True)
    fake_py.touch()
    monkeypatch.setattr(sys, "executable", str(fake_py))

    import tools.computer_use.cua_backend as cb

    monkeypatch.setattr(cb.shutil, "which", lambda _n: None)

    hint = cb.cua_driver_resolution_hint()

    assert f"Spark Python: {fake_py}" in hint
    assert "Install cua-driver: /bin/bash -c" in hint
    assert "raw.githubusercontent.com/trycua/cua/main/libs/cua-driver/scripts/install.sh" in hint


def test_computer_use_dispatch_accepts_task_id(monkeypatch):
    from tools.computer_use import tool as computer_use_tool
    from tools.registry import registry

    monkeypatch.setattr(
        computer_use_tool._backend,
        "list_apps",
        lambda: [{"pid": 123, "name": "Notion"}],
    )

    result = json.loads(
        registry.dispatch("computer_use", {"action": "list_apps"}, task_id="task-123")
    )

    assert "error" not in result
    assert result["apps"] == [{"pid": 123, "name": "Notion"}]


def test_cua_window_helpers_accept_current_api_shape():
    from tools.computer_use import cua_backend as cb

    windows = cb._parse_windows(
        {
            "structuredContent": {
                "windows": [
                    {
                        "pid": 456,
                        "app_name": "Notion",
                        "window_id": 789,
                        "z_index": 1,
                    }
                ]
            }
        }
    )
    target = cb._select_window(windows, "notion")

    assert cb._window_app(target) == "Notion"
    assert cb._window_id(target) == 789


def test_cua_key_combo_parses_schema_format():
    from tools.computer_use import cua_backend as cb

    assert cb._parse_key_combo("cmd+p") == ["cmd", "p"]
    assert cb._parse_key_combo("shift+delete") == ["shift", "delete"]
    assert cb._parse_key_combo("return") == ["return"]


def test_capture_without_app_requires_active_context():
    from tools.computer_use.cua_backend import CuaDriverBackend

    backend = CuaDriverBackend()
    with pytest.raises(RuntimeError, match="capture requires app"):
        backend.capture()
