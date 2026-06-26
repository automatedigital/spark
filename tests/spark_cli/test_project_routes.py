"""Tests for canonical Project routes and workspace compatibility aliases."""

from __future__ import annotations

import pytest


_MACHINE_FIELDS = {"path", "cwd", "source", "url"}


@pytest.fixture
def client():
    fastapi = pytest.importorskip("fastapi")
    from starlette.testclient import TestClient

    from spark_cli.project_routes import register_project_routes

    app = fastapi.FastAPI()
    register_project_routes(app)
    return TestClient(app)


def test_canonical_project_routes_share_workspace_behavior(client):
    created = client.post("/api/projects", json={"name": "Project Route Smoke"}).json()

    assert created["ok"] is True
    assert created["slug"] == "Project-Route-Smoke"

    canonical = client.get("/api/projects").json()
    compat = client.get("/api/workspace/projects").json()

    assert [p["slug"] for p in canonical["projects"]] == [
        p["slug"] for p in compat["projects"]
    ]
    assert "Project-Route-Smoke" in [p["slug"] for p in canonical["projects"]]


def test_canonical_project_templates_alias(client):
    canonical = client.get("/api/project-templates")
    compat = client.get("/api/workspace/project-templates")

    assert canonical.status_code == 200
    assert canonical.json() == compat.json()


def _reader_facing_text(payload):
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key not in _MACHINE_FIELDS:
                yield key
                yield from _reader_facing_text(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from _reader_facing_text(item)
    elif isinstance(payload, str):
        yield payload


def test_canonical_project_responses_avoid_workspace_language(client):
    client.post("/api/projects", json={"name": "Language Guard"})

    for path in ("/api/projects", "/api/project-templates"):
        resp = client.get(path)
        assert resp.status_code == 200
        text = "\n".join(_reader_facing_text(resp.json())).lower()
        assert "workspace" not in text
