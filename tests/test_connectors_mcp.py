"""Tests for MCP preset connectors + the unified connectors API surface."""

from __future__ import annotations

import json

import pytest

from tools.connectors import CONNECTOR_REGISTRY, Transport, get_connector
from tools.connectors.mcp import MCP_PRESET_CONNECTORS, McpConnector, McpConnectorSpec

# --- registry / presets ------------------------------------------------------

def test_mcp_presets_registered():
    for spec in MCP_PRESET_CONNECTORS:
        assert spec.id in CONNECTOR_REGISTRY
        connector = get_connector(spec.id)
        assert isinstance(connector, McpConnector)
        assert connector.transport is Transport.MCP


def test_mcp_preset_ids_do_not_clash_with_catalog():
    assert len(CONNECTOR_REGISTRY) == len(set(CONNECTOR_REGISTRY))


def _spec(auth: str = "oauth") -> McpConnectorSpec:
    return McpConnectorSpec(
        id="test-mcp",
        name="Test MCP",
        description="test",
        url="https://mcp.example.com/mcp",
        auth=auth,
    )


# --- status derivation --------------------------------------------------------

def test_status_disconnected_without_config_entry():
    c = McpConnector(_spec())
    status = c.status()
    assert status.state.value == "disconnected"
    assert status.extra["server_url"] == "https://mcp.example.com/mcp"


def test_connect_no_auth_writes_server_and_connects():
    from spark_cli.mcp_config import _get_mcp_servers

    c = McpConnector(_spec(auth="none"))
    status = c.connect()
    assert status.connected
    assert _get_mcp_servers()["test-mcp"] == {"url": "https://mcp.example.com/mcp"}
    # disconnect cleans up the config entry
    status = c.disconnect()
    assert not status.connected
    assert "test-mcp" not in _get_mcp_servers()


def test_oauth_connected_when_entry_and_tokens_exist(monkeypatch):
    from spark_cli.mcp_config import _save_mcp_server
    from tools.mcp_oauth import _get_token_dir

    c = McpConnector(_spec(auth="oauth"))
    _save_mcp_server("test-mcp", {"url": "https://mcp.example.com/mcp", "auth": "oauth"})
    token_dir = _get_token_dir()
    token_dir.mkdir(parents=True, exist_ok=True)
    (token_dir / "test-mcp.json").write_text(json.dumps({"access_token": "x"}))
    try:
        status = c.status()
        assert status.connected
        assert status.extra["auth_type"] == "mcp_oauth"
    finally:
        c.disconnect()
    assert not (token_dir / "test-mcp.json").exists()


def test_oauth_connect_kicks_off_background_flow(monkeypatch):
    calls = {}

    def fake_probe(name, config, connect_timeout=300):
        calls["name"] = name
        calls["config"] = config

    monkeypatch.setattr("spark_cli.mcp_config._probe_single_server", fake_probe)
    c = McpConnector(_spec(auth="oauth"))
    try:
        status = c.connect()
        assert status.extra["connect_state"] in {"pending", "done"}
        # background thread runs quickly; wait for it
        import time

        for _ in range(50):
            if c.read_meta().get("connect_state") == "done":
                break
            time.sleep(0.05)
        assert c.read_meta().get("connect_state") == "done"
        assert calls["name"] == "test-mcp"
    finally:
        c.disconnect()


# --- API routes ---------------------------------------------------------------

@pytest.fixture
def client():
    fastapi = pytest.importorskip("fastapi")
    from starlette.testclient import TestClient

    from spark_cli.connectors_routes import register_connectors_routes

    app = fastapi.FastAPI()
    register_connectors_routes(app)
    return TestClient(app)


def test_list_connectors_single_payload(client):
    items = client.get("/api/connectors").json()
    by_id = {item["id"]: item for item in items}
    assert by_id["google"]["kind"] == "oauth"
    notion = by_id["notion"]
    assert notion["kind"] == "api_key"
    assert notion["api_key_url"].startswith("https://")
    assert notion["setup_steps"]
    mcp = by_id["notion-mcp"]
    assert mcp["kind"] == "mcp"
    assert mcp["state"] in {"connected", "disconnected", "error"}
    cc = by_id["claude-code"]
    assert cc["kind"] == "cli"


def test_api_key_endpoint_persists_to_env(client, monkeypatch):
    from spark_cli.config import get_env_path, get_env_value

    # Tinker has no token validator, so the key is accepted without network I/O.
    resp = client.post(
        "/api/connectors/tinker/api-key", json={"api_key": "tk-test-123"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["saved"] is True
    assert body["env_var"] == "TINKER_API_KEY"
    assert body["connected"] is True
    assert get_env_value("TINKER_API_KEY") == "tk-test-123"
    # persisted under the isolated SPARK_HOME, not a hardcoded path
    assert get_env_path().exists()


def test_api_key_endpoint_rejects_multiline(client):
    resp = client.post(
        "/api/connectors/tinker/api-key", json={"api_key": "bad\nkey"}
    )
    assert resp.status_code == 400


def test_api_key_endpoint_rejects_wrong_env_var(client):
    resp = client.post(
        "/api/connectors/tinker/api-key",
        json={"api_key": "x", "env_var": "NOT_A_VAR"},
    )
    assert resp.status_code == 400


def test_api_key_endpoint_unknown_connector(client):
    resp = client.post("/api/connectors/nope/api-key", json={"api_key": "x"})
    assert resp.status_code == 404


def test_api_key_endpoint_rejects_non_api_key_connector(client):
    resp = client.post("/api/connectors/notion-mcp/api-key", json={"api_key": "x"})
    assert resp.status_code == 400


def test_mcp_connect_and_poll(client, monkeypatch):
    monkeypatch.setattr(
        "spark_cli.mcp_config._probe_single_server", lambda *a, **k: None
    )
    resp = client.post("/api/connectors/context7/connect")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["flow"] in {"mcp", "mcp_oauth"}
    assert body["poll_url"] == "/api/connectors/context7/connect/status"
    poll = client.get("/api/connectors/context7/connect/status").json()
    assert poll["connected"] is True  # context7 needs no auth
    # disconnect cleans up
    resp = client.delete("/api/connectors/context7")
    assert resp.json()["disconnected"] is True
    from spark_cli.mcp_config import _get_mcp_servers

    assert "context7" not in _get_mcp_servers()
