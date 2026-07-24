"""Tests for workspace preview port detection (src/spark_cli/workspace_routes.py)."""

from __future__ import annotations

import json
from pathlib import Path

from spark_cli import workspace_routes as w


def test_declared_port_from_env(tmp_path: Path):
    (tmp_path / ".env").write_text("FOO=bar\nPORT=3001\n")
    assert w._declared_project_port(tmp_path) == 3001


def test_declared_port_from_vite_config(tmp_path: Path):
    (tmp_path / "vite.config.ts").write_text("export default { server: { port: 5180 } }")
    assert w._declared_project_port(tmp_path) == 5180


def test_declared_port_from_package_script(tmp_path: Path):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"dev": "next dev -p 4321"}}))
    assert w._declared_project_port(tmp_path) == 4321


def test_declared_port_from_compose(tmp_path: Path):
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  web:\n    ports:\n      - \"8080:80\"\n"
    )
    assert w._declared_project_port(tmp_path) == 8080


def test_declared_port_none_when_absent(tmp_path: Path):
    assert w._declared_project_port(tmp_path) is None


def test_canonical_probe_url_normalizes_wildcard_hosts():
    assert w._canonical_probe_url("http://0.0.0.0:5173/") == "http://127.0.0.1:5173/"
    assert w._canonical_probe_url("http://localhost:3000") == "http://127.0.0.1:3000"
    assert w._canonical_probe_url("http://[::1]:8080/x") == "http://127.0.0.1:8080/x"
    # external host preserved
    assert w._canonical_probe_url("http://example.com:443") == "http://example.com:443"


def test_capture_bound_url_adopts_new_port(monkeypatch):
    events: list[dict] = []
    monkeypatch.setattr(w, "_preview_emit", lambda slug, ev: events.append(ev))
    session = {"slug": "x", "status": "running", "url": "http://127.0.0.1:4173", "port": 4173}
    w._capture_bound_url_from_log("x", session, "  ➜  Local:   http://127.0.0.1:5173/")
    assert session["port"] == 5173
    assert session["url"] == "http://127.0.0.1:5173/"
    assert [e["type"] for e in events] == ["state", "refresh"]


def test_capture_bound_url_noop_when_same_port(monkeypatch):
    events: list[dict] = []
    monkeypatch.setattr(w, "_preview_emit", lambda slug, ev: events.append(ev))
    session = {"slug": "x", "status": "running", "url": "http://127.0.0.1:5173", "port": 5173}
    w._capture_bound_url_from_log("x", session, "Local: http://127.0.0.1:5173/")
    assert events == []


def test_capture_bound_url_respects_port_lock(monkeypatch):
    events: list[dict] = []
    monkeypatch.setattr(w, "_preview_emit", lambda slug, ev: events.append(ev))
    session = {"slug": "x", "status": "running", "url": "http://127.0.0.1:4173", "port": 4173, "port_locked": True}
    w._capture_bound_url_from_log("x", session, "Local: http://127.0.0.1:5173/")
    assert events == []
    assert session["port"] == 4173


def test_reprobe_adopts_new_port_on_restart(monkeypatch):
    events: list[dict] = []
    monkeypatch.setattr(w, "_preview_emit", lambda slug, ev: events.append(ev))
    monkeypatch.setattr(w, "_probe_preview_url", lambda url: False)  # current url is dead
    monkeypatch.setattr(
        w,
        "_find_running_project_preview",
        lambda d: {"kind": "existing", "url": "http://127.0.0.1:5999", "port": 5999, "process": None},
    )
    session = {"slug": "x", "status": "running", "url": "http://127.0.0.1:4173", "port": 4173}
    w._reprobe_preview_port("x", session, Path("/tmp"))
    assert session["port"] == 5999
    assert [e["type"] for e in events] == ["state", "refresh"]


def test_reprobe_noop_when_url_healthy(monkeypatch):
    events: list[dict] = []
    monkeypatch.setattr(w, "_preview_emit", lambda slug, ev: events.append(ev))
    monkeypatch.setattr(w, "_probe_preview_url", lambda url: True)
    session = {"slug": "x", "status": "running", "url": "http://127.0.0.1:4173", "port": 4173}
    w._reprobe_preview_port("x", session, Path("/tmp"))
    assert events == []


def test_remember_and_recall_last_url():
    w._remember_last_url("proj-a", "http://127.0.0.1:5173/page")
    w._remember_last_url("proj-b", "https://example.com/")
    assert w._recall_last_url("proj-a") == "http://127.0.0.1:5173/page"
    assert w._recall_last_url("proj-b") == "https://example.com/"
    assert w._recall_last_url("proj-missing") is None


def test_remembered_preview_prefers_recalled_url(monkeypatch):
    w._remember_last_url("proj-c", "http://127.0.0.1:6100/")
    monkeypatch.setattr(w, "_probe_preview_url", lambda url: True)
    result = w._find_remembered_preview(Path("/tmp"), "proj-c")
    assert result is not None
    assert result["url"] == "http://127.0.0.1:6100/"
    assert result["port"] == 6100
    assert result["kind"] == "remembered"


def test_loopback_probe_url_forces_loopback_host():
    assert w._loopback_probe_url("http://myhost.example.com:5173/app") == "http://127.0.0.1:5173/app"
    assert w._loopback_probe_url("http://0.0.0.0:3000") == "http://127.0.0.1:3000"


def test_client_facing_url_keeps_loopback_on_desktop(monkeypatch):
    monkeypatch.setattr("core.spark_constants.is_server_environment", lambda: False)
    assert w._client_facing_preview_url("http://0.0.0.0:5173/") == "http://127.0.0.1:5173/"
    assert w._client_facing_preview_url("http://127.0.0.1:5173/") == "http://127.0.0.1:5173/"


def test_client_facing_url_keeps_real_bind_address_in_server_env(monkeypatch):
    monkeypatch.setattr("core.spark_constants.is_server_environment", lambda: True)
    monkeypatch.setattr("core.spark_constants.get_public_base_url", lambda h, p, s="http": f"http://vps.example.com:{p}")
    monkeypatch.setattr("core.spark_constants.get_server_hostname", lambda: "vps.example.com")
    out = w._client_facing_preview_url("http://0.0.0.0:5173/dashboard")
    assert out == "http://127.0.0.1:5173/dashboard"


def test_client_facing_url_leaves_concrete_host_alone(monkeypatch):
    monkeypatch.setattr("core.spark_constants.is_server_environment", lambda: True)
    assert w._client_facing_preview_url("http://10.0.0.5:8080/") == "http://10.0.0.5:8080/"


def test_await_ready_promotes_on_successful_probe(monkeypatch):
    events: list[dict] = []
    monkeypatch.setattr(w, "_preview_emit", lambda slug, ev: events.append(ev))
    monkeypatch.setattr(w, "_publish_workspace_event", lambda *a, **k: None)
    monkeypatch.setattr(w, "_run_agent_browser", lambda *a, **k: None)
    monkeypatch.setattr(w, "_probe_preview_url", lambda url: True)
    monkeypatch.setattr(w.threading, "Thread", lambda *a, **k: type("T", (), {"start": lambda self: None})())
    session = {"slug": "rdy", "status": "starting", "url": "http://127.0.0.1:5173/", "process": None}
    w._await_preview_ready("rdy", session)
    assert session["status"] == "running"
    assert any(ev.get("status") == "running" for ev in events)


def test_await_ready_times_out(monkeypatch):
    monkeypatch.setattr(w, "_preview_emit", lambda slug, ev: None)
    monkeypatch.setattr(w, "_probe_preview_url", lambda url: False)
    monkeypatch.setattr(w, "_PREVIEW_READY_TIMEOUT_SECONDS", 0.0)
    session = {"slug": "to", "status": "starting", "url": "http://127.0.0.1:5173/", "process": None}
    w._await_preview_ready("to", session)
    assert session["status"] == "failed"
    assert "did not respond" in session["error"]
