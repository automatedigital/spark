"""Tests for the spark_cli models module."""

from unittest.mock import patch, MagicMock

from spark_cli.models import (
    OPENROUTER_MODELS, fetch_openrouter_models, model_ids, detect_provider_for_model,
)
import spark_cli.models as _models_mod

LIVE_OPENROUTER_MODELS = [
    ("anthropic/claude-opus-4.6", "recommended"),
    ("qwen/qwen3.6-plus", ""),
    ("nvidia/nemotron-3-super-120b-a12b:free", "free"),
]



class TestModelIds:
    def test_returns_non_empty_list(self):
        with patch("spark_cli.models.fetch_openrouter_models", return_value=LIVE_OPENROUTER_MODELS):
            ids = model_ids()
        assert isinstance(ids, list)
        assert len(ids) > 0

    def test_ids_match_fetched_catalog(self):
        with patch("spark_cli.models.fetch_openrouter_models", return_value=LIVE_OPENROUTER_MODELS):
            ids = model_ids()
        expected = [mid for mid, _ in LIVE_OPENROUTER_MODELS]
        assert ids == expected

    def test_all_ids_contain_provider_slash(self):
        """Model IDs should follow the provider/model format."""
        with patch("spark_cli.models.fetch_openrouter_models", return_value=LIVE_OPENROUTER_MODELS):
            for mid in model_ids():
                assert "/" in mid, f"Model ID '{mid}' missing provider/ prefix"

    def test_no_duplicate_ids(self):
        with patch("spark_cli.models.fetch_openrouter_models", return_value=LIVE_OPENROUTER_MODELS):
            ids = model_ids()
        assert len(ids) == len(set(ids)), "Duplicate model IDs found"





class TestOpenRouterModels:
    def test_structure_is_list_of_tuples(self):
        for entry in OPENROUTER_MODELS:
            assert isinstance(entry, tuple) and len(entry) == 2
            mid, desc = entry
            assert isinstance(mid, str) and len(mid) > 0
            assert isinstance(desc, str)

    def test_at_least_5_models(self):
        """Sanity check that the models list hasn't been accidentally truncated."""
        assert len(OPENROUTER_MODELS) >= 5


class TestFetchOpenRouterModels:
    def test_live_fetch_recomputes_free_tags(self, monkeypatch):
        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"data":[{"id":"anthropic/claude-opus-4.6","pricing":{"prompt":"0.000015","completion":"0.000075"}},{"id":"qwen/qwen3.6-plus","pricing":{"prompt":"0.000000325","completion":"0.00000195"}},{"id":"nvidia/nemotron-3-super-120b-a12b:free","pricing":{"prompt":"0","completion":"0"}}]}'

        monkeypatch.setattr(_models_mod, "_openrouter_catalog_cache", None)
        with patch("spark_cli.models.urllib.request.urlopen", return_value=_Resp()):
            models = fetch_openrouter_models(force_refresh=True)

        assert models == [
            ("anthropic/claude-opus-4.6", "recommended"),
            ("qwen/qwen3.6-plus", ""),
            ("nvidia/nemotron-3-super-120b-a12b:free", "free"),
        ]

    def test_live_fetch_uses_configured_urllib_context(self, monkeypatch):
        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"data":[]}'

        sentinel_context = object()
        monkeypatch.setattr(_models_mod, "_openrouter_catalog_cache", None)
        with (
            patch(
                "spark_cli.models.urllib_request_kwargs",
                return_value={"context": sentinel_context},
            ),
            patch("spark_cli.models.urllib.request.urlopen", return_value=_Resp()) as mock_urlopen,
        ):
            fetch_openrouter_models(force_refresh=True)

        assert mock_urlopen.call_args.kwargs["context"] is sentinel_context

    def test_falls_back_to_static_snapshot_on_fetch_failure(self, monkeypatch):
        monkeypatch.setattr(_models_mod, "_openrouter_catalog_cache", None)
        with patch("spark_cli.models.urllib.request.urlopen", side_effect=OSError("boom")):
            models = fetch_openrouter_models(force_refresh=True)

        assert models == OPENROUTER_MODELS


class TestFindOpenrouterSlug:
    def test_exact_match(self):
        from spark_cli.models import _find_openrouter_slug
        with patch("spark_cli.models.fetch_openrouter_models", return_value=LIVE_OPENROUTER_MODELS):
            assert _find_openrouter_slug("anthropic/claude-opus-4.6") == "anthropic/claude-opus-4.6"

    def test_bare_name_match(self):
        from spark_cli.models import _find_openrouter_slug
        with patch("spark_cli.models.fetch_openrouter_models", return_value=LIVE_OPENROUTER_MODELS):
            result = _find_openrouter_slug("claude-opus-4.6")
        assert result == "anthropic/claude-opus-4.6"

    def test_case_insensitive(self):
        from spark_cli.models import _find_openrouter_slug
        with patch("spark_cli.models.fetch_openrouter_models", return_value=LIVE_OPENROUTER_MODELS):
            result = _find_openrouter_slug("Anthropic/Claude-Opus-4.6")
        assert result is not None

    def test_unknown_returns_none(self):
        from spark_cli.models import _find_openrouter_slug
        with patch("spark_cli.models.fetch_openrouter_models", return_value=LIVE_OPENROUTER_MODELS):
            assert _find_openrouter_slug("totally-fake-model-xyz") is None


class TestDetectProviderForModel:
    def test_anthropic_model_detected(self):
        """claude-opus-4-6 should resolve to anthropic provider."""
        with patch("spark_cli.models.fetch_openrouter_models", return_value=LIVE_OPENROUTER_MODELS):
            result = detect_provider_for_model("claude-opus-4-6", "openai-codex")
        assert result is not None
        assert result[0] == "anthropic"

    def test_deepseek_model_detected(self):
        """deepseek-chat should resolve to deepseek provider."""
        result = detect_provider_for_model("deepseek-chat", "openai-codex")
        assert result is not None
        # Provider is deepseek (direct) or openrouter (fallback) depending on creds
        assert result[0] in ("deepseek", "openrouter")

    def test_current_provider_model_returns_none(self):
        """Models belonging to the current provider should not trigger a switch."""
        assert detect_provider_for_model("gpt-5.3-codex", "openai-codex") is None

    def test_openrouter_slug_match(self):
        """Models in the OpenRouter catalog should be found."""
        with patch("spark_cli.models.fetch_openrouter_models", return_value=LIVE_OPENROUTER_MODELS):
            result = detect_provider_for_model("anthropic/claude-opus-4.6", "openai-codex")
        assert result is not None
        assert result[0] == "openrouter"
        assert result[1] == "anthropic/claude-opus-4.6"

    def test_bare_name_gets_openrouter_slug(self, monkeypatch):
        for env_var in (
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_TOKEN",
            "CLAUDE_CODE_TOKEN",
            "CLAUDE_CODE_OAUTH_TOKEN",
        ):
            monkeypatch.delenv(env_var, raising=False)
        """Bare model names should get mapped to full OpenRouter slugs."""
        with patch("spark_cli.models.fetch_openrouter_models", return_value=LIVE_OPENROUTER_MODELS):
            result = detect_provider_for_model("claude-opus-4.6", "openai-codex")
        assert result is not None
        # Should find it on OpenRouter with full slug
        assert result[1] == "anthropic/claude-opus-4.6"

    def test_unknown_model_returns_none(self):
        """Completely unknown model names should return None."""
        with patch("spark_cli.models.fetch_openrouter_models", return_value=LIVE_OPENROUTER_MODELS):
            assert detect_provider_for_model("nonexistent-model-xyz", "openai-codex") is None

    def test_aggregator_not_suggested(self):
        """nous/openrouter should never be auto-suggested as target provider."""
        with patch("spark_cli.models.fetch_openrouter_models", return_value=LIVE_OPENROUTER_MODELS):
            result = detect_provider_for_model("claude-opus-4-6", "openai-codex")
        assert result is not None
        assert result[0] not in ("nous",)  # nous is no longer a valid provider
