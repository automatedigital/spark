"""Tests for the agent ⇄ user collaboration features (PLAN.md 2b wave 2 — Group 2).

Covers the take-over/pause control module + its gating of the agent's browser
actions, the element picker + GIF recording session methods, and the routes
that expose them. The agent-browser runtime is mocked throughout.
"""

from __future__ import annotations

import json

import pytest

from spark_cli import preview_agent_browser as pab
from tools import browser_takeover

# ── Take-over / pause control ─────────────────────────────────────────────────


def test_takeover_default_not_paused(monkeypatch):
    monkeypatch.delenv("SPARK_BROWSER_PREVIEW_SESSION", raising=False)
    assert browser_takeover.is_paused(slug="proj") is False
    assert browser_takeover.get_state(slug="proj")["paused"] is False


def test_takeover_set_and_read_roundtrip(monkeypatch):
    monkeypatch.delenv("SPARK_BROWSER_PREVIEW_SESSION", raising=False)
    browser_takeover.set_paused(True, slug="proj")
    assert browser_takeover.is_paused(slug="proj") is True
    state = browser_takeover.get_state(slug="proj")
    assert state["paused"] is True and state["ts"] > 0
    browser_takeover.set_paused(False, slug="proj")
    assert browser_takeover.is_paused(slug="proj") is False


def test_takeover_path_under_spark_home(monkeypatch):
    from core.spark_constants import get_spark_home

    browser_takeover.set_paused(True, slug="proj")
    path = browser_takeover._control_path("proj")
    assert str(path).startswith(str(get_spark_home()))
    assert path.name == "control.json"


def test_takeover_env_binding_slug(monkeypatch):
    monkeypatch.setenv("SPARK_BROWSER_PREVIEW_SESSION", "spark-preview-mysite")
    browser_takeover.set_paused(True)
    # The bare slug must address the same control file the env binding wrote.
    assert browser_takeover.is_paused(slug="mysite") is True


# ── browser_tool gating (agent actions defer while paused) ────────────────────


def test_browser_click_defers_when_paused(monkeypatch):
    monkeypatch.setenv("SPARK_BROWSER_PREVIEW_SESSION", "spark-preview-ws")
    browser_takeover.set_paused(True, slug="ws")
    import tools.browser_tool as bt

    monkeypatch.setattr(bt, "_is_camofox_mode", lambda: False)
    called = {"ran": False}
    monkeypatch.setattr(
        bt, "_run_browser_command", lambda *a, **k: called.__setitem__("ran", True) or {}
    )
    out = json.loads(bt.browser_click("@e5", task_id="t"))
    assert out["paused"] is True
    assert called["ran"] is False  # the click must NOT have been dispatched


def test_browser_click_proceeds_when_not_paused(monkeypatch):
    monkeypatch.setenv("SPARK_BROWSER_PREVIEW_SESSION", "spark-preview-ws")
    browser_takeover.set_paused(False, slug="ws")
    import tools.browser_tool as bt

    monkeypatch.setattr(bt, "_is_camofox_mode", lambda: False)
    monkeypatch.setattr(bt, "_run_browser_command", lambda *a, **k: {"success": True})
    monkeypatch.setattr(bt.browser_permission_gate, "gate_enabled", lambda: False)
    out = json.loads(bt.browser_click("@e5", task_id="t"))
    assert out.get("success") is True


# ── Session picker + GIF recording ────────────────────────────────────────────


@pytest.fixture
def session(monkeypatch):
    monkeypatch.setattr(pab, "_agent_browser_bin", lambda: "/fake/agent-browser")
    monkeypatch.setattr(pab.AgentBrowserSession, "_run", lambda self, args, **k: {})
    return pab.AgentBrowserSession("proj")


def test_pick_element_returns_descriptor(monkeypatch, session):
    monkeypatch.setattr(
        session,
        "_eval",
        lambda expr: {"selector": "#go", "tag": "button", "name": "Go", "text": "Go"},
    )
    session.current_url = "https://ex.com"
    info = session.pick_element(10, 20)
    assert info["selector"] == "#go"
    assert info["url"] == "https://ex.com"


def test_pick_element_empty_when_eval_denied(monkeypatch, session):
    def boom(expr):
        raise pab.AgentBrowserUnavailable("denied")

    monkeypatch.setattr(session, "_eval", boom)
    assert session.pick_element(1, 2) == {}


def test_record_gif_writes_file(monkeypatch, session):
    # Provide a tiny valid PNG for each captured frame.
    import io

    Image = pytest.importorskip("PIL.Image", reason="Pillow not installed")

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buf, format="PNG")
    png = buf.getvalue()
    monkeypatch.setattr(session, "screenshot", lambda: png)
    monkeypatch.setattr("time.sleep", lambda *_: None)
    out = session.record_gif(frames=3, interval=0.01)
    assert out is not None and out.exists() and out.suffix == ".gif"
    assert str(out.parent) == str(session.downloads_dir)


def test_record_gif_none_without_pillow(monkeypatch, session):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("no pillow")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert session.record_gif(frames=2) is None


# ── Routes ────────────────────────────────────────────────────────────────────


class _FakeSession:
    def __init__(self):
        self.viewport = (1280, 800)
        self.current_url = "https://ex.com"
        self.downloads_dir = None

    def pick_element(self, x, y):
        return {"selector": "#go", "url": self.current_url}

    def screenshot(self):
        return b"\x89PNG\r\n"

    def record_gif(self, *, frames=12, interval=0.4):
        from pathlib import Path

        return Path("recording-1.gif")


@pytest.fixture
def client(monkeypatch):
    fastapi = pytest.importorskip("fastapi")
    from starlette.testclient import TestClient

    import spark_cli.workspace_routes as wr
    from spark_cli.preview_agent_browser import AgentBrowserUnavailable

    monkeypatch.setattr(wr, "_project_dir", lambda slug: None)
    monkeypatch.setattr(
        wr, "_streamed_session", lambda slug, **k: (_FakeSession(), AgentBrowserUnavailable)
    )
    app = fastapi.FastAPI()
    wr.register_workspace_routes(app)
    return TestClient(app)


def test_route_takeover_toggle(client, monkeypatch):
    r = client.post("/api/workspace/projects/proj/preview/stream/takeover", json={"paused": True})
    assert r.status_code == 200 and r.json()["paused"] is True
    s = client.get("/api/workspace/projects/proj/preview/stream/takeover")
    assert s.status_code == 200 and s.json()["paused"] is True


def test_route_pick(client):
    r = client.post("/api/workspace/projects/proj/preview/stream/pick", json={"x": 10, "y": 20})
    assert r.status_code == 200
    assert r.json()["element"]["selector"] == "#go"


def test_route_screenshot(client):
    r = client.get("/api/workspace/projects/proj/preview/stream/screenshot")
    assert r.status_code == 200
    assert "png_base64" in r.json()


def test_route_record(client):
    r = client.post("/api/workspace/projects/proj/preview/stream/record", json={"frames": 3})
    assert r.status_code == 200
    assert r.json()["name"] == "recording-1.gif"


def test_route_record_degrades_when_no_encoder(client, monkeypatch):
    import spark_cli.workspace_routes as wr
    from spark_cli.preview_agent_browser import AgentBrowserUnavailable

    class _NoGif(_FakeSession):
        def record_gif(self, *, frames=12, interval=0.4):
            return None

    monkeypatch.setattr(
        wr, "_streamed_session", lambda slug, **k: (_NoGif(), AgentBrowserUnavailable)
    )
    r = client.post("/api/workspace/projects/proj/preview/stream/record", json={})
    assert r.status_code == 501  # graceful, not a crash
