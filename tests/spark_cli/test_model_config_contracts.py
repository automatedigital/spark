"""Typed contract tests for model config, runtime, and web chat DTOs."""

from __future__ import annotations

import pytest


def test_normalize_global_model_config_prefers_default_then_aliases():
    from spark_cli.model_config import GlobalModelConfig, normalize_global_model_config

    assert normalize_global_model_config(
        {
            "default": "smart-model",
            "model": "legacy-model",
            "name": "display-name",
            "provider": "anthropic",
            "base_url": "https://proxy.example/anthropic",
            "api_mode": "anthropic_messages",
        }
    ) == GlobalModelConfig(
        model="smart-model",
        provider="anthropic",
        base_url="https://proxy.example/anthropic",
        api_mode="anthropic_messages",
    )

    assert normalize_global_model_config({"model": "legacy-model"}).model == "legacy-model"
    assert normalize_global_model_config({"name": "named-model"}).model == "named-model"
    assert normalize_global_model_config("string-model").model == "string-model"
    assert normalize_global_model_config(["bad"]).model == ""


def test_runtime_provider_resolution_contract_names_core_keys():
    from spark_cli.runtime_provider import RuntimeProviderRecord, RuntimeProviderResolution

    assert {
        "provider",
        "api_mode",
        "base_url",
        "api_key",
        "source",
        "requested_provider",
    }.issubset(RuntimeProviderResolution.__annotations__)
    assert {
        "provider",
        "model",
        "api_mode",
        "base_url",
        "api_key",
        "credential_source",
        "timeout_policy",
        "request_overrides",
    }.issubset(RuntimeProviderRecord.__dataclass_fields__)


def test_runtime_provider_record_round_trips_legacy_kwargs():
    from spark_cli.runtime_provider import RuntimeProviderRecord, runtime_record_from_mapping

    record = runtime_record_from_mapping(
        {
            "provider": "openai-codex",
            "model": "gpt-5.5",
            "api_mode": "codex_responses",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test",
            "source": "auth",
            "requested_provider": "auto",
            "timeout_policy": {"connect": 10},
            "request_overrides": {"reasoning_effort": "low"},
        }
    )

    assert record == RuntimeProviderRecord(
        provider="openai-codex",
        model="gpt-5.5",
        api_mode="codex_responses",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        source="auth",
        credential_source="auth",
        requested_provider="auto",
        timeout_policy={"connect": 10},
        request_overrides={"reasoning_effort": "low"},
    )
    assert record.to_runtime_kwargs() == {
        "provider": "openai-codex",
        "model": "gpt-5.5",
        "api_mode": "codex_responses",
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-test",
        "source": "auth",
        "requested_provider": "auto",
        "timeout_policy": {"connect": 10},
        "request_overrides": {"reasoning_effort": "low"},
    }
    assert dict(record)["provider"] == "openai-codex"
    assert {**record}["api_mode"] == "codex_responses"


def test_resolve_runtime_provider_returns_typed_record(monkeypatch):
    from spark_cli import runtime_provider as rp
    from spark_cli.runtime_provider import RuntimeProviderRecord

    monkeypatch.setattr(rp, "resolve_requested_provider", lambda requested=None: "ollama")
    monkeypatch.setattr(rp, "resolve_provider", lambda *args, **kwargs: "ollama")
    monkeypatch.setattr(rp, "_get_model_config", lambda: {})

    resolved = rp.resolve_runtime_provider(requested="ollama")

    assert isinstance(resolved, RuntimeProviderRecord)
    assert resolved["provider"] == "ollama"
    assert resolved.get("api_key") == "no-key-required"


def test_runtime_model_config_normalizes_legacy_model_alias(monkeypatch):
    from spark_cli import runtime_provider as rp

    monkeypatch.setattr(
        rp,
        "load_config",
        lambda: {
            "model": {
                "model": "legacy-key-model",
                "provider": "custom",
                "base_url": "https://models.example/v1",
            }
        },
    )

    assert rp._get_model_config() == {
        "model": "legacy-key-model",
        "provider": "custom",
        "base_url": "https://models.example/v1",
        "default": "legacy-key-model",
    }


def test_web_chat_dtos_validate_context_items_and_isolate_defaults():
    from spark_cli.context_models import ContextItem
    from spark_cli.web_schemas import ConversationCreate, ConversationMessage

    body = ConversationCreate.model_validate(
        {
            "message": "hello",
            "context_items": [
                {
                    "id": "ctx-1",
                    "type": "file",
                    "source_path": "src/app.py",
                    "inclusion_mode": "path_only",
                    "scope": "one_turn",
                    "size_bytes": 0,
                }
            ],
        }
    )

    assert isinstance(body.context_items[0], ContextItem)
    assert body.context_items[0].source_path == "src/app.py"

    first = ConversationMessage(message="one")
    second = ConversationMessage(message="two")
    first.context_items.append(body.context_items[0])

    assert len(first.context_items) == 1
    assert second.context_items == []


def test_web_chat_dtos_reject_invalid_context_items():
    from spark_cli.web_schemas import ConversationCreate

    with pytest.raises(ValueError):
        ConversationCreate.model_validate(
            {
                "message": "hello",
                "context_items": [{"id": "ctx-1", "type": "not-a-type"}],
            }
        )
