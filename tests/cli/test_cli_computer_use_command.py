"""Tests for the /computer-use CLI slash command."""

from unittest.mock import MagicMock, patch

from core.cli import SparkCLI


def _make_cli():
    cli_obj = SparkCLI.__new__(SparkCLI)
    cli_obj.config = {}
    cli_obj.console = MagicMock()
    cli_obj.agent = None
    cli_obj.conversation_history = []
    cli_obj.session_id = "sess-cu"
    cli_obj.enabled_toolsets = ["terminal"]
    cli_obj._pending_input = MagicMock()
    return cli_obj


def _make_cli_with_agent():
    cli_obj = _make_cli()
    cli_obj.agent = MagicMock()
    cli_obj.agent.enabled_toolsets = ["terminal"]
    cli_obj.agent.disabled_toolsets = None
    cli_obj.agent.tools = []
    cli_obj.agent.valid_tool_names = set()
    cli_obj.agent._persist_session = MagicMock()
    cli_obj.agent._invalidate_system_prompt = MagicMock()
    return cli_obj


class TestComputerUseCommand:
    def test_non_macos_noop(self):
        cli_obj = _make_cli_with_agent()
        with patch("platform.system", return_value="Linux"):
            assert cli_obj.process_command("/computer-use do something") is True
        cli_obj._pending_input.put.assert_not_called()
        assert cli_obj.conversation_history == []

    def test_macos_enables_and_queues_task(self):
        cli_obj = _make_cli_with_agent()
        with patch("platform.system", return_value="Darwin"):
            with patch(
                "spark_cli.tools_config.enable_computer_use_cli_toolset"
            ) as en:
                with patch(
                    "spark_cli.tools_config._get_platform_tools",
                    return_value=["computer_use", "terminal"],
                ):
                    with patch("core.model_tools.get_tool_definitions") as gt:
                        gt.return_value = [{"function": {"name": "computer_use"}}]
                        assert cli_obj.process_command("/cu click OK") is True
        en.assert_called_once()
        assert "computer_use" in cli_obj.agent.valid_tool_names
        cli_obj.agent._invalidate_system_prompt.assert_called_once()
        cli_obj._pending_input.put.assert_called_once()
        queued = cli_obj._pending_input.put.call_args[0][0]
        assert queued == "click OK"
        assert len(cli_obj.conversation_history) == 1
        assert "[SYSTEM:" in cli_obj.conversation_history[0]["content"]
        assert "click OK" not in cli_obj.conversation_history[0]["content"]

    def test_macos_computer_use_hidden_prompt_infers_target_app(self):
        cli_obj = _make_cli_with_agent()
        with patch("platform.system", return_value="Darwin"):
            with patch("spark_cli.tools_config.enable_computer_use_cli_toolset"):
                with patch(
                    "spark_cli.tools_config._get_platform_tools",
                    return_value=["computer_use", "terminal"],
                ):
                    with patch("core.model_tools.get_tool_definitions") as gt:
                        gt.return_value = [{"function": {"name": "computer_use"}}]
                        assert (
                            cli_obj.process_command(
                                "/computer-use Open Notion and press Cmd+P"
                            )
                            is True
                        )

        queued = cli_obj._pending_input.put.call_args[0][0]
        hidden = cli_obj.conversation_history[0]["content"]
        assert queued == "Open Notion and press Cmd+P"
        assert "app='Notion'" in hidden
        assert "Never call action='capture' without app" in hidden

    def test_macos_without_task_appends_history(self):
        cli_obj = _make_cli_with_agent()
        with patch("platform.system", return_value="Darwin"):
            with patch("spark_cli.tools_config.enable_computer_use_cli_toolset"):
                with patch(
                    "spark_cli.tools_config._get_platform_tools",
                    return_value=["computer_use"],
                ):
                    with patch("core.model_tools.get_tool_definitions") as gt:
                        gt.return_value = [{"function": {"name": "computer_use"}}]
                        assert cli_obj.process_command("/computer-use") is True
        assert len(cli_obj.conversation_history) == 1
        assert "computer_use" in cli_obj.conversation_history[0]["content"]
        cli_obj._pending_input.put.assert_not_called()
        cli_obj.agent._persist_session.assert_called_once()

    def test_macos_missing_cua_queues_fallback_not_force_system(self):
        cli_obj = _make_cli_with_agent()
        with patch("platform.system", return_value="Darwin"):
            with patch("spark_cli.tools_config.enable_computer_use_cli_toolset"):
                with patch(
                    "spark_cli.tools_config._get_platform_tools",
                    return_value=["computer_use", "terminal"],
                ):
                    with patch("core.model_tools.get_tool_definitions") as gt:
                        gt.return_value = [{"function": {"name": "terminal"}}]
                        with patch(
                            "tools.computer_use.cua_backend.is_available",
                            return_value=False,
                        ):
                            assert (
                                cli_obj.process_command(
                                    "/computer-use do something in Notion"
                                )
                                is True
                            )
        cli_obj._pending_input.put.assert_called_once()
        queued = cli_obj._pending_input.put.call_args[0][0]
        assert queued == "do something in Notion"
        assert len(cli_obj.conversation_history) == 1
        hidden = cli_obj.conversation_history[0]["content"]
        assert "MUST use computer_use" not in hidden
        assert "not available" in hidden.lower() or "missing" in hidden.lower()

    def test_macos_no_task_without_tool_no_history(self):
        cli_obj = _make_cli_with_agent()
        with patch("platform.system", return_value="Darwin"):
            with patch("spark_cli.tools_config.enable_computer_use_cli_toolset"):
                with patch(
                    "spark_cli.tools_config._get_platform_tools",
                    return_value=["computer_use"],
                ):
                    with patch("core.model_tools.get_tool_definitions") as gt:
                        gt.return_value = []
                        with patch(
                            "tools.computer_use.cua_backend.is_available",
                            return_value=False,
                        ):
                            assert cli_obj.process_command("/computer-use") is True
        assert cli_obj.conversation_history == []
