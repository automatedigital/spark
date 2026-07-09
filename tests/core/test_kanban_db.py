"""Focused tests for durable Kanban task lifecycle behavior."""

from __future__ import annotations

import json
import sqlite3
import time

import pytest

from core import kanban_db as kb


def test_old_schema_missing_owner_profile_self_heals():
    path = kb.kanban_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE boards (
                slug TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                description TEXT,
                icon TEXT,
                created_at REAL NOT NULL
            );
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY,
                board_slug TEXT NOT NULL DEFAULT 'default',
                title TEXT NOT NULL,
                body TEXT,
                status TEXT NOT NULL DEFAULT 'todo',
                assignee TEXT,
                tenant TEXT,
                priority INTEGER NOT NULL DEFAULT 0,
                idempotency_key TEXT UNIQUE,
                workspace_kind TEXT NOT NULL DEFAULT 'scratch',
                workspace_path TEXT,
                skills_json TEXT,
                result TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                current_run_id INTEGER,
                claim_token TEXT,
                claim_expires_at REAL,
                worker_pid INTEGER,
                spawn_failures INTEGER NOT NULL DEFAULT 0,
                max_runtime_seconds INTEGER NOT NULL DEFAULT 0
            );
            INSERT INTO boards (slug, display_name, description, icon, created_at)
            VALUES ('default', 'Default', '', '', 1);
            INSERT INTO tasks (
                id, board_slug, title, status, priority, workspace_kind,
                created_at, updated_at
            )
            VALUES ('old_task', 'default', 'Old task', 'running', 1, 'scratch', 1, 1);
            """
        )
        conn.commit()
    finally:
        conn.close()

    kb._initialized[str(path)] = True
    try:
        board = kb.get_board()
    finally:
        kb._initialized.pop(str(path), None)

    assert board["columns"]["running"][0]["id"] == "old_task"
    assert board["columns"]["running"][0]["owner_profile"] is None

    conn = sqlite3.connect(path)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    finally:
        conn.close()
    assert "owner_profile" in columns


def test_create_with_dependency_promotes_when_parent_done():
    parent = kb.create_task(title="Parent", assignee="worker-a")
    child = kb.create_task(
        title="Child",
        assignee="worker-a",
        parent_ids=[parent["id"]],
    )

    assert child["status"] == "todo"

    kb.mark_task_done(parent["id"], summary="parent complete")
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

    assert task["status"] == "todo"

    patched = kb.patch_task(task["id"], status="ready", priority=5, tenant="tenant-a")
    assert patched is not None
    assert patched["status"] == "ready"
    assert patched["priority"] == 5
    assert patched["tenant"] == "tenant-a"

    blocked = kb.block_task(task["id"], "waiting on input")
    assert blocked is not None
    assert blocked["status"] == "blocked"

    unblocked = kb.unblock_task(task["id"])
    assert unblocked is not None
    assert unblocked["status"] == "ready"

    review = kb.complete_task(task["id"], summary="finished")
    assert review is not None
    assert review["status"] == "user_review"
    assert review["result"] == "finished"

    done = kb.mark_task_done(task["id"], summary="accepted")
    assert done is not None
    assert done["status"] == "done"


def test_reclaim_stale_running_returns_task_to_ready():
    task = kb.create_task(title="Run me", assignee="worker-a")
    kb.patch_task(task["id"], status="ready")
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
    kb.patch_task(older["id"], status="ready")
    time.sleep(0.01)
    newer = kb.create_task(title="Newer", assignee="worker-a", priority=1)
    kb.patch_task(newer["id"], status="ready")
    highest = kb.create_task(title="Highest", assignee="worker-a", priority=10)
    kb.patch_task(highest["id"], status="ready")

    ids = [row["id"] for row in kb.get_board()["columns"]["ready"]]

    assert ids.index(highest["id"]) < ids.index(newer["id"])
    assert ids.index(newer["id"]) < ids.index(older["id"])


def test_preview_ready_for_dispatch_reports_assignee_concurrency():
    first = kb.create_task(title="First", assignee="worker-a", priority=2)
    second = kb.create_task(title="Second", assignee="worker-a", priority=1)
    third = kb.create_task(title="Third", assignee="worker-b", priority=1)
    for task in (first, second, third):
        kb.patch_task(task["id"], status="ready")

    preview = kb.preview_ready_for_dispatch(max_tasks=3)

    assert preview["dry_run"] is True
    assert preview["ready"] == [first["id"], third["id"]]
    assert preview["blocked_by_assignee"] == ["worker-a"]
    assert second["id"] not in preview["ready"]


def test_task_notification_metadata_and_events_are_durable():
    creator_source = {
        "platform": "telegram",
        "chat_id": "chat-1",
        "chat_type": "dm",
        "user_id": "user-1",
        "user_name": "Owner",
    }
    task = kb.create_task(
        title="Notify me",
        assignee="worker-a",
        owner_profile="owner-profile",
        owner_platform="telegram",
        owner_channel="chat-1",
        creator_session_key="agent:main:telegram:dm:chat-1",
        creator_session_source=creator_source,
        notify_on_changes=True,
        wake_on_changes=True,
    )

    assert task["owner_profile"] == "owner-profile"
    assert task["owner_platform"] == "telegram"
    assert task["notify_on_changes"] == 1
    assert task["wake_on_changes"] == 1

    kb.patch_task(
        task["id"],
        status="ready",
        actor="Owner",
        origin_session_key="agent:main:telegram:dm:chat-1",
        origin_kind="test",
    )
    kb.add_comment(
        task["id"],
        "Looks good",
        "Owner",
        origin_session_key="agent:main:telegram:dm:chat-1",
        origin_kind="test",
    )

    events = kb.append_events_since(0)
    status_event = next(e for e in events if e["kind"] == "status")
    comment_event = next(e for e in events if e["kind"] == "comment")
    status_payload = json.loads(status_event["payload_json"])
    comment_payload = json.loads(comment_event["payload_json"])

    assert status_payload["from"] == "todo"
    assert status_payload["to"] == "ready"
    assert status_payload["origin"]["session_key"] == "agent:main:telegram:dm:chat-1"
    assert status_payload["task"]["owner_channel"] == "chat-1"
    assert status_payload["task"]["creator_session_key"] == "agent:main:telegram:dm:chat-1"
    assert json.loads(status_payload["task"]["creator_session_source_json"]) == creator_source
    assert comment_payload["body"] == "Looks good"
    assert comment_payload["task"]["notify_on_changes"] is True
