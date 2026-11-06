"""SP10 read-only catalogue contracts."""
import json

import pytest

from spark_cli.auth import PROVIDER_REGISTRY, ProviderConfig
from spark_cli.provider_catalog import provider_catalog


@pytest.mark.parametrize("provider_id", list(PROVIDER_REGISTRY))
def test_registered_provider_metadata(provider_id, monkeypatch, tmp_path):
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    catalog = provider_catalog({})
    entry = next(p for p in catalog["providers"] if p["id"] == provider_id)
    registered = PROVIDER_REGISTRY[provider_id]
    assert entry["label"] == registered.name
    assert entry["credential"]["mechanism"] == registered.auth_type
    assert entry["credential"]["configured"] is False
    assert entry["availability"] == "unknown"
    assert set(entry["capabilities"].values()) == {"unknown"}


def test_profile_credentials_never_adopted_or_returned(monkeypatch, tmp_path):
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    monkeypatch.setenv("OPENROUTER_API_KEY", "other-profile-secret")
    assert not next(p for p in provider_catalog({})["providers"] if p["id"] == "openrouter")["credential"]["configured"]
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=profile-secret\n")
    result = provider_catalog({})
    assert next(p for p in result["providers"] if p["id"] == "openrouter")["credential"]["configured"]
    assert "profile-secret" not in json.dumps(result)


def test_fixture_registration_no_frontend_edit(monkeypatch):
    monkeypatch.setitem(PROVIDER_REGISTRY, "fixture", ProviderConfig(
        id="fixture", name="Fixture provider", auth_type="api_key",
        api_key_env_vars=("FIXTURE_KEY",), inference_base_url="https://fixture.invalid/v1",
    ))
    assert any(p["id"] == "fixture" for p in provider_catalog({})["providers"])


def test_no_network_or_runtime_resolution(monkeypatch):
    import socket

    import spark_cli.runtime_provider as runtime

    def forbidden(*args, **kwargs):
        raise AssertionError("catalogue attempted provider connection/resolution")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(runtime, "resolve_requested_provider", forbidden)
    result = provider_catalog({"model": {"provider": "ollama"}})
    assert result["selected_provider"] == "ollama"
    assert any(p["id"] == "custom" for p in result["providers"])


def test_custom_config_never_exposes_endpoint_secrets():
    result = provider_catalog({"providers": {"lab": {
        "name": "Lab", "base_url": "http://user:secret@localhost/v1?token=secret",
        "api_key": "inline-secret",
    }}})
    assert any(p["id"] == "custom:lab" for p in result["providers"])
    assert "secret" not in json.dumps(result)


def test_optional_sdks_are_not_required_for_catalogue(monkeypatch):
    import builtins

    original = builtins.__import__

    def without_sdks(name, *args, **kwargs):
        if name.split(".")[0] in {"openai", "anthropic", "google"}:
            raise ImportError("fixture: optional SDK unavailable")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_sdks)
    result = provider_catalog({})
    assert set(PROVIDER_REGISTRY).issubset({p["id"] for p in result["providers"]})
    assert all(p["availability"] == "unknown" for p in result["providers"])


def test_catalogue_http_contract(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from spark_cli import config
    from spark_cli.providers_routes import register_providers_routes

    monkeypatch.setattr(config, "load_config", lambda: {"model": {"provider": "custom"}})
    app = FastAPI()
    register_providers_routes(app)
    response = TestClient(app).get("/api/providers/catalogue")
    assert response.status_code == 200
    assert response.json()["schema_version"] == 1
    assert response.json()["selected_provider"] == "custom"
