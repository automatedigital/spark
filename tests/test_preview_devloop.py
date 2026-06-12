"""Tests for dev-loop integration (PLAN.md 2b wave 2 — Group 3).

Covers the CDP console/network capture parser, the session's graceful
degradation when capture is unavailable, and the console + dev-server-detection
routes. No real browser or CDP socket is used.
"""

from __future__ import annotations

import pytest

from spark_cli import preview_agent_browser as pab


# ── ConsoleCapture event parsing ──────────────────────────────────────────────


def _capture():
    return pab.ConsoleCapture("ws://127.0.0.1:0/devtools/page/x")


def test_console_api_called_recorded():
    cap = _capture()
    cap._handle(
        {
            "method": "Runtime.consoleAPICalled",
            "params": {"type": "error", "args": [{"value": "boom"}]},
        }
    )
    entries = cap.entries()
    assert entries[-1]["kind"] == "console"
    assert entries[-1]["level"] == "error"
    assert "boom" in entries[-1]["text"]


def test_exception_thrown_recorded():
    cap = _capture()
    cap._handle(
        {
            "method": "Runtime.exceptionThrown",
            "params": {"exceptionDetails": {"text": "Uncaught TypeError: x"}},
        }
    )
    e = cap.entries()[-1]
    assert e["kind"] == "exception" and e["level"] == "error"
    assert "TypeError" in e["text"]


def test_network_4xx_recorded_but_2xx_ignored():
    cap = _capture()
    cap._handle(
        {"method": "Network.responseReceived", "params": {"response": {"status": 200, "url": "/ok"}}}
    )
    cap._handle(
        {"method": "Network.responseReceived", "params": {"response": {"status": 500, "url": "/boom"}}}
    )
    entries = cap.entries()
    assert len(entries) == 1
    assert entries[0]["kind"] == "network" and "500" in entries[0]["text"]


def test_log_entry_added_recorded():
    cap = _capture()
    cap._handle(
        {
            "method": "Log.entryAdded",
            "params": {"entry": {"level": "warning", "text": "deprecated", "source": "rendering"}},
        }
    )
    e = cap.entries()[-1]
    assert e["kind"] == "console" and e["text"] == "deprecated"


def test_console_entries_since_seq_filter():
    cap = _capture()
    cap._record("console", "log", "one")
    first = cap.entries()[-1]["seq"]
    cap._record("console", "log", "two")
    later = cap.entries(since_seq=first)
    assert [e["text"] for e in later] == ["two"]


def test_console_buffer_is_bounded():
    cap = _capture()
    for i in range(pab._CONSOLE_BUFFER_MAX + 50):
        cap._record("console", "log", str(i))
    assert len(cap.entries(limit=10_000)) == pab._CONSOLE_BUFFER_MAX


# ── Session graceful degradation ─────────────────────────────────────────────


def test_session_console_entries_empty_without_cdp(monkeypatch):
    monkeypatch.setattr(pab, "_agent_browser_bin", lambda: "/fake/agent-browser")
    monkeypatch.setattr(pab.AgentBrowserSession, "_run", lambda self, args, **k: {})
    sess = pab.AgentBrowserSession("proj")
    monkeypatch.setattr(sess, "cdp_url", lambda: None)  # no CDP → no capture
    assert sess.console_entries() == []


# ── Routes ────────────────────────────────────────────────────────────────────


@pytest.fixture
def client(monkeypatch):
    fastapi = pytest.importorskip("fastapi")
    from starlette.testclient import TestClient

    import spark_cli.workspace_routes as wr
    from spark_cli.preview_agent_browser import AgentBrowserUnavailable

    class _FakeSession:
        viewport = (1280, 800)

        def console_entries(self, *, since_seq=0, limit=500):
            return [{"seq": 1, "ts": 1.0, "kind": "network", "level": "error", "text": "500 /x", "detail": {}}]

    monkeypatch.setattr(wr, "_project_dir", lambda slug: __import__("pathlib").Path("/tmp/proj"))
    monkeypatch.setattr(
        wr, "_streamed_session", lambda slug, **k: (_FakeSession(), AgentBrowserUnavailable)
    )
    app = fastapi.FastAPI()
    wr.register_workspace_routes(app)
    return TestClient(app)


def test_route_console(client):
    r = client.get("/api/workspace/projects/proj/preview/stream/console")
    assert r.status_code == 200
    assert r.json()["entries"][0]["kind"] == "network"


def test_route_console_degrades_for_bare_backend(client, monkeypatch):
    import spark_cli.workspace_routes as wr
    from spark_cli.preview_agent_browser import AgentBrowserUnavailable

    class _Bare:
        viewport = (1280, 800)

    monkeypatch.setattr(
        wr, "_streamed_session", lambda slug, **k: (_Bare(), AgentBrowserUnavailable)
    )
    r = client.get("/api/workspace/projects/proj/preview/stream/console")
    assert r.status_code == 200 and r.json()["entries"] == []


def test_route_detect_servers(client, monkeypatch):
    import spark_cli.workspace_routes as wr

    monkeypatch.setattr(wr, "_list_loopback_listeners", lambda: [(111, 5173), (222, 5173)])
    monkeypatch.setattr(wr, "_process_cwd", lambda pid: __import__("pathlib").Path("/tmp/proj"))
    monkeypatch.setattr(wr, "_path_is_inside", lambda cwd, parent: True)
    monkeypatch.setattr(wr, "_probe_preview_url", lambda url: True)
    r = client.get("/api/workspace/projects/proj/preview/detect-servers")
    assert r.status_code == 200
    servers = r.json()["servers"]
    # Deduped by port.
    assert servers == [{"url": "http://127.0.0.1:5173", "port": 5173}]
