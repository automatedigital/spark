"""Tests for model_tools.py — function call dispatch, agent-loop interception, legacy toolsets."""

import json
from unittest.mock import call, patch

from core.model_tools import (
    _AGENT_LOOP_TOOLS,
    _LEGACY_TOOLSET_MAP,
    TOOL_TO_TOOLSET_MAP,
    get_all_tool_names,
    get_tool_definitions,
    get_toolset_for_tool,
    handle_function_call,
)
from core.toolsets import resolve_toolset

# =========================================================================
# handle_function_call
# =========================================================================

class TestHandleFunctionCall:
    def test_agent_loop_tool_returns_error(self):
        for tool_name in _AGENT_LOOP_TOOLS:
            result = json.loads(handle_function_call(tool_name, {}))
            assert "error" in result
            assert "agent loop" in result["error"].lower()

    def test_unknown_tool_returns_error(self):
        result = json.loads(handle_function_call("totally_fake_tool_xyz", {}))
        assert "error" in result
        assert "totally_fake_tool_xyz" in result["error"]

    def test_exception_returns_json_error(self):
        # Even if something goes wrong, should return valid JSON
        result = handle_function_call("web_search", None)  # None args may cause issues
        parsed = json.loads(result)
        assert isinstance(parsed, dict)
        assert "error" in parsed
        assert len(parsed["error"]) > 0
        assert "error" in parsed["error"].lower() or "failed" in parsed["error"].lower()

    def test_tool_hooks_receive_session_and_tool_call_ids(self):
        with (
            patch("core.model_tools.registry.dispatch", return_value='{"ok":true}'),
            patch("spark_cli.plugins.invoke_hook") as mock_invoke_hook,
        ):
            result = handle_function_call(
                "web_search",
                {"q": "test"},
                task_id="task-1",
                tool_call_id="call-1",
                session_id="session-1",
            )

        assert result == '{"ok":true}'
        assert mock_invoke_hook.call_args_list == [
            call(
                "pre_tool_call",
                tool_name="web_search",
                args={"q": "test"},
                task_id="task-1",
                session_id="session-1",
                tool_call_id="call-1",
            ),
            call(
                "post_tool_call",
                tool_name="web_search",
                args={"q": "test"},
                result='{"ok":true}',
                task_id="task-1",
                session_id="session-1",
                tool_call_id="call-1",
            ),
        ]


# =========================================================================
# Agent loop tools
# =========================================================================

class TestAgentLoopTools:
    def test_expected_tools_in_set(self):
        assert "todo" in _AGENT_LOOP_TOOLS
        assert "memory" in _AGENT_LOOP_TOOLS
        assert "session_search" in _AGENT_LOOP_TOOLS
        assert "delegate_task" in _AGENT_LOOP_TOOLS

    def test_no_regular_tools_in_set(self):
        assert "web_search" not in _AGENT_LOOP_TOOLS
        assert "terminal" not in _AGENT_LOOP_TOOLS


# =========================================================================
# Pre-tool-call blocking via plugin hooks
# =========================================================================

class TestPreToolCallBlocking:
    """Verify that pre_tool_call hooks can block tool execution."""

    def test_blocked_tool_returns_error_and_skips_dispatch(self, monkeypatch):
        def fake_invoke_hook(hook_name, **kwargs):
            if hook_name == "pre_tool_call":
                return [{"action": "block", "message": "Blocked by policy"}]
            return []

        dispatch_called = False
        _orig_dispatch = None

        def fake_dispatch(*args, **kwargs):
            nonlocal dispatch_called
            dispatch_called = True
            raise AssertionError("dispatch should not run when blocked")

        monkeypatch.setattr("spark_cli.plugins.invoke_hook", fake_invoke_hook)
        monkeypatch.setattr("core.model_tools.registry.dispatch", fake_dispatch)

        result = json.loads(handle_function_call("read_file", {"path": "test.txt"}, task_id="t1"))
        assert result == {"error": "Blocked by policy"}
        assert not dispatch_called

    def test_blocked_tool_skips_read_loop_notification(self, monkeypatch):
        notifications = []

        def fake_invoke_hook(hook_name, **kwargs):
            if hook_name == "pre_tool_call":
                return [{"action": "block", "message": "Blocked"}]
            return []

        monkeypatch.setattr("spark_cli.plugins.invoke_hook", fake_invoke_hook)
        monkeypatch.setattr("core.model_tools.registry.dispatch",
                            lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not run")))
        monkeypatch.setattr("tools.file_tools.notify_other_tool_call",
                            lambda task_id: notifications.append(task_id))

        result = json.loads(handle_function_call("web_search", {"q": "test"}, task_id="t1"))
        assert result == {"error": "Blocked"}
        assert notifications == []

    def test_invalid_hook_returns_do_not_block(self, monkeypatch):
        """Malformed hook returns should be ignored — tool executes normally."""
        def fake_invoke_hook(hook_name, **kwargs):
            if hook_name == "pre_tool_call":
                return [
                    "block",
                    {"action": "block"},           # missing message
                    {"action": "deny", "message": "nope"},
                ]
            return []

        monkeypatch.setattr("spark_cli.plugins.invoke_hook", fake_invoke_hook)
        monkeypatch.setattr("core.model_tools.registry.dispatch",
                            lambda *a, **kw: json.dumps({"ok": True}))

        result = json.loads(handle_function_call("read_file", {"path": "test.txt"}, task_id="t1"))
        assert result == {"ok": True}

    def test_skip_flag_prevents_double_block_check(self, monkeypatch):
        """When skip_pre_tool_call_hook=True, blocking is not checked (caller did it)."""
        hook_calls = []

        def fake_invoke_hook(hook_name, **kwargs):
            hook_calls.append(hook_name)
            return []

        monkeypatch.setattr("spark_cli.plugins.invoke_hook", fake_invoke_hook)
        monkeypatch.setattr("core.model_tools.registry.dispatch",
                            lambda *a, **kw: json.dumps({"ok": True}))

        handle_function_call("web_search", {"q": "test"}, task_id="t1",
                             skip_pre_tool_call_hook=True)

        # Hook still fires for observer notification, but get_pre_tool_call_block_message
        # is not called — invoke_hook fires directly in the skip=True branch.
        assert "pre_tool_call" in hook_calls
        assert "post_tool_call" in hook_calls


# =========================================================================
# Legacy toolset map
# =========================================================================

class TestLegacyToolsetMap:
    def test_expected_legacy_names(self):
        expected = [
            "web_tools", "terminal_tools", "vision_tools", "moa_tools",
            "image_tools", "skills_tools", "browser_tools", "cronjob_tools",
            "rl_tools", "file_tools", "tts_tools",
        ]
        for name in expected:
            assert name in _LEGACY_TOOLSET_MAP, f"Missing legacy toolset: {name}"

    def test_values_are_lists_of_strings(self):
        for name, tools in _LEGACY_TOOLSET_MAP.items():
            assert isinstance(tools, list), f"{name} is not a list"
            for tool in tools:
                assert isinstance(tool, str), f"{name} contains non-string: {tool}"


# =========================================================================
# Backward-compat wrappers
# =========================================================================

class TestBackwardCompat:
    def test_get_all_tool_names_returns_list(self):
        names = get_all_tool_names()
        assert isinstance(names, list)
        assert len(names) > 0
        # Should contain well-known tools
        assert "web_search" in names
        assert "terminal" in names

    def test_get_toolset_for_tool(self):
        result = get_toolset_for_tool("web_search")
        assert result is not None
        assert isinstance(result, str)

    def test_get_toolset_for_unknown_tool(self):
        result = get_toolset_for_tool("totally_nonexistent_tool")
        assert result is None

    def test_tool_to_toolset_map(self):
        assert isinstance(TOOL_TO_TOOLSET_MAP, dict)
        assert len(TOOL_TO_TOOLSET_MAP) > 0


# =========================================================================
# Tool manifest contract
# =========================================================================

class TestToolManifestContract:
    def test_spark_cli_toolset_names_are_registered(self):
        """The default Spark toolset should only reference registered or loop-owned tools."""
        missing = [
            name
            for name in resolve_toolset("spark-cli")
            if name not in TOOL_TO_TOOLSET_MAP and name not in _AGENT_LOOP_TOOLS
        ]
        assert missing == []

    def test_tool_definitions_are_returned_in_stable_name_order(self):
        """Schema order is prompt-sensitive, so registry sorting is intentional."""
        tools = get_tool_definitions(enabled_toolsets=["file"], quiet_mode=True)
        assert [tool["function"]["name"] for tool in tools] == [
            "patch",
            "read_file",
            "search_files",
            "write_file",
        ]

    def test_browser_schema_omits_web_tool_hint_when_web_tools_unavailable(self):
        fake_browser_schema = {
            "name": "browser_navigate",
            "description": (
                "Navigate somewhere. For simple information retrieval, "
                "prefer web_search or web_extract (faster, cheaper)."
            ),
            "parameters": {"type": "object", "properties": {}},
        }

        with patch(
            "core.model_tools.registry.get_definitions",
            return_value=[{"type": "function", "function": fake_browser_schema}],
        ):
            tools = get_tool_definitions(enabled_toolsets=["browser"], quiet_mode=True)

        desc = tools[0]["function"]["description"]
        assert "web_search" not in desc
        assert "web_extract" not in desc

    def test_execute_code_schema_omits_unavailable_sandbox_tools(self):
        """Final model-facing schemas must not advertise disabled helper tools."""
        tools = get_tool_definitions(
            enabled_toolsets=["code_execution"],
            quiet_mode=True,
        )
        schemas = {tool["function"]["name"]: tool["function"] for tool in tools}

        assert set(schemas) == {"execute_code"}

        schema_text = json.dumps(schemas["execute_code"])
        for unavailable_tool in (
            "web_search(",
            "web_extract(",
            "read_file(",
            "write_file(",
            "search_files(",
            "patch(",
            "terminal(",
        ):
            assert unavailable_tool not in schema_text
