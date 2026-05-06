"""Tests for gateway /kanban command behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _runner():
    from gateway.run import GatewayRunner

    return object.__new__(GatewayRunner)


def _event(args: str = ""):
    event = MagicMock()
    event.get_command_args.return_value = args
    return event


@pytest.mark.asyncio
async def test_gateway_kanban_summary_and_show():
    from core import kanban_db as kb

    task = kb.create_task(title="Gateway task", assignee="worker-a", body="Do the thing")
    runner = _runner()

    summary = await runner._handle_kanban_command(_event(""))
    detail = await runner._handle_kanban_command(_event(f"show {task['id']}"))

    assert "Gateway task" in summary
    assert task["id"] in summary
    assert "Do the thing" in detail


@pytest.mark.asyncio
async def test_gateway_kanban_dispatch_disabled_by_config():
    runner = _runner()

    with patch("spark_cli.config.load_config", return_value={"kanban": {"dispatch_in_gateway": False}}):
        result = await runner._handle_kanban_command(_event("dispatch"))

    assert "disabled" in result
    assert "spark kanban dispatch" in result


@pytest.mark.asyncio
async def test_gateway_kanban_dispatch_enabled_spawns_tick():
    runner = _runner()

    with (
        patch("spark_cli.config.load_config", return_value={"kanban": {"dispatch_in_gateway": True}}),
        patch(
            "spark_cli.kanban_dispatch.run_dispatch_tick",
            new=AsyncMock(return_value={"ok": True, "claimed": 2, "task_ids": ["t_a", "t_b"]}),
        ) as dispatch,
    ):
        result = await runner._handle_kanban_command(_event("dispatch"))

    dispatch.assert_awaited_once_with(max_tasks=3)
    assert "2 task(s)" in result
    assert "t_a, t_b" in result
