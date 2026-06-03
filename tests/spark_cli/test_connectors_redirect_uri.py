"""Tests for environment-aware OAuth redirect URI (connectors_routes._redirect_uri)."""

from __future__ import annotations

from spark_cli import connectors_routes as c


def test_redirect_uri_defaults_to_localhost(monkeypatch):
    monkeypatch.setattr("core.spark_constants.is_server_environment", lambda: False)
    c.set_server_port(9119)
    assert c._redirect_uri() == "http://localhost:9119/oauth/google/callback"


def test_redirect_uri_uses_public_host_in_server_env(monkeypatch):
    monkeypatch.setattr("core.spark_constants.is_server_environment", lambda: True)
    monkeypatch.setattr(
        "core.spark_constants.get_public_base_url",
        lambda h, p, s="http": "https://spark.example.com",
    )
    c.set_server_port(9119)
    assert c._redirect_uri() == "https://spark.example.com/oauth/google/callback"


def test_redirect_uri_explicit_override(monkeypatch, tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("connectors:\n  oauth_redirect_base: https://proxy.example.com/\n")
    monkeypatch.setattr("spark_cli.config.get_spark_home", lambda: tmp_path)
    # Override wins even in a server environment.
    monkeypatch.setattr("core.spark_constants.is_server_environment", lambda: True)
    c.set_server_port(9119)
    assert c._redirect_uri() == "https://proxy.example.com/oauth/google/callback"
