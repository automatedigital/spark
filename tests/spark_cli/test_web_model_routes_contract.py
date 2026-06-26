"""Route-level contracts for dashboard model endpoints before router extraction."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest


@pytest.fixture
def client():
    try:
        from starlette.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi/starlette not installed")

    from spark_cli.web_server import app

    return TestClient(app)


def test_model_status_route_shape(client, monkeypatch):
    import spark_cli.web_server as web_server

    monkeypatch.setattr(
        web_server,
        "load_config",
        lambda: {
            "model": {
                "default": "anthropic/claude-opus-4.6",
                "provider": "anthropic",
            },
            "smart_model_routing": {
                "enabled": True,
                "cheap_model": {
                    "model": "openai/gpt-5-mini",
                    "provider": "openai",
                },
            },
            "agent": {"reasoning_effort": "medium"},
        },
    )
    caps = SimpleNamespace(supports_reasoning=True)

    with patch("agent.models_dev.get_model_capabilities", return_value=caps):
        resp = client.get("/api/model/status")

    assert resp.status_code == 200
    assert resp.json() == {
        "smart_model": "anthropic/claude-opus-4.6",
        "smart_provider": "anthropic",
        "fast_model": "openai/gpt-5-mini",
        "fast_provider": "openai",
        "multi_model_enabled": True,
        "reasoning_effort": "medium",
        "reasoning_supported": True,
    }


def test_model_routes_are_registered_on_config_router(client):
    import spark_cli.web_server as web_server

    route = next(
        route
        for route in web_server.config_router.routes
        if getattr(route, "path", "") == "/api/model/status"
    )

    assert "config" in route.tags


def test_model_suggestions_route_uses_provider_catalogs(client, monkeypatch):
    import spark_cli.web_server as web_server

    monkeypatch.setattr(
        web_server,
        "load_config",
        lambda: {
            "model": {
                "default": "anthropic/claude-opus-4.6",
                "provider": "anthropic",
                "base_url": "https://anthropic.example",
            },
            "smart_model_routing": {
                "cheap_model": {
                    "model": "gpt-5-mini",
                    "provider": "openai",
                    "base_url": "https://openai.example",
                },
            },
        },
    )

    def fake_catalog(provider: str, base_url: str = ""):
        assert base_url.endswith(".example")
        return [f"{provider}/one", f"{provider}/two"], False

    monkeypatch.setattr(web_server, "_resolve_provider_models", fake_catalog)

    resp = client.get("/api/model/suggestions")

    assert resp.status_code == 200
    assert resp.json() == {
        "smart": ["anthropic/one", "anthropic/two"],
        "fast": ["openai/one", "openai/two"],
        "smart_provider": "anthropic",
        "fast_provider": "openai",
    }


def test_model_mutation_routes_write_only_targeted_fields(client, monkeypatch):
    import spark_cli.web_server as web_server

    saved_configs = []
    config = {
        "model": {
            "default": "old-smart",
            "provider": "openrouter",
            "base_url": "https://models.example",
        },
        "smart_model_routing": {
            "enabled": True,
            "cheap_model": {
                "model": "old-fast",
                "provider": "openai",
            },
        },
        "agent": {"reasoning_effort": "low"},
    }

    monkeypatch.setattr(web_server, "load_config", lambda: config)
    monkeypatch.setattr("spark_cli.config.save_config", lambda cfg: saved_configs.append(cfg.copy()))

    smart = client.put("/api/model/smart", json={"model": "new-smart"})
    fast = client.put("/api/model/fast", json={"model": "new-fast"})
    reasoning = client.put("/api/model/reasoning", json={"effort": "high"})

    assert smart.status_code == 200
    assert fast.status_code == 200
    assert reasoning.status_code == 200
    assert config["model"] == {
        "default": "new-smart",
        "provider": "openrouter",
        "base_url": "https://models.example",
    }
    assert config["smart_model_routing"]["cheap_model"] == {
        "model": "new-fast",
        "provider": "openai",
    }
    assert config["agent"]["reasoning_effort"] == "high"
    assert [resp.json()["model"] for resp in (smart, fast)] == ["new-smart", "new-fast"]
    assert reasoning.json() == {"effort": "high", "ok": True}
    assert len(saved_configs) == 3


def test_model_mutation_routes_reject_empty_or_invalid_values(client, monkeypatch):
    import spark_cli.web_server as web_server

    monkeypatch.setattr(web_server, "load_config", lambda: {})

    smart = client.put("/api/model/smart", json={"model": ""})
    fast = client.put("/api/model/fast", json={"model": "   "})
    reasoning = client.put("/api/model/reasoning", json={"effort": "too-much"})

    assert smart.status_code == 400
    assert fast.status_code == 400
    assert reasoning.status_code == 400
    assert smart.json()["error"] == "model is required"
    assert fast.json()["error"] == "model is required"
    assert reasoning.json()["error"] == "Invalid effort: too-much"
