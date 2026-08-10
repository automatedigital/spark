"""Tests for terminal/file tool availability in local dev environments."""

import importlib

from core.model_tools import get_tool_definitions
from tools.registry import registry

terminal_tool_module = importlib.import_module("tools.terminal_tool")


class TestTerminalRequirements:
    def test_local_backend_requirements(self, monkeypatch):
        monkeypatch.setattr(
            terminal_tool_module,
            "_get_env_config",
            lambda: {"env_type": "local"},
        )
        assert terminal_tool_module.check_terminal_requirements() is True

    def test_terminal_and_file_tools_resolve_for_local_backend(self, monkeypatch):
        monkeypatch.setattr(
            terminal_tool_module,
            "_get_env_config",
            lambda: {"env_type": "local"},
        )
        tools = get_tool_definitions(enabled_toolsets=["terminal", "file"], quiet_mode=True)
        names = {tool["function"]["name"] for tool in tools}
        assert "terminal" in names
        assert {"read_file", "write_file", "patch", "search_files"}.issubset(names)

    def test_legacy_managed_modal_flag_does_not_restore_removed_backend(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SPARK_ENABLE_NOUS_MANAGED_TOOLS", "1")
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.delenv("MODAL_TOKEN_ID", raising=False)
        monkeypatch.delenv("MODAL_TOKEN_SECRET", raising=False)
        monkeypatch.setattr(
            terminal_tool_module,
            "_get_env_config",
            lambda: {"env_type": "modal", "modal_mode": "managed"},
        )
        monkeypatch.setattr(
            terminal_tool_module,
            "is_managed_tool_gateway_ready",
            lambda _vendor: True,
        )
        # Other tests can replace the process-global registry entry. Restore
        # this module's availability contract so the assertion is order-safe.
        terminal_entry = registry.get_entry("terminal")
        assert terminal_entry is not None
        monkeypatch.setattr(
            terminal_entry,
            "check_fn",
            terminal_tool_module.check_terminal_requirements,
        )
        tools = get_tool_definitions(enabled_toolsets=["terminal", "code_execution"], quiet_mode=True)
        names = {tool["function"]["name"] for tool in tools}

        assert "terminal" not in names
        assert "execute_code" in names
