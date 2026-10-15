"""Real SQLite contract replay. Provider and transport work stays outside fixtures."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.subagents import emit, make_run_record
from core.spark_state import SCHEMA_VERSION, SessionDB

CONTRACT = json.loads(
    (Path(__file__).parents[1] / "fixtures/app_upgrade/contracts-v1.json").read_text()
)["execution"]


def test_contract_replay_restart_compression_and_root_authority(tmp_path):
    path = tmp_path / "state.db"
    db = SessionDB(path)
    parent = CONTRACT["parent_session_id"]
    db.create_session(parent, "web")
    db.create_session("compressed", "web", parent_session_id=parent)
    db._conn.execute("UPDATE sessions SET end_reason='compression' WHERE id=?", (parent,))
    db.create_session(CONTRACT["child_session_id"], "delegate", parent_session_id=parent)
    db.upsert_web_turn_projection(CONTRACT["root_run_id"], parent, {"status": "running"})
    db.create_web_pending_action(action_id="decision-1", session_id=parent,
                                 turn_id=CONTRACT["root_run_id"], kind="approval", payload={"tool": "fixture"})
    published = []
    db.subscribe_session_events(published.append)
    run = {key: value for key, value in CONTRACT.items() if key not in ("events", "expected_child_status", "expected_root_status")}
    for event in CONTRACT["events"]:
        name = event["event"]
        result = db.commit_subagent_lifecycle(
            {**run, "status": "completed" if name == "completed" else "running"}, event
        )
        assert result["event"]["event_id"] == event["event_id"]
    assert len(published) == 4
    db.close()
    db = SessionDB(path)
    try:
        snapshot = db.list_subagent_runs("compressed")[0]
        assert snapshot["status"] == CONTRACT["expected_child_status"]
        for key in ("root_run_id", "attempt_id", "node_id", "parent_node_id"):
            assert snapshot[key] == CONTRACT[key]
        assert snapshot["projection_version"] == 1
        assert len(db.get_subagent_events(run["id"])) == 4
        events = [e for e in db.get_session_events(parent) if e["event_type"].startswith("subagent.")]
        assert len(events) == 4
        assert db.get_latest_web_turn_projection(parent)["projection"]["status"] == "running"
        assert db.get_web_pending_action("decision-1")["status"] == "pending"
        assert db.get_session(parent)["ended_at"] is None
    finally:
        db.close()


def test_atomic_failure_rolls_back_all_three_writes_and_does_not_publish(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    db.create_session("parent", "cli")
    db._conn.execute("""CREATE TRIGGER fail_child_session_event BEFORE INSERT ON session_events
        WHEN NEW.event_type LIKE 'subagent.%' BEGIN SELECT RAISE(ABORT, 'fixture crash'); END""")
    published = []
    db.subscribe_session_events(published.append)
    with pytest.raises(sqlite3.IntegrityError, match="fixture crash"):
        db.commit_subagent_lifecycle(
            {"id": "child", "parent_session_id": "parent", "status": "running"},
            {"event_id": "start-1", "event": "started"},
        )
    assert db.get_subagent_run("child") is None
    assert db.get_subagent_events("child") == []
    assert published == []
    db.close()


def test_duplicate_concurrent_connections_commit_one_event(tmp_path):
    path = tmp_path / "state.db"
    db = SessionDB(path)
    db.create_session("parent", "cli")
    connections = [SessionDB(path) for _ in range(6)]
    try:
        def write(connection):
            return connection.commit_subagent_lifecycle(
                {"id": "child", "parent_session_id": "parent", "status": "running"},
                {"event_id": "same", "event": "started"},
            )
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(write, connections))
        assert sum(result["created"] for result in results) == 1
        assert len(db.get_subagent_events("child")) == 1
    finally:
        for connection in connections:
            connection.close()
        db.close()


def test_schema12_upgrade_is_additive_and_idempotent(tmp_path):
    path = tmp_path / "state.db"
    db = SessionDB(path)
    db.create_session("legacy", "cli")
    db.create_subagent_run({"id": "old-child", "parent_session_id": "legacy", "status": "completed"})
    db.append_subagent_event("old-child", "completed", {"summary": "preserved"})
    # Reconstruct the actual v12 tables: the only removed columns are v13 additions.
    db._conn.execute("DROP TABLE runtime_child_jobs")
    db._conn.execute("DROP TABLE runtime_command_receipts")
    db._conn.execute("DROP INDEX idx_subagent_event_identity")
    db._conn.execute("ALTER TABLE subagent_events DROP COLUMN event_id")
    for name in ("root_run_id", "attempt_id", "parent_node_id", "node_id", "projection_version", "execution_mode", "retry_of"):
        db._conn.execute(f"ALTER TABLE subagent_runs DROP COLUMN {name}")
    db._conn.execute("UPDATE schema_version SET version=12")
    db.close()
    for _ in range(2):
        db = SessionDB(path)
        assert db._conn.execute("SELECT version FROM schema_version").fetchone()[0] == SCHEMA_VERSION
        assert db.get_subagent_run("old-child")["root_run_id"] is None
        assert db.get_subagent_run("old-child")["status"] == "completed"
        assert db.get_subagent_events("old-child")[0]["data"] == {"summary": "preserved"}
        assert db.get_subagent_events("old-child")[0]["event_id"] is None
        db.close()


def test_dedicated_callback_remains_the_single_writer_and_failure_does_not_publish(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    db.create_session("parent", "cli")
    events = []
    progress = []
    def dedicated(event):
        result = db.commit_subagent_lifecycle(event["subagent_run"], event)
        events.append(result)
    parent = SimpleNamespace(_session_db=db, subagent_event_callback=dedicated,
                             tool_progress_callback=lambda *a, **kw: progress.append(kw["event"]))
    record = make_run_record(parent_session_id="parent", task_index=0, task="fixture")
    emit(parent, record, "created")
    assert len(db.get_subagent_events(record["id"])) == 1
    assert len(events) == len(progress) == 1
    assert progress[0]["event_id"] == events[0]["event"]["event_id"]
    def broken(event):
        raise RuntimeError("persistence unavailable")
    parent.subagent_event_callback = broken
    with pytest.raises(RuntimeError, match="persistence unavailable"):
        emit(parent, record, "completed")
    assert len(progress) == 1
    db.close()


def test_cancelled_is_terminal_and_large_events_remain_bounded(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    db.create_session("parent", "cli")
    db.create_subagent_run({"id": "cancelled", "parent_session_id": "parent", "status": "cancelled"})
    result = db.commit_subagent_lifecycle(
        {"id": "cancelled", "parent_session_id": "parent", "status": "running"},
        {"event_id": "huge-late-tool", "event": "tool_started", "payload": {"text": "x" * 100_000}},
    )
    assert result["run"]["status"] == "cancelled"
    assert result["event"]["event_id"] == "huge-late-tool"
    assert result["event"]["schema"] == "spark.subagent.lifecycle.v1"
    assert result["event"]["subagent_id"] == "cancelled"
    assert result["event"]["subagent_run"]["status"] == "cancelled"
    assert len(json.dumps(result["event"])) <= 24_000
    assert db.get_subagent_events("cancelled")[0]["data"] == result["event"]
    db.close()


def test_interrupt_capability_requires_callable_on_owned_live_child():
    from core.orchestration.capabilities import owned_live_child
    run = {"status": "running", "child_session_id": "child"}
    parent = SimpleNamespace(_active_children=[SimpleNamespace(session_id="child")])
    assert owned_live_child(parent, run) is None
    parent._active_children[0].interrupt = lambda message: None
    assert owned_live_child(parent, run) is parent._active_children[0]
    assert owned_live_child(parent, {**run, "status": "cancelled"}) is None
