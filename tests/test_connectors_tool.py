"""Tests for the `connectors` agent tool wrapper."""

import json

from tools import connectors_tool as ct


def _fake_status(monkeypatch, *, connected=False, account=None):
    """Force GoogleWorkspaceConnector.status() to a fixed result."""
    from tools.connectors.base import ConnectorState, ConnectorStatus
    from tools.connectors.google import GoogleWorkspaceConnector

    state = ConnectorState.CONNECTED if connected else ConnectorState.DISCONNECTED
    monkeypatch.setattr(
        GoogleWorkspaceConnector, "status",
        lambda self: ConnectorStatus(state=state, account=account, detail="x"),
    )


def test_list_includes_google(monkeypatch):
    _fake_status(monkeypatch)
    out = json.loads(ct.connectors_tool("list"))
    ids = [c["id"] for c in out["connectors"]]
    assert "google" in ids
    g = next(c for c in out["connectors"] if c["id"] == "google")
    assert g["status"]["state"] == "disconnected"
    assert "gmail.send" in " ".join(g["scopes"])


def test_status_requires_connector():
    out = ct.connectors_tool("status")
    assert "error" in out.lower() or "required" in out.lower()


def test_status_unknown_connector():
    out = ct.connectors_tool("status", "nope")
    assert "unknown" in out.lower()


def test_status_known(monkeypatch):
    _fake_status(monkeypatch, connected=True, account="me@example.com")
    out = json.loads(ct.connectors_tool("status", "google"))
    assert out["connector"] == "google"
    assert out["status"]["state"] == "connected"
    assert out["status"]["account"] == "me@example.com"


def test_connect_already_connected(monkeypatch):
    _fake_status(monkeypatch, connected=True, account="me@example.com")
    out = json.loads(ct.connectors_tool("connect", "google"))
    assert out["already_connected"] is True


def test_connect_headless_returns_guidance(monkeypatch):
    _fake_status(monkeypatch, connected=False)
    monkeypatch.setattr(ct, "_is_interactive", lambda: False)
    out = json.loads(ct.connectors_tool("connect", "google"))
    assert out["started"] is False
    assert "/connect google" in out["message"]


def test_connect_interactive_invokes_connect(monkeypatch):
    _fake_status(monkeypatch, connected=False)
    monkeypatch.setattr(ct, "_is_interactive", lambda: True)
    calls = {}
    from tools.connectors.base import ConnectorState, ConnectorStatus
    from tools.connectors.google import GoogleWorkspaceConnector

    def fake_connect(self, *, interactive=True, **kw):
        calls["interactive"] = interactive
        return ConnectorStatus(state=ConnectorState.CONNECTED, account="z@z.com")

    monkeypatch.setattr(GoogleWorkspaceConnector, "connect", fake_connect)
    out = json.loads(ct.connectors_tool("connect", "google"))
    assert calls["interactive"] is True
    assert out["status"]["state"] == "connected"


def test_unknown_action():
    out = ct.connectors_tool("frobnicate", "google")
    assert "unknown action" in out.lower()


def test_tool_is_registered():
    from tools.registry import registry
    assert "connectors" in registry._tools
    assert registry._tools["connectors"].toolset == "connectors"
