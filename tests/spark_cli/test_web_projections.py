from spark_cli.web_projections import compute_changed_files, normalize_plan


def test_session_db_web_projection_and_action_resolution_are_idempotent():
    from core.spark_state import SessionDB

    db = SessionDB()
    try:
        db.ensure_session("projection-session", source="web", model="test")
        projection = {"turn_id": "turn-1", "status": "running", "plan": None}
        db.upsert_web_turn_projection("turn-1", "projection-session", projection)
        assert db.get_latest_web_turn_projection("projection-session")["projection"] == projection

        created = db.create_web_pending_action(
            action_id="action-1",
            session_id="projection-session",
            turn_id="turn-1",
            kind="requested_input",
            payload={"question": "Continue?"},
        )
        assert created["status"] == "pending"
        resolved, changed = db.resolve_web_pending_action(
            action_id="action-1",
            session_id="projection-session",
            response={"value": "yes"},
        )
        assert changed is True
        assert resolved["status"] == "resolved"

        repeated, changed = db.resolve_web_pending_action(
            action_id="action-1",
            session_id="projection-session",
            response={"value": "no"},
        )
        assert changed is False
        assert repeated["response"] == {"value": "yes"}

        db.create_web_pending_action(
            action_id="action-cancelled",
            session_id="projection-session",
            turn_id="turn-1",
            kind="requested_input",
            payload={"question": "Cancel me"},
        )
        cancelled, changed = db.cancel_web_pending_action(
            action_id="action-cancelled",
            session_id="projection-session",
        )
        assert changed is True
        assert cancelled["status"] == "cancelled"
        assert cancelled["response"] == {
            "cancelled": True,
            "reason": "turn_ended",
        }
        repeated_cancel, changed = db.cancel_web_pending_action(
            action_id="action-cancelled",
            session_id="projection-session",
        )
        assert changed is False
        assert repeated_cancel["status"] == "cancelled"
    finally:
        db.close()


def test_session_db_lists_all_web_turn_projections_in_order():
    from core.spark_state import SessionDB

    db = SessionDB()
    try:
        db.ensure_session("projection-list-session", source="web", model="test")
        db.upsert_web_turn_projection(
            "turn-2",
            "projection-list-session",
            {"turn_id": "turn-2", "started_at": 2.0, "status": "completed"},
        )
        db.upsert_web_turn_projection(
            "turn-1",
            "projection-list-session",
            {"turn_id": "turn-1", "started_at": 1.0, "status": "completed"},
        )
        rows = db.list_web_turn_projections("projection-list-session")
        assert [row["turn_id"] for row in rows] == ["turn-2", "turn-1"]
        assert rows[0]["projection"]["status"] == "completed"
    finally:
        db.close()


def test_compute_changed_files_attributes_only_status_transitions():
    before = {
        "is_repo": True,
        "branch": "feature",
        "files": [{"path": "already.py", "status": "modified", "adds": 1, "dels": 0}],
    }
    after = {
        "is_repo": True,
        "branch": "feature",
        "files": [
            {"path": "already.py", "status": "modified", "adds": 2, "dels": 0},
            {"path": "new.py", "status": "added", "adds": 4, "dels": 0},
        ],
    }

    result = compute_changed_files(before, after)

    assert result["count"] == 2
    assert [item["path"] for item in result["files"]] == ["already.py", "new.py"]
    assert result["files"][0]["before"]["adds"] == 1
    assert "before" not in result
    assert "after" not in result


def test_compute_changed_files_reports_reverted_path():
    result = compute_changed_files(
        {"is_repo": True, "files": [{"path": "draft.md", "status": "added"}]},
        {"is_repo": True, "files": []},
    )

    assert result["files"] == [
        {
            "path": "draft.md",
            "before": {"path": "draft.md", "status": "added"},
            "after": None,
            "status": "reverted",
        }
    ]


def test_normalize_plan_is_revisioned_and_derives_status():
    result = normalize_plan(
        [
            {"id": "a", "content": "First", "status": "completed"},
            {"id": "b", "content": "Second", "status": "in_progress"},
        ],
        revision=3,
        markdown="## Plan",
        updated_at=10.5,
    )

    assert result == {
        "revision": 3,
        "steps": [
            {"id": "a", "content": "First", "status": "completed"},
            {"id": "b", "content": "Second", "status": "in_progress"},
        ],
        "status": "active",
        "markdown": "## Plan",
        "updated_at": 10.5,
    }
