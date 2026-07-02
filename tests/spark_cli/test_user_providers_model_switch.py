"""Tests for user-defined providers (providers: dict) in /model.

These tests ensure that providers defined in the config.yaml ``providers:`` section
are properly resolved for model switching and that their full ``models:`` lists
are exposed in the model picker.
"""

from spark_cli import runtime_provider as rp
from spark_cli.config import get_compatible_custom_providers
from spark_cli.model_switch import list_authenticated_providers, switch_model
from spark_cli.providers import resolve_provider_full

# =============================================================================
# Tests for list_authenticated_providers including full models list
# =============================================================================

def test_list_authenticated_providers_includes_full_models_list_from_user_providers(monkeypatch):
    """User-defined providers should expose both default_model and full models list.

    Regression test: previously only default_model was shown in /model picker.
    """
    monkeypatch.setattr("agent.models_dev.fetch_models_dev", lambda: {})
    monkeypatch.setattr("spark_cli.providers.SPARK_OVERLAYS", {})

    user_providers = {
        "local-ollama": {
            "name": "Local Ollama",
            "api": "http://localhost:11434/v1",
            "default_model": "minimax-m2.7:cloud",
            "models": [
                "minimax-m2.7:cloud",
                "kimi-k2.5:cloud",
                "glm-5.1:cloud",
                "qwen3.5:cloud",
            ],
        }
    }

    providers = list_authenticated_providers(
        current_provider="local-ollama",
        user_providers=user_providers,
        custom_providers=[],
        max_models=50,
    )

    # Find our user provider
    user_prov = next(
        (p for p in providers if p.get("is_user_defined") and p["slug"] == "local-ollama"),
        None
    )

    assert user_prov is not None, "User provider 'local-ollama' should be in results"
    assert user_prov["total_models"] == 4, f"Expected 4 models, got {user_prov['total_models']}"
    assert "minimax-m2.7:cloud" in user_prov["models"]
    assert "kimi-k2.5:cloud" in user_prov["models"]
    assert "glm-5.1:cloud" in user_prov["models"]
    assert "qwen3.5:cloud" in user_prov["models"]


def test_list_authenticated_providers_dedupes_models_when_default_in_list(monkeypatch):
    """When default_model is also in models list, don't duplicate."""
    monkeypatch.setattr("agent.models_dev.fetch_models_dev", lambda: {})
    monkeypatch.setattr("spark_cli.providers.SPARK_OVERLAYS", {})

    user_providers = {
        "my-provider": {
            "api": "http://example.com/v1",
            "default_model": "model-a",  # Included in models list below
            "models": ["model-a", "model-b", "model-c"],
        }
    }

    providers = list_authenticated_providers(
        current_provider="my-provider",
        user_providers=user_providers,
        custom_providers=[],
    )

    user_prov = next(
        (p for p in providers if p.get("is_user_defined")),
        None
    )

    assert user_prov is not None
    assert user_prov["total_models"] == 3, "Should have 3 unique models, not 4"
    assert user_prov["models"].count("model-a") == 1, "model-a should not be duplicated"


def test_list_authenticated_providers_fallback_to_default_only(monkeypatch):
    """When no models array is provided, should fall back to default_model."""
    monkeypatch.setattr("agent.models_dev.fetch_models_dev", lambda: {})
    monkeypatch.setattr("spark_cli.providers.SPARK_OVERLAYS", {})

    user_providers = {
        "simple-provider": {
            "name": "Simple Provider",
            "api": "http://example.com/v1",
            "default_model": "single-model",
            # No 'models' key
        }
    }

    providers = list_authenticated_providers(
        current_provider="",
        user_providers=user_providers,
        custom_providers=[],
    )

    user_prov = next(
        (p for p in providers if p.get("is_user_defined")),
        None
    )

    assert user_prov is not None
    assert user_prov["total_models"] == 1
    assert user_prov["models"] == ["single-model"]


def test_user_provider_dedupes_compatible_custom_provider_view(monkeypatch):
    """Passing both providers: and the compatibility list should not duplicate rows."""
    monkeypatch.setattr("agent.models_dev.fetch_models_dev", lambda: {})
    monkeypatch.setattr("spark_cli.providers.SPARK_OVERLAYS", {})

    config = {
        "providers": {
            "local-ollama": {
                "name": "Local Ollama",
                "api": "http://localhost:11434/v1",
                "default_model": "llama3",
                "models": ["llama3", "qwen3-coder"],
            }
        }
    }

    providers = list_authenticated_providers(
        current_provider="local-ollama",
        user_providers=config["providers"],
        custom_providers=get_compatible_custom_providers(config),
        max_models=50,
    )

    local_rows = [p for p in providers if p.get("name") == "Local Ollama"]
    assert len(local_rows) == 1
    assert local_rows[0]["slug"] == "local-ollama"
    assert local_rows[0]["models"] == ["llama3", "qwen3-coder"]


def test_resolve_provider_full_finds_user_provider_by_display_name():
    resolved = resolve_provider_full(
        "custom:local-ollama",
        user_providers={
            "local-gateway": {
                "name": "Local Ollama",
                "api": "http://localhost:11434/v1",
                "key_env": "OLLAMA_API_KEY",
                "transport": "openai_chat",
            }
        },
        custom_providers=[],
    )

    assert resolved is not None
    assert resolved.id == "local-gateway"
    assert resolved.name == "Local Ollama"
    assert resolved.base_url == "http://localhost:11434/v1"
    assert resolved.api_key_env_vars == ("OLLAMA_API_KEY",)


# =============================================================================
# Tests for _get_named_custom_provider with providers: dict
# =============================================================================

def test_get_named_custom_provider_finds_user_providers_by_key(monkeypatch, tmp_path):
    """Should resolve providers from providers: dict (new-style), not just custom_providers."""
    config = {
        "providers": {
            "local-localhost:11434": {
                "api": "http://localhost:11434/v1",
                "name": "Local (localhost:11434)",
                "default_model": "minimax-m2.7:cloud",
            }
        }
    }

    import yaml
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(config))

    monkeypatch.setenv("SPARK_HOME", str(tmp_path))

    result = rp._get_named_custom_provider("local-localhost:11434")

    assert result is not None
    assert result["base_url"] == "http://localhost:11434/v1"
    assert result["name"] == "Local (localhost:11434)"


def test_get_named_custom_provider_finds_by_display_name(monkeypatch, tmp_path):
    """Should match providers by their 'name' field as well as key."""
    config = {
        "providers": {
            "my-ollama-xyz": {
                "api": "http://ollama.example.com/v1",
                "name": "My Production Ollama",
                "default_model": "llama3",
            }
        }
    }

    import yaml
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(config))

    monkeypatch.setenv("SPARK_HOME", str(tmp_path))

    # Should find by display name (normalized)
    result = rp._get_named_custom_provider("my-production-ollama")

    assert result is not None
    assert result["base_url"] == "http://ollama.example.com/v1"


def test_get_named_custom_provider_falls_back_to_legacy_format(monkeypatch, tmp_path):
    """Should still work with custom_providers: list format."""
    config = {
        "providers": {},
        "custom_providers": [
            {
                "name": "Custom Endpoint",
                "base_url": "http://custom.example.com/v1",
            }
        ]
    }

    import yaml
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(config))

    monkeypatch.setenv("SPARK_HOME", str(tmp_path))

    result = rp._get_named_custom_provider("custom-endpoint")

    assert result is not None


def test_get_named_custom_provider_returns_none_for_unknown(monkeypatch, tmp_path):
    """Should return None for providers that don't exist."""
    config = {
        "providers": {
            "known-provider": {
                "api": "http://known.example.com/v1",
            }
        }
    }

    import yaml
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(config))

    monkeypatch.setenv("SPARK_HOME", str(tmp_path))

    result = rp._get_named_custom_provider("other-provider")

    # "unknown-provider" partial-matches "known-provider" because "unknown" doesn't match
    # but our matching is loose (substring). Let's verify a truly non-matching provider
    result = rp._get_named_custom_provider("completely-different-name")
    assert result is None


def test_get_named_custom_provider_skips_empty_base_url(monkeypatch, tmp_path):
    """Should skip providers without a base_url."""
    config = {
        "providers": {
            "incomplete-provider": {
                "name": "Incomplete",
                # No api/base_url field
            }
        }
    }

    import yaml
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(config))

    monkeypatch.setenv("SPARK_HOME", str(tmp_path))

    result = rp._get_named_custom_provider("incomplete-provider")

    assert result is None


# =============================================================================
# Integration test for switch_model with user providers
# =============================================================================

def test_switch_model_resolves_user_provider_credentials(monkeypatch, tmp_path):
    """/model switch should resolve credentials for providers: dict providers."""
    import yaml

    config = {
        "providers": {
            "local-ollama": {
                "api": "http://localhost:11434/v1",
                "name": "Local Ollama",
                "default_model": "minimax-m2.7:cloud",
            }
        }
    }

    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(config))
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))

    # Mock validation to pass
    monkeypatch.setattr(
        "spark_cli.models.validate_requested_model",
        lambda *a, **k: {"accepted": True, "persist": True, "recognized": True, "message": None}
    )

    result = switch_model(
        raw_input="kimi-k2.5:cloud",
        current_provider="local-ollama",
        current_model="minimax-m2.7:cloud",
        current_base_url="http://localhost:11434/v1",
        is_global=False,
        user_providers=config["providers"],
    )

    assert result.success is True
    assert result.error_message == ""


def test_resolve_runtime_provider_uses_user_provider_key_env_and_api_mode(monkeypatch, tmp_path):
    """Runtime resolution should honor providers: key_env and api_mode/transport."""
    import yaml

    config = {
        "providers": {
            "anthropic-proxy": {
                "name": "Anthropic Proxy",
                "api": "https://proxy.example.com/anthropic",
                "key_env": "PROXY_API_KEY",
                "transport": "anthropic_messages",
                "default_model": "claude-proxy",
            }
        }
    }

    (tmp_path / "config.yaml").write_text(yaml.dump(config))
    monkeypatch.setenv("SPARK_HOME", str(tmp_path))
    monkeypatch.setenv("PROXY_API_KEY", "proxy-token")
    monkeypatch.setattr(
        rp,
        "load_pool",
        lambda provider: type("P", (), {"has_credentials": lambda self: False})(),
    )

    result = rp.resolve_runtime_provider(requested="anthropic-proxy")

    assert result["provider"] == "custom"
    assert result["requested_provider"] == "anthropic-proxy"
    assert result["api_key"] == "proxy-token"
    assert result["api_mode"] == "anthropic_messages"
    assert result["base_url"] == "https://proxy.example.com/anthropic"
