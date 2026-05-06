"""Focused tests for durable Kanban task lifecycle behavior."""

from __future__ import annotations

import time

import pytest

from core import kanban_db as kb


def test_create_with_dependency_promotes_when_parent_done():
    parent = kb.create_task(title="Parent", assignee="worker-a")
    child = kb.create_task(
        title="Child",
        assignee="worker-a",
        parent_ids=[parent["id"]],
    )

    assert child["status"] == "todo"

    kb.complete_task(parent["id"], summary="parent complete")
    refreshed = kb.get_task(child["id"])

    assert refreshed is not None
    assert refreshed["status"] == "ready"


def test_link_cycle_rejected():
    first = kb.create_task(title="First")
    second = kb.create_task(title="Second")

    kb.add_link(first["id"], second["id"])

    with pytest.raises(ValueError, match="cycle"):
        kb.add_link(second["id"], first["id"])


def test_patch_status_block_unblock_and_complete():
    task = kb.create_task(title="Patch me", assignee="worker-a")

    patched = kb.patch_task(task["id"], status="todo", priority=5, tenant="tenant-a")
    assert patched is not None
    assert patched["status"] == "todo"
    assert patched["priority"] == 5
    assert patched["tenant"] == "tenant-a"

    blocked = kb.block_task(task["id"], "waiting on input")
    assert blocked is not None
    assert blocked["status"] == "blocked"

    unblocked = kb.unblock_task(task["id"])
    assert unblocked is not None
    assert unblocked["status"] == "ready"

    done = kb.complete_task(task["id"], summary="finished")
    assert done is not None
    assert done["status"] == "done"
    assert done["result"] == "finished"


def test_reclaim_stale_running_returns_task_to_ready():
    task = kb.create_task(title="Run me", assignee="worker-a")
    claim = kb.claim_ready_task(task["id"], profile="worker-a", claim_ttl_seconds=-1)

    assert claim is not None
    assert kb.get_task(task["id"])["status"] == "running"

    reclaimed = kb.reclaim_stale_running(claim_ttl_seconds=1, check_pid=False)

    assert reclaimed == [task["id"]]
    assert kb.get_task(task["id"])["status"] == "ready"


def test_bulk_patch_reports_missing_task_errors():
    task = kb.create_task(title="Bulk", assignee="worker-a")

    result = kb.bulk_patch([task["id"], "missing"], {"status": "done"})

    assert result["ok"] is False
    assert result["errors"] == {"missing": "Task not found"}
    assert kb.get_task(task["id"])["status"] == "done"


def test_board_columns_sorted_by_priority_then_updated_at():
    older = kb.create_task(title="Older", assignee="worker-a", priority=1)
    time.sleep(0.01)
    newer = kb.create_task(title="Newer", assignee="worker-a", priority=1)
    highest = kb.create_task(title="Highest", assignee="worker-a", priority=10)

    ids = [row["id"] for row in kb.get_board()["columns"]["ready"]]

    assert ids.index(highest["id"]) < ids.index(newer["id"])
    assert ids.index(newer["id"]) < ids.index(older["id"])


def test_preview_ready_for_dispatch_reports_assignee_concurrency():
    first = kb.create_task(title="First", assignee="worker-a", priority=2)
    second = kb.create_task(title="Second", assignee="worker-a", priority=1)
    third = kb.create_task(title="Third", assignee="worker-b", priority=1)

    preview = kb.preview_ready_for_dispatch(max_tasks=3)

    assert preview["dry_run"] is True
    assert preview["ready"] == [first["id"], third["id"]]
    assert preview["blocked_by_assignee"] == ["worker-a"]
    assert second["id"] not in preview["ready"]
