"""Regression tests for the OpenAI Codex interactive model flow."""

from __future__ import annotations

import json

from spark_cli.codex_models import DEFAULT_CODEX_MODELS


def test_direct_openai_models_are_not_in_codex_offline_fallback():
    assert not {"gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"}.intersection(
        DEFAULT_CODEX_MODELS
    )


def test_openai_codex_model_flow_uses_quick_live_catalog(monkeypatch):
    """The picker should use live discovery with a short timeout."""
    from spark_cli import main

    monkeypatch.setattr(
        "spark_cli.auth.get_codex_auth_status",
        lambda: {"logged_in": True, "api_key": "codex-token"},
    )

    def fake_get_codex_model_ids(*, access_token=None, api_timeout=10.0):
        assert access_token == "codex-token"
        assert api_timeout == 1.5
        return ["gpt-5.4-mini", "gpt-5.4"]

    monkeypatch.setattr(
        "spark_cli.codex_models.get_codex_model_ids",
        fake_get_codex_model_ids,
    )
    monkeypatch.setattr(
        "spark_cli.auth._prompt_model_selection",
        lambda model_ids, current_model="": None,
    )

    main._model_flow_openai_codex({"model": {}}, current_model="gpt-5.4-mini")


def test_openai_codex_fast_slot_defaults_to_mini(monkeypatch):
    """The FAST Codex picker should start on gpt-5.4-mini when available."""
    from spark_cli import main

    monkeypatch.setattr(
        "spark_cli.auth.get_codex_auth_status",
        lambda: {"logged_in": True, "api_key": "codex-token"},
    )
    monkeypatch.setattr(
        "spark_cli.auth.get_model_routing_slot_selection",
        lambda: "fast",
    )
    monkeypatch.setattr(
        "spark_cli.codex_models.get_codex_model_ids",
        lambda access_token=None, api_timeout=10.0: [
            "gpt-5.5",
            "gpt-5.4-mini",
            "gpt-5.4",
        ],
    )

    seen = {}

    def fake_prompt_model_selection(model_ids, current_model=""):
        seen["model_ids"] = model_ids
        seen["current_model"] = current_model
        return None

    monkeypatch.setattr(
        "spark_cli.auth._prompt_model_selection",
        fake_prompt_model_selection,
    )

    main._model_flow_openai_codex({"model": {}}, current_model="gpt-5.5")

    assert seen == {
        "model_ids": ["gpt-5.5", "gpt-5.4-mini", "gpt-5.4"],
        "current_model": "gpt-5.4-mini",
    }


def test_openai_codex_smart_slot_includes_current_model(monkeypatch):
    """The SMART picker must show the active model even if local cache lacks it."""
    from spark_cli import main

    monkeypatch.setattr(
        "spark_cli.auth.get_codex_auth_status",
        lambda: {"logged_in": True, "api_key": "codex-token"},
    )
    monkeypatch.setattr(
        "spark_cli.auth.get_model_routing_slot_selection",
        lambda: "smart",
    )
    monkeypatch.setattr(
        "spark_cli.codex_models.get_codex_model_ids",
        lambda access_token=None, api_timeout=10.0: ["gpt-5.4", "gpt-5.4-mini"],
    )

    seen = {}

    def fake_prompt_model_selection(model_ids, current_model=""):
        seen["model_ids"] = model_ids
        seen["current_model"] = current_model
        return None

    monkeypatch.setattr(
        "spark_cli.auth._prompt_model_selection",
        fake_prompt_model_selection,
    )

    main._model_flow_openai_codex({"model": {}}, current_model="gpt-5.5")

    assert seen == {
        "model_ids": ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini"],
        "current_model": "gpt-5.5",
    }


def test_get_codex_model_ids_forwards_api_timeout(monkeypatch):
    from spark_cli.codex_models import get_codex_model_ids

    seen = {}

    def fake_fetch(access_token, timeout=10.0):
        seen["access_token"] = access_token
        seen["timeout"] = timeout
        return ["gpt-5.5"]

    monkeypatch.setattr("spark_cli.codex_models._fetch_models_from_api", fake_fetch)

    assert get_codex_model_ids(access_token="token", api_timeout=1.5) == ["gpt-5.5"]
    assert seen == {"access_token": "token", "timeout": 1.5}


def test_live_codex_catalog_is_authoritative(monkeypatch):
    from spark_cli.codex_models import get_codex_model_catalog

    monkeypatch.setattr(
        "spark_cli.codex_models._fetch_model_entries_from_api",
        lambda access_token, timeout=10.0: ([{"slug": "gpt-5.4"}], None),
    )
    catalog = get_codex_model_catalog("token")
    assert catalog["models"] == ["gpt-5.4"]
    assert catalog["source"] == "live"
    assert catalog["live"] is True
    assert catalog["authoritative"] is True
    assert catalog["catalog"] == [
        {
            "slug": "gpt-5.4",
            "display_name": "gpt-5.4",
            "visibility": None,
            "supported_reasoning_efforts": [],
            "context_window": None,
            "max_output_tokens": None,
            "multi_agent_version": None,
            "source": "live",
            "fetched_at": None,
        }
    ]


def test_live_catalog_preserves_capabilities_and_freshness(monkeypatch):
    from spark_cli.codex_models import get_codex_model_catalog

    monkeypatch.setattr(
        "spark_cli.codex_models._fetch_model_entries_from_api",
        lambda access_token, timeout=10.0: (
            [
                {
                    "slug": "gpt-5.6-sol",
                    "display_name": "GPT-5.6-Sol",
                    "visibility": "list",
                    "supported_reasoning_levels": [
                        {"effort": "low"},
                        {"effort": "xhigh"},
                    ],
                    "context_window": 272000,
                    "max_output_tokens": 64000,
                    "multi_agent_version": "v2",
                    "priority": 1,
                }
            ],
            "2026-08-04T21:52:35Z",
        ),
    )

    catalog = get_codex_model_catalog("token")
    assert catalog["freshness"] == "2026-08-04T21:52:35Z"
    assert catalog["catalog"][0] == {
        "slug": "gpt-5.6-sol",
        "display_name": "GPT-5.6-Sol",
        "visibility": "list",
        "supported_reasoning_efforts": ["low", "xhigh"],
        "context_window": 272000,
        "max_output_tokens": 64000,
        "multi_agent_version": "v2",
        "source": "live",
        "fetched_at": "2026-08-04T21:52:35Z",
    }


def test_live_catalog_does_not_append_defaults_or_hidden_models(monkeypatch):
    from spark_cli.codex_models import get_codex_model_catalog

    monkeypatch.setattr(
        "spark_cli.codex_models._fetch_model_entries_from_api",
        lambda access_token, timeout=10.0: (
            [
                {"slug": "visible-model", "visibility": "list"},
                {"slug": "hidden-model", "visibility": "hide"},
                {"slug": "unsupported-model", "supported_in_api": False},
            ],
            None,
        ),
    )

    catalog = get_codex_model_catalog("token")
    assert catalog["models"] == ["visible-model"]
    assert all(model not in catalog["models"] for model in DEFAULT_CODEX_MODELS)


def test_cache_catalog_preserves_metadata_and_is_marked_stale(monkeypatch, tmp_path):
    from spark_cli.codex_models import get_codex_model_catalog

    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    (tmp_path / "models_cache.json").write_text(
        json.dumps(
            {
                "fetched_at": "2026-08-04T21:52:35Z",
                "models": [
                    {
                        "slug": "gpt-5.6-luna",
                        "display_name": "GPT-5.6-Luna",
                        "visibility": "list",
                        "supported_reasoning_levels": ["low", "medium"],
                        "context_window": 272000,
                        "multi_agent_version": "v1",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "spark_cli.codex_models._fetch_model_entries_from_api",
        lambda access_token, timeout=10.0: None,
    )

    catalog = get_codex_model_catalog("token")
    assert catalog["models"] == ["gpt-5.6-luna"]
    assert catalog["source"] == "cache"
    assert catalog["live"] is False
    assert catalog["stale"] is True
    assert catalog["authoritative"] is False
    assert catalog["freshness"] == "2026-08-04T21:52:35Z"
    assert catalog["catalog"][0]["multi_agent_version"] == "v1"


def test_failed_codex_discovery_has_explicit_offline_fallback(monkeypatch, tmp_path):
    from spark_cli.codex_models import get_codex_model_catalog

    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setattr(
        "spark_cli.codex_models._fetch_model_entries_from_api",
        lambda access_token, timeout=10.0: None,
    )
    catalog = get_codex_model_catalog("token")
    assert catalog["source"] == "offline-fallback"
    assert catalog["live"] is False
    assert catalog["models"] == DEFAULT_CODEX_MODELS
    assert "offline fallback" in str(catalog["warning"])
