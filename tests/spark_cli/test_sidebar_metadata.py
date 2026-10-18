"""P05 uses real profile databases and the production dashboard auth middleware."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.spark_state import SessionDB
from spark_cli.sidebar_metadata import DEFAULT_METADATA, MetadataConflict, SidebarMetadata
from spark_cli.sidebar_routes import (
    get_sidebar_db,
    get_sidebar_publisher,
    get_sidebar_settle_guard,
    router,
)


@pytest.fixture
def db(tmp_path):
    instance = SessionDB(tmp_path / "state.db")
    instance.create_session("upgrade-parent", "web")
    instance.create_session("upgrade-other", "workspace:alpha")
    yield instance
    instance.close()


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_sidebar_db] = lambda: db
    app.dependency_overrides[get_sidebar_settle_guard] = lambda: lambda _sid: None
    app.dependency_overrides[get_sidebar_publisher] = lambda: lambda _sid: None
    with TestClient(app) as client:
        yield client


def test_contract_defaults_fixture_and_restart(db, client):
    fixture = json.loads(
        (Path(__file__).parents[1] / "fixtures/app_upgrade/contracts-v1.json").read_text()
    )["sidebar"]
    response = client.get("/api/sidebar/threads").json()
    assert response["schema_version"] == fixture["schema_version"]
    assert response["entries"]["upgrade-parent"] == DEFAULT_METADATA
    desired = fixture["entries"]["upgrade-parent"]
    response = client.patch(
        "/api/sidebar/threads/upgrade-parent",
        json={"expected_revision": 0, **{k: v for k, v in desired.items() if k != "revision"}},
    )
    assert response.json()["metadata"] == desired
    other = SessionDB(db.db_path)
    try:
        assert SidebarMetadata(other).snapshot()["upgrade-parent"] == desired
        assert other.get_session("upgrade-parent")["source"] == "web"
        assert other.get_messages("upgrade-parent") == []
    finally:
        other.close()
    conflict = client.patch(
        "/api/sidebar/threads/upgrade-parent", json={"expected_revision": 0, "pinned": False}
    )
    assert conflict.status_code == fixture["conflict_status"]
    assert conflict.json()["current"] == desired


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"expected_revision": 0},
        {"expected_revision": -1, "pinned": True},
        {"expected_revision": True, "pinned": True},
        {"expected_revision": "0", "pinned": True},
        {"expected_revision": 0, "pinned": "true"},
        {"expected_revision": 0, "pinned": None},
        {"expected_revision": 0, "settled": None},
        {"expected_revision": 0, "other": 1},
        {"expected_revision": 0, "position": "1"},
        {"expected_revision": 0, "revision": 10},
    ],
)
def test_rejects_malformed_input(client, body):
    assert client.patch("/api/sidebar/threads/upgrade-parent", json=body).status_code == 422


def test_exact_ownership_and_profile_isolation(db, client, tmp_path):
    for sid in ("upgrade", "other-profile-id", "missing"):
        assert (
            client.patch(
                f"/api/sidebar/threads/{sid}", json={"expected_revision": 0, "pinned": True}
            ).status_code
            == 404
        )
    other = SessionDB(tmp_path / "profile-b/state.db")
    other.create_session("upgrade-parent", "web")
    try:
        client.patch(
            "/api/sidebar/threads/upgrade-parent", json={"expected_revision": 0, "pinned": True}
        )
        assert SidebarMetadata(other).snapshot()["upgrade-parent"] == DEFAULT_METADATA
        first_scope = client.get("/api/sidebar/threads").json()["preference_scope"]
        client.app.dependency_overrides[get_sidebar_db] = lambda: other
        assert client.get("/api/sidebar/threads").json()["preference_scope"] != first_scope
    finally:
        other.close()


def test_event_is_atomic_and_publish_observes_committed_revision(db, client):
    published = []
    client.app.dependency_overrides[get_sidebar_publisher] = lambda: (
        lambda sid: published.append((sid, SidebarMetadata(db).snapshot()[sid]["revision"]))
    )
    assert (
        client.patch(
            "/api/sidebar/threads/upgrade-parent", json={"expected_revision": 0, "pinned": True}
        ).status_code
        == 200
    )
    assert published == [("upgrade-parent", 1)]
    events = db.get_session_events("upgrade-parent")
    assert events[-1]["event_type"] == "sidebar.metadata_changed"
    assert events[-1]["payload"]["revision"] == 1
    # Persistence error rolls metadata back and never publishes success.
    original = db._append_session_event_row
    db._append_session_event_row = lambda *args: (_ for _ in ()).throw(RuntimeError("disk failure"))
    with pytest.raises(RuntimeError, match="disk failure"):
        SidebarMetadata(db).patch("upgrade-parent", 1, {"settled": True})
    db._append_session_event_row = original
    assert SidebarMetadata(db).snapshot()["upgrade-parent"]["revision"] == 1


def test_two_connections_compare_and_swap(db):
    other = SessionDB(db.db_path)
    stores = [SidebarMetadata(db), SidebarMetadata(other)]

    def update(store):
        try:
            return store.patch("upgrade-parent", 0, {"pinned": True})
        except MetadataConflict as exc:
            return exc.current

    try:
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(update, stores))
        assert [r["revision"] for r in results] == [1, 1]
        assert (
            len(
                [
                    e
                    for e in db.get_session_events("upgrade-parent")
                    if e["event_type"] == "sidebar.metadata_changed"
                ]
            )
            == 1
        )
    finally:
        other.close()


def test_pending_decision_and_live_projection_block_settle(db, client):
    db.create_web_pending_action(
        action_id="decision",
        session_id="upgrade-parent",
        turn_id="run",
        kind="approval",
        payload={},
    )
    body = {"expected_revision": 0, "settled": True}
    response = client.patch("/api/sidebar/threads/upgrade-parent", json=body)
    assert response.status_code == 409
    assert "pending decision" in response.json()["detail"]
    assert client.get("/api/sidebar/threads").json()["attention"]["upgrade-parent"][
        "pending_decision"
    ]
    db.resolve_web_pending_action(action_id="decision", session_id="upgrade-parent", response=True)
    db.upsert_web_turn_projection(
        "run", "upgrade-parent", {"turn_active": True, "state": "running"}
    )
    assert client.patch("/api/sidebar/threads/upgrade-parent", json=body).status_code == 409
    db.upsert_web_turn_projection(
        "run", "upgrade-parent", {"turn_active": False, "state": "completed"}
    )
    assert client.patch("/api/sidebar/threads/upgrade-parent", json=body).status_code == 200


def test_unwired_guard_fails_closed_and_unsettle_is_safe(client):
    client.app.dependency_overrides.pop(get_sidebar_settle_guard)
    assert (
        client.patch(
            "/api/sidebar/threads/upgrade-parent", json={"expected_revision": 0, "settled": True}
        ).status_code
        == 409
    )
    assert (
        client.patch(
            "/api/sidebar/threads/upgrade-parent", json={"expected_revision": 0, "settled": False}
        ).status_code
        == 200
    )


def test_live_guard_and_revision_checked_undo_preserve_newer_run(db, client):
    response = client.patch(
        "/api/sidebar/threads/upgrade-parent", json={"expected_revision": 0, "settled": True}
    )
    assert response.status_code == 200
    client.patch(
        "/api/sidebar/threads/upgrade-parent", json={"expected_revision": 1, "pinned": True}
    )
    db.upsert_web_turn_projection("newer-run", "upgrade-parent", {"turn_active": True})
    undo = client.patch(
        "/api/sidebar/threads/upgrade-parent", json={"expected_revision": 1, "settled": False}
    )
    assert undo.status_code == 409
    assert undo.json()["current"]["pinned"]
    assert db.get_web_turn_projection("newer-run")["projection"]["turn_active"]
    client.app.dependency_overrides[get_sidebar_settle_guard] = lambda: (
        lambda _sid: "Owned run is still live"
    )
    assert (
        client.patch(
            "/api/sidebar/threads/upgrade-other", json={"expected_revision": 0, "settled": True}
        ).json()["detail"]
        == "Owned run is still live"
    )


def test_session_delete_cascades_metadata(db):
    store = SidebarMetadata(db)
    store.patch("upgrade-parent", 0, {"pinned": True})
    db.delete_session("upgrade-parent")
    assert "upgrade-parent" not in store.snapshot()
    assert db._conn.execute("SELECT COUNT(*) FROM sidebar_thread_metadata").fetchone()[0] == 0


def test_production_auth_middleware_protects_router(db, monkeypatch):
    from spark_cli import web_server

    monkeypatch.setattr(
        web_server, "load_config", lambda: {"dashboard": {"require_auth_nonlocal": True}}
    )
    monkeypatch.setattr(
        web_server, "get_configured_dashboard_secret", lambda: "test-sidebar-secret"
    )
    app = FastAPI()
    app.add_middleware(web_server.DashboardAPIAuthMiddleware)
    app.include_router(router)
    app.dependency_overrides[get_sidebar_db] = lambda: db
    app.dependency_overrides[get_sidebar_publisher] = lambda: lambda _sid: None
    with TestClient(app, client=("203.0.113.10", 1234)) as client:
        assert client.get("/api/sidebar/threads").status_code == 401
        assert (
            client.patch(
                "/api/sidebar/threads/upgrade-parent", json={"expected_revision": 0, "pinned": True}
            ).status_code
            == 401
        )
        headers = {"Authorization": "Bearer test-sidebar-secret"}
        assert client.get("/api/sidebar/threads", headers=headers).status_code == 200
        assert (
            client.patch(
                "/api/sidebar/threads/upgrade-parent",
                headers=headers,
                json={"expected_revision": 0, "pinned": True},
            ).status_code
            == 200
        )


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_nonfinite_positions_return_json_validation_error(client, value):
    response = client.patch(
        "/api/sidebar/threads/upgrade-parent",
        content='{"expected_revision":0,"position":' + value + "}",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]


def test_owned_child_decision_blocks_parent_and_stays_nested(db, client):
    db.create_session("child", "delegate")
    db.create_subagent_run(
        {
            "id": "child-run",
            "parent_session_id": "upgrade-parent",
            "child_session_id": "child",
            "status": "completed",
            "name": "Child",
        }
    )
    db.create_web_pending_action(
        action_id="child-decision",
        session_id="child",
        turn_id="child-turn",
        kind="input",
        payload={},
    )
    attention = client.get("/api/sidebar/threads").json()["attention"]
    assert attention["upgrade-parent"]["pending_decision"]
    assert "child" not in attention
    response = client.patch(
        "/api/sidebar/threads/upgrade-parent", json={"expected_revision": 0, "settled": True}
    )
    assert response.status_code == 409
    assert "pending decision" in response.json()["detail"]


def test_compression_family_decision_blocks_settle(db, client):
    db._execute_write(
        lambda conn: conn.execute(
            "UPDATE sessions SET end_reason='compression' WHERE id='upgrade-parent'"
        )
    )
    db.create_session("compressed-leaf", "web", parent_session_id="upgrade-parent")
    db.create_web_pending_action(
        action_id="compressed-decision",
        session_id="compressed-leaf",
        turn_id="leaf-turn",
        kind="input",
        payload={},
    )
    assert client.get("/api/sidebar/threads").json()["attention"]["upgrade-parent"][
        "pending_decision"
    ]
    assert (
        client.patch(
            "/api/sidebar/threads/upgrade-parent", json={"expected_revision": 0, "settled": True}
        ).status_code
        == 409
    )


def test_stale_settle_returns_current_even_if_live_guard_blocks(client):
    client.patch(
        "/api/sidebar/threads/upgrade-parent", json={"expected_revision": 0, "pinned": True}
    )
    client.app.dependency_overrides.pop(get_sidebar_settle_guard)
    response = client.patch(
        "/api/sidebar/threads/upgrade-parent", json={"expected_revision": 0, "settled": True}
    )
    assert response.status_code == 409
    assert response.json()["current"]["revision"] == 1


def test_created_child_without_transcript_keeps_parent_visible_and_blocks_settle(db, client):
    db.create_subagent_run(
        {
            "id": "starting-child",
            "parent_session_id": "upgrade-parent",
            "status": "created",
            "name": "Starting child",
        }
    )
    attention = client.get("/api/sidebar/threads").json()["attention"]
    assert attention["upgrade-parent"]["running"]
    assert (
        client.patch(
            "/api/sidebar/threads/upgrade-parent", json={"expected_revision": 0, "settled": True}
        ).status_code
        == 409
    )


@pytest.mark.parametrize("status", ["working", "stopping"])
def test_canonical_live_child_states_block_settlement(db, client, status):
    db.create_subagent_run({"id": "live-child", "parent_session_id": "upgrade-parent", "status": status})
    assert client.get("/api/sidebar/threads").json()["attention"]["upgrade-parent"]["running"]
    response = client.patch(
        "/api/sidebar/threads/upgrade-parent", json={"expected_revision": 0, "settled": True}
    )
    assert response.status_code == 409


def test_integrated_guard_covers_compression_alias_without_database_reentry(client, monkeypatch):
    from spark_cli import web_server

    monkeypatch.setattr(web_server, "_web_active_turns", {
        "compressed-leaf": SimpleNamespace(
            active_agent_session_id="compressed-leaf", session_aliases={"upgrade-parent"}
        )
    })
    monkeypatch.setattr(web_server, "_web_turn_aliases", {})
    monkeypatch.setattr(web_server, "_web_agents", {})
    def no_database_lookup(_sid):
        raise AssertionError("Guard must not open SQLite inside a metadata write")
    monkeypatch.setattr(web_server, "_resolve_web_turn_ids", no_database_lookup)
    client.app.dependency_overrides[get_sidebar_settle_guard] = lambda: web_server._sidebar_settle_block_reason
    blocked = client.patch(
        "/api/sidebar/threads/upgrade-parent", json={"expected_revision": 0, "settled": True}
    )
    assert blocked.status_code == 409
    assert "live work" in blocked.json()["detail"]
    web_server._web_active_turns.clear()
    settled = client.patch(
        "/api/sidebar/threads/upgrade-parent", json={"expected_revision": 0, "settled": True}
    )
    assert settled.status_code == 200


def test_integrated_guard_covers_child_after_parent_turn_finishes(client, monkeypatch):
    from spark_cli import web_server

    monkeypatch.setattr(web_server, "_web_active_turns", {})
    monkeypatch.setattr(web_server, "_web_turn_aliases", {})
    monkeypatch.setattr(web_server, "_web_agents", {
        "upgrade-parent": SimpleNamespace(_active_children=[object()])
    })
    client.app.dependency_overrides[get_sidebar_settle_guard] = lambda: web_server._sidebar_settle_block_reason
    response = client.patch(
        "/api/sidebar/threads/upgrade-parent", json={"expected_revision": 0, "settled": True}
    )
    assert response.status_code == 409
    assert "delegated work" in response.json()["detail"]


def test_compressed_child_decision_remains_owned_by_parent(db, client):
    db.create_session("child", "delegate")
    db._execute_write(
        lambda conn: conn.execute("UPDATE sessions SET end_reason='compression' WHERE id='child'")
    )
    db.create_session("child-leaf", "delegate", parent_session_id="child")
    db.create_subagent_run(
        {
            "id": "compressed-child",
            "parent_session_id": "upgrade-parent",
            "child_session_id": "child",
            "status": "completed",
            "name": "Child",
        }
    )
    db.create_web_pending_action(
        action_id="compressed-child-input",
        session_id="child-leaf",
        turn_id="child-turn",
        kind="input",
        payload={},
    )
    attention = client.get("/api/sidebar/threads").json()["attention"]
    assert attention["upgrade-parent"]["pending_decision"]
    assert "child" not in attention and "child-leaf" not in attention
    assert (
        client.patch(
            "/api/sidebar/threads/upgrade-parent", json={"expected_revision": 0, "settled": True}
        ).status_code
        == 409
    )
