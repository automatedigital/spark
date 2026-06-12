"""Tests for the preview-pane browser-chrome features (PLAN.md 2b wave 2 — Group 1).

Covers the ``AgentBrowserSession`` chrome methods (viewport presets, dark-mode
emulation, tab multiplexing, downloads surfacing) and the workspace routes that
expose them. The agent-browser CLI runtime is mocked throughout — no real
browser is ever spawned.
"""

from __future__ import annotations

import json

import pytest

from spark_cli import preview_agent_browser as pab


@pytest.fixture
def session(monkeypatch):
    """An AgentBrowserSession with the CLI binary + ``_run`` mocked out."""
    monkeypatch.setattr(pab, "_agent_browser_bin", lambda: "/fake/agent-browser")
    calls: list[list[str]] = []

    def fake_run(self, args, *, timeout=pab._COMMAND_TIMEOUT):
        calls.append(list(args))
        return {}

    monkeypatch.setattr(pab.AgentBrowserSession, "_run", fake_run)
    sess = pab.AgentBrowserSession("proj")
    sess._calls = calls  # type: ignore[attr-defined]
    return sess


def test_set_viewport_updates_state_and_runs_cli(session):
    session._calls.clear()
    session.set_viewport(390, 844)
    assert session.viewport == (390, 844)
    assert ["set", "viewport", "390", "844"] in session._calls


def test_set_viewport_clamps_nonpositive(session):
    session.set_viewport(0, -5)
    assert session.viewport == (1, 1)


def test_set_emulated_media_dark(session):
    session._calls.clear()
    session.set_emulated_media(dark=True)
    call = next(c for c in session._calls if c[0] == "cdp")
    assert call[1] == "Emulation.setEmulatedMedia"
    params = json.loads(call[2])
    assert params["features"] == [{"name": "prefers-color-scheme", "value": "dark"}]


def test_set_emulated_media_clear(session):
    session._calls.clear()
    session.set_emulated_media(dark=None)
    call = next(c for c in session._calls if c[0] == "cdp")
    assert json.loads(call[2])["features"] == []


def test_downloads_dir_under_spark_home(session):
    from core.spark_constants import get_spark_home

    assert str(session.downloads_dir).startswith(str(get_spark_home()))
    assert session.downloads_dir.name == "downloads"
    assert "workspace" in session.downloads_dir.parts


def test_list_downloads_newest_first_skips_partials(session):
    d = session.downloads_dir
    d.mkdir(parents=True, exist_ok=True)
    (d / "a.txt").write_text("a")
    (d / "b.pdf").write_text("b")
    (d / "wip.crdownload").write_text("partial")
    import os
    import time

    os.utime(d / "a.txt", (time.time() - 100, time.time() - 100))
    names = [x["name"] for x in session.list_downloads()]
    assert "wip.crdownload" not in names
    assert names[0] == "b.pdf"  # newest first
    assert set(names) == {"a.txt", "b.pdf"}


def test_list_downloads_empty_when_missing(session):
    assert session.list_downloads() == []


def test_list_tabs_via_cdp(monkeypatch, session):
    monkeypatch.setattr(
        session,
        "_cdp_targets",
        lambda: [
            {"id": "T1", "title": "One", "url": "https://a", "_active": True},
            {"id": "T2", "title": "Two", "url": "https://b"},
        ],
    )
    tabs = session.list_tabs()
    assert [t["id"] for t in tabs] == ["T1", "T2"]
    assert tabs[0]["active"] is True
    assert tabs[1]["active"] is False


def test_list_tabs_empty_when_cdp_unavailable(monkeypatch, session):
    monkeypatch.setattr(session, "_cdp_targets", lambda: [])
    assert session.list_tabs() == []


# ── Route tests (mock the streamed session) ──────────────────────────────────


class _FakeSession:
    def __init__(self):
        self.viewport = (1280, 800)
        self.current_url = "https://ex.com"
        self.title = "Ex"
        self.dark = None
        self.tabs = [{"id": "T1", "title": "One", "url": "https://ex.com", "active": True}]
        self.downloads = [{"name": "f.pdf", "size": 12, "mtime": 1.0}]

    def set_viewport(self, w, h):
        self.viewport = (w, h)

    def set_emulated_media(self, *, dark=None):
        self.dark = dark

    def list_tabs(self):
        return self.tabs

    def new_tab(self, url="about:blank"):
        return {"url": url, "title": ""}

    def switch_tab(self, target_id):
        return {"url": self.current_url, "title": self.title}

    def close_tab(self, target_id):
        return None

    def list_downloads(self):
        return self.downloads


@pytest.fixture
def client(monkeypatch):
    fastapi = pytest.importorskip("fastapi")
    from starlette.testclient import TestClient

    import spark_cli.workspace_routes as wr
    from spark_cli.preview_agent_browser import AgentBrowserUnavailable

    fake = _FakeSession()
    monkeypatch.setattr(wr, "_project_dir", lambda slug: None)
    monkeypatch.setattr(
        wr, "_streamed_session", lambda slug, **k: (fake, AgentBrowserUnavailable)
    )
    app = fastapi.FastAPI()
    wr.register_workspace_routes(app)
    tc = TestClient(app)
    tc._fake = fake  # type: ignore[attr-defined]
    return tc


def test_route_viewport(client):
    r = client.post("/api/workspace/projects/proj/preview/stream/viewport", json={"width": 390, "height": 844})
    assert r.status_code == 200
    assert r.json()["width"] == 390
    assert client._fake.viewport == (390, 844)


def test_route_emulate_dark(client):
    r = client.post("/api/workspace/projects/proj/preview/stream/emulate", json={"dark": True})
    assert r.status_code == 200
    assert client._fake.dark is True


def test_route_tabs_list(client):
    r = client.get("/api/workspace/projects/proj/preview/stream/tabs")
    assert r.status_code == 200
    assert r.json()["tabs"][0]["id"] == "T1"


def test_route_tab_new(client):
    r = client.post(
        "/api/workspace/projects/proj/preview/stream/tabs",
        json={"action": "new", "url": "https://x.com"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_route_tab_switch_requires_target(client):
    r = client.post(
        "/api/workspace/projects/proj/preview/stream/tabs", json={"action": "switch"}
    )
    assert r.status_code == 400


def test_route_downloads(client):
    r = client.get("/api/workspace/projects/proj/preview/stream/downloads")
    assert r.status_code == 200
    assert r.json()["downloads"][0]["name"] == "f.pdf"


def test_route_tabs_degrade_when_backend_lacks_support(client, monkeypatch):
    # A backend without list_tabs (e.g. Playwright) returns an empty list, not 500.
    import spark_cli.workspace_routes as wr
    from spark_cli.preview_agent_browser import AgentBrowserUnavailable

    class _Bare:
        viewport = (1280, 800)

    monkeypatch.setattr(
        wr, "_streamed_session", lambda slug, **k: (_Bare(), AgentBrowserUnavailable)
    )
    r = client.get("/api/workspace/projects/proj/preview/stream/tabs")
    assert r.status_code == 200
    assert r.json()["tabs"] == []
