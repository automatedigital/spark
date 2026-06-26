"""Regression tests for optional SDK import isolation in tool discovery."""

import builtins
import importlib
import sys

from core.model_tools import get_tool_definitions


def _tool_names(definitions):
    return {tool["function"]["name"] for tool in definitions}


def test_missing_fal_client_disables_only_image_generation(monkeypatch):
    """A missing image SDK should not hide unrelated tool schemas."""
    original_import = builtins.__import__

    def import_without_fal(name, *args, **kwargs):
        if name == "fal_client" or name.startswith("fal_client."):
            raise ImportError("blocked fal_client for optional SDK isolation test")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_fal)
    sys.modules.pop("fal_client", None)
    sys.modules.pop("tools.image_generation_tool", None)

    image_tool = importlib.import_module("tools.image_generation_tool")

    assert image_tool.fal_client is None
    assert image_tool.check_image_generation_requirements() is False

    definitions = get_tool_definitions(
        enabled_toolsets=["image_gen", "file"],
        quiet_mode=True,
    )
    names = _tool_names(definitions)

    assert "image_generate" not in names
    assert {"read_file", "write_file", "patch", "search_files"}.issubset(names)
