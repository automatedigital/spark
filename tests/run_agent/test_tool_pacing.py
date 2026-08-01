"""Focused tests for sequential tool-call pacing."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.run_agent import AIAgent


def _tool_definitions() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "terminal",
                "description": "Run a terminal command.",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]


def _tool_call(call_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name="terminal", arguments='{"command":"true"}'),
    )


def _make_agent(*, tool_delay: float | None = None) -> AIAgent:
    kwargs = {}
    if tool_delay is not None:
        kwargs["tool_delay"] = tool_delay

    with (
        patch("core.run_agent.get_tool_definitions", return_value=_tool_definitions()),
        patch("core.run_agent.check_toolset_requirements", return_value={}),
        patch("core.run_agent.OpenAI"),
    ):
        agent = AIAgent(
            api_key="test-key-1234567890",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
            **kwargs,
        )
    agent.client = MagicMock()
    return agent


def _two_tool_message() -> SimpleNamespace:
    return SimpleNamespace(tool_calls=[_tool_call("c1"), _tool_call("c2")])


def test_sequential_tools_have_no_artificial_delay_by_default() -> None:
    agent = _make_agent()
    messages: list[dict] = []

    with (
        patch("core.run_agent.handle_function_call", return_value='{"ok":true}'),
        patch("core.run_agent.enforce_turn_budget") as mock_budget,
        patch("core.run_agent.time.sleep") as mock_sleep,
    ):
        agent._execute_tool_calls(_two_tool_message(), messages, "task-1")

    assert agent.tool_delay == 0.0
    mock_sleep.assert_not_called()
    assert [message["tool_call_id"] for message in messages] == ["c1", "c2"]
    assert all("name" not in message for message in messages)
    assert mock_budget.call_args.kwargs["tool_names"] == ["terminal", "terminal"]


def test_explicit_sequential_tool_pacing_is_preserved() -> None:
    agent = _make_agent(tool_delay=0.25)
    messages: list[dict] = []

    with (
        patch("core.run_agent.handle_function_call", return_value='{"ok":true}'),
        patch("core.run_agent.time.sleep") as mock_sleep,
    ):
        agent._execute_tool_calls(_two_tool_message(), messages, "task-1")

    mock_sleep.assert_called_once_with(0.25)
    assert [message["tool_call_id"] for message in messages] == ["c1", "c2"]
