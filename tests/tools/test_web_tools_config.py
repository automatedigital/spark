"""Tests for web backend client configuration and singleton behavior.

Coverage:
  _get_firecrawl_client() — configuration matrix, singleton caching,
  constructor failure recovery, return value verification, edge cases.
  _get_backend() — backend selection logic with env var combinations.
  _get_parallel_client() — Parallel client configuration, singleton caching.
  check_web_api_key() — unified availability check across all web backends.
"""

import asyncio
import json
import os
import sys
import time
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestFirecrawlClientConfig:
    """Test suite for Firecrawl client initialization."""

    def setup_method(self):
        """Reset client and env vars before each test."""
        import tools.web_tools

        tools.web_tools._firecrawl_client = None
        tools.web_tools._firecrawl_client_config = None
        for key in (
            "SPARK_ENABLE_NOUS_MANAGED_TOOLS",
            "FIRECRAWL_API_KEY",
            "FIRECRAWL_API_URL",
            "FIRECRAWL_GATEWAY_URL",
            "TOOL_GATEWAY_DOMAIN",
            "TOOL_GATEWAY_SCHEME",
            "TOOL_GATEWAY_USER_TOKEN",
        ):
            os.environ.pop(key, None)
        os.environ["SPARK_ENABLE_NOUS_MANAGED_TOOLS"] = "1"

    def teardown_method(self):
        """Reset client after each test."""
        import tools.web_tools

        tools.web_tools._firecrawl_client = None
        tools.web_tools._firecrawl_client_config = None
        for key in (
            "SPARK_ENABLE_NOUS_MANAGED_TOOLS",
            "FIRECRAWL_API_KEY",
            "FIRECRAWL_API_URL",
            "FIRECRAWL_GATEWAY_URL",
            "TOOL_GATEWAY_DOMAIN",
            "TOOL_GATEWAY_SCHEME",
            "TOOL_GATEWAY_USER_TOKEN",
        ):
            os.environ.pop(key, None)

    # ── Configuration matrix ─────────────────────────────────────────

    def test_cloud_mode_key_only(self):
        """API key without URL → cloud Firecrawl."""
        with patch.dict(os.environ, {"FIRECRAWL_API_KEY": "fc-test"}):
            with patch("tools.web_tools.Firecrawl") as mock_fc:
                from tools.web_tools import _get_firecrawl_client

                result = _get_firecrawl_client()
                mock_fc.assert_called_once_with(api_key="fc-test")
                assert result is mock_fc.return_value

    def test_self_hosted_with_key(self):
        """Both key + URL → self-hosted with auth."""
        with patch.dict(
            os.environ,
            {
                "FIRECRAWL_API_KEY": "fc-test",
                "FIRECRAWL_API_URL": "http://localhost:3002",
            },
        ):
            with patch("tools.web_tools.Firecrawl") as mock_fc:
                from tools.web_tools import _get_firecrawl_client

                result = _get_firecrawl_client()
                mock_fc.assert_called_once_with(
                    api_key="fc-test", api_url="http://localhost:3002"
                )
                assert result is mock_fc.return_value

    def test_self_hosted_no_key(self):
        """URL only, no key → self-hosted without auth."""
        with patch.dict(os.environ, {"FIRECRAWL_API_URL": "http://localhost:3002"}):
            with patch("tools.web_tools.Firecrawl") as mock_fc:
                from tools.web_tools import _get_firecrawl_client

                result = _get_firecrawl_client()
                mock_fc.assert_called_once_with(api_url="http://localhost:3002")
                assert result is mock_fc.return_value

    def test_no_config_raises_with_helpful_message(self):
        """Neither key nor URL → ValueError with guidance."""
        with patch("tools.web_tools.Firecrawl"):
            from tools.web_tools import _get_firecrawl_client

            with pytest.raises(ValueError, match="FIRECRAWL_API_KEY"):
                _get_firecrawl_client()

    def test_direct_mode_is_preferred_over_tool_gateway(self):
        """Explicit Firecrawl config should win over the gateway fallback."""
        with patch.dict(
            os.environ,
            {
                "FIRECRAWL_API_KEY": "fc-test",
                "TOOL_GATEWAY_DOMAIN": "automatedigital.ai",
            },
        ):
            with patch("tools.web_tools.Firecrawl") as mock_fc:
                from tools.web_tools import _get_firecrawl_client

                _get_firecrawl_client()
            mock_fc.assert_called_once_with(api_key="fc-test")

    def test_check_auxiliary_model_re_resolves_backend_each_call(self):
        """Availability checks should not be pinned to module import state."""
        import tools.web_tools

        # Simulate the pre-fix import-time cache slot for regression coverage.
        tools.web_tools.__dict__["_aux_async_client"] = None

        with patch(
            "tools.web_tools.get_async_text_auxiliary_client",
            side_effect=[
                (None, None),
                (MagicMock(base_url="https://api.openrouter.ai/v1"), "test-model"),
            ],
        ):
            assert tools.web_tools.check_auxiliary_model() is False
            assert tools.web_tools.check_auxiliary_model() is True

    @pytest.mark.asyncio
    async def test_summarizer_re_resolves_backend_after_initial_unavailable_state(self):
        """Summarization should pick up a backend that becomes available later in-process."""
        import tools.web_tools

        tools.web_tools.__dict__["_aux_async_client"] = None

        response = MagicMock()
        response.choices = [MagicMock(message=MagicMock(content="summary text"))]

        with (
            patch(
                "tools.web_tools._resolve_web_extract_auxiliary",
                side_effect=[
                    (None, None, {}),
                    (
                        MagicMock(base_url="https://api.openrouter.ai/v1"),
                        "test-model",
                        {},
                    ),
                ],
            ),
            patch(
                "tools.web_tools.async_call_llm",
                new=AsyncMock(return_value=response),
            ) as mock_async_call,
        ):
            assert tools.web_tools.check_auxiliary_model() is False
            result = await tools.web_tools._call_summarizer_llm(
                "Some content worth summarizing",
                "Source: https://example.com\n\n",
                None,
            )

        assert result == "summary text"
        mock_async_call.assert_awaited_once()

    # ── Singleton caching ────────────────────────────────────────────

    def test_singleton_returns_same_instance(self):
        """Second call returns cached client without re-constructing."""
        with patch.dict(os.environ, {"FIRECRAWL_API_KEY": "fc-test"}):
            with patch("tools.web_tools.Firecrawl") as mock_fc:
                from tools.web_tools import _get_firecrawl_client

                client1 = _get_firecrawl_client()
                client2 = _get_firecrawl_client()
                assert client1 is client2
                mock_fc.assert_called_once()  # constructed only once

    def test_constructor_failure_allows_retry(self):
        """If Firecrawl() raises, next call should retry (not return None)."""
        import tools.web_tools

        with patch.dict(os.environ, {"FIRECRAWL_API_KEY": "fc-test"}):
            with patch("tools.web_tools.Firecrawl") as mock_fc:
                mock_fc.side_effect = [RuntimeError("init failed"), MagicMock()]
                from tools.web_tools import _get_firecrawl_client

                with pytest.raises(RuntimeError):
                    _get_firecrawl_client()

                # Client stayed None, so retry should work
                assert tools.web_tools._firecrawl_client is None
                result = _get_firecrawl_client()
                assert result is not None

    # ── Edge cases ───────────────────────────────────────────────────

    def test_empty_string_key_treated_as_absent(self):
        """FIRECRAWL_API_KEY='' should not be passed as api_key."""
        with patch.dict(
            os.environ,
            {
                "FIRECRAWL_API_KEY": "",
                "FIRECRAWL_API_URL": "http://localhost:3002",
            },
        ):
            with patch("tools.web_tools.Firecrawl") as mock_fc:
                from tools.web_tools import _get_firecrawl_client

                _get_firecrawl_client()
                # Empty string is falsy, so only api_url should be passed
                mock_fc.assert_called_once_with(api_url="http://localhost:3002")

    def test_empty_string_key_no_url_raises(self):
        """FIRECRAWL_API_KEY='' with no URL → should raise."""
        with patch.dict(os.environ, {"FIRECRAWL_API_KEY": ""}):
            with patch("tools.web_tools.Firecrawl"):
                from tools.web_tools import _get_firecrawl_client

                with pytest.raises(ValueError):
                    _get_firecrawl_client()


class TestBackendSelection:
    """Test suite for _get_backend() backend selection logic.

    The backend is configured via config.yaml (web.backend), set by
    ``spark tools``.  Falls back to key-based detection for legacy/manual
    setups.
    """

    _ENV_KEYS = (
        "SPARK_ENABLE_NOUS_MANAGED_TOOLS",
        "EXA_API_KEY",
        "PARALLEL_API_KEY",
        "FIRECRAWL_API_KEY",
        "FIRECRAWL_API_URL",
        "FIRECRAWL_GATEWAY_URL",
        "TOOL_GATEWAY_DOMAIN",
        "TOOL_GATEWAY_SCHEME",
        "TOOL_GATEWAY_USER_TOKEN",
        "TAVILY_API_KEY",
    )

    def setup_method(self):
        os.environ["SPARK_ENABLE_NOUS_MANAGED_TOOLS"] = "1"
        for key in self._ENV_KEYS:
            if key != "SPARK_ENABLE_NOUS_MANAGED_TOOLS":
                os.environ.pop(key, None)

    def teardown_method(self):
        for key in self._ENV_KEYS:
            os.environ.pop(key, None)

    # ── Config-based selection (web.backend in config.yaml) ───────────

    def test_config_parallel(self):
        """web.backend=parallel in config → 'parallel' regardless of keys."""
        from tools.web_tools import _get_backend

        with patch(
            "tools.web_tools._load_web_config", return_value={"backend": "parallel"}
        ):
            assert _get_backend() == "parallel"

    def test_config_exa(self):
        """web.backend=exa in config → 'exa' regardless of other keys."""
        from tools.web_tools import _get_backend

        with (
            patch("tools.web_tools._load_web_config", return_value={"backend": "exa"}),
            patch.dict(os.environ, {"PARALLEL_API_KEY": "test-key"}),
        ):
            assert _get_backend() == "exa"

    def test_config_firecrawl(self):
        """web.backend=firecrawl in config → 'firecrawl' even if Parallel key set."""
        from tools.web_tools import _get_backend

        with (
            patch(
                "tools.web_tools._load_web_config",
                return_value={"backend": "firecrawl"},
            ),
            patch.dict(os.environ, {"PARALLEL_API_KEY": "test-key"}),
        ):
            assert _get_backend() == "firecrawl"

    def test_config_tavily(self):
        """web.backend=tavily in config → 'tavily' regardless of other keys."""
        from tools.web_tools import _get_backend

        with patch(
            "tools.web_tools._load_web_config", return_value={"backend": "tavily"}
        ):
            assert _get_backend() == "tavily"

    def test_config_tavily_overrides_env_keys(self):
        """web.backend=tavily in config → 'tavily' even if Firecrawl key set."""
        from tools.web_tools import _get_backend

        with (
            patch(
                "tools.web_tools._load_web_config", return_value={"backend": "tavily"}
            ),
            patch.dict(os.environ, {"FIRECRAWL_API_KEY": "fc-test"}),
        ):
            assert _get_backend() == "tavily"

    def test_config_case_insensitive(self):
        """web.backend=Parallel (mixed case) → 'parallel'."""
        from tools.web_tools import _get_backend

        with patch(
            "tools.web_tools._load_web_config", return_value={"backend": "Parallel"}
        ):
            assert _get_backend() == "parallel"

    def test_config_tavily_case_insensitive(self):
        """web.backend=Tavily (mixed case) → 'tavily'."""
        from tools.web_tools import _get_backend

        with patch(
            "tools.web_tools._load_web_config", return_value={"backend": "Tavily"}
        ):
            assert _get_backend() == "tavily"

    # ── Fallback (no web.backend in config) ───────────────────────────

    def test_fallback_parallel_only_key(self):
        """Only PARALLEL_API_KEY set → 'parallel'."""
        from tools.web_tools import _get_backend

        with (
            patch("tools.web_tools._load_web_config", return_value={}),
            patch.dict(os.environ, {"PARALLEL_API_KEY": "test-key"}),
        ):
            assert _get_backend() == "parallel"

    def test_fallback_exa_only_key(self):
        """Only EXA_API_KEY set → 'exa'."""
        from tools.web_tools import _get_backend

        with (
            patch("tools.web_tools._load_web_config", return_value={}),
            patch.dict(os.environ, {"EXA_API_KEY": "exa-test"}),
        ):
            assert _get_backend() == "exa"

    def test_fallback_parallel_takes_priority_over_exa(self):
        """Exa should only win the fallback path when it is the only configured backend."""
        from tools.web_tools import _get_backend

        with (
            patch("tools.web_tools._load_web_config", return_value={}),
            patch.dict(
                os.environ, {"EXA_API_KEY": "exa-test", "PARALLEL_API_KEY": "par-test"}
            ),
        ):
            assert _get_backend() == "parallel"

    def test_fallback_tavily_only_key(self):
        """Only TAVILY_API_KEY set → 'tavily'."""
        from tools.web_tools import _get_backend

        with (
            patch("tools.web_tools._load_web_config", return_value={}),
            patch.dict(os.environ, {"TAVILY_API_KEY": "tvly-test"}),
        ):
            assert _get_backend() == "tavily"

    def test_fallback_tavily_with_firecrawl_prefers_firecrawl(self):
        """Tavily + Firecrawl keys, no config → 'firecrawl' (backward compat)."""
        from tools.web_tools import _get_backend

        with (
            patch("tools.web_tools._load_web_config", return_value={}),
            patch.dict(
                os.environ,
                {"TAVILY_API_KEY": "tvly-test", "FIRECRAWL_API_KEY": "fc-test"},
            ),
        ):
            assert _get_backend() == "firecrawl"

    def test_fallback_tavily_with_parallel_prefers_parallel(self):
        """Tavily + Parallel keys, no config → 'parallel' (Parallel takes priority over Tavily)."""
        from tools.web_tools import _get_backend

        with (
            patch("tools.web_tools._load_web_config", return_value={}),
            patch.dict(
                os.environ,
                {"TAVILY_API_KEY": "tvly-test", "PARALLEL_API_KEY": "par-test"},
            ),
        ):
            # Parallel + no Firecrawl → parallel
            assert _get_backend() == "parallel"

    def test_fallback_both_keys_defaults_to_firecrawl(self):
        """Both keys set, no config → 'firecrawl' (backward compat)."""
        from tools.web_tools import _get_backend

        with (
            patch("tools.web_tools._load_web_config", return_value={}),
            patch.dict(
                os.environ,
                {"PARALLEL_API_KEY": "test-key", "FIRECRAWL_API_KEY": "fc-test"},
            ),
        ):
            assert _get_backend() == "firecrawl"

    def test_fallback_firecrawl_only_key(self):
        """Only FIRECRAWL_API_KEY set → 'firecrawl'."""
        from tools.web_tools import _get_backend

        with (
            patch("tools.web_tools._load_web_config", return_value={}),
            patch.dict(os.environ, {"FIRECRAWL_API_KEY": "fc-test"}),
        ):
            assert _get_backend() == "firecrawl"

    def test_fallback_no_keys_defaults_to_firecrawl(self):
        """No keys, no config → 'firecrawl' (will fail at client init)."""
        from tools.web_tools import _get_backend

        with patch("tools.web_tools._load_web_config", return_value={}):
            assert _get_backend() == "firecrawl"

    def test_invalid_config_falls_through_to_fallback(self):
        """web.backend=invalid → ignored, uses key-based fallback."""
        from tools.web_tools import _get_backend

        with (
            patch(
                "tools.web_tools._load_web_config",
                return_value={"backend": "nonexistent"},
            ),
            patch.dict(os.environ, {"PARALLEL_API_KEY": "test-key"}),
        ):
            assert _get_backend() == "parallel"


class TestParallelClientConfig:
    """Test suite for Parallel client initialization."""

    def setup_method(self):
        import tools.web_tools

        tools.web_tools._parallel_client = None
        os.environ.pop("PARALLEL_API_KEY", None)
        fake_parallel = types.ModuleType("parallel")

        class Parallel:
            def __init__(self, api_key):
                self.api_key = api_key

        class AsyncParallel:
            def __init__(self, api_key):
                self.api_key = api_key

        fake_parallel.Parallel = Parallel
        fake_parallel.AsyncParallel = AsyncParallel
        sys.modules["parallel"] = fake_parallel

    def teardown_method(self):
        import tools.web_tools

        tools.web_tools._parallel_client = None
        os.environ.pop("PARALLEL_API_KEY", None)
        sys.modules.pop("parallel", None)

    def test_creates_client_with_key(self):
        """PARALLEL_API_KEY set → creates Parallel client."""
        with patch.dict(os.environ, {"PARALLEL_API_KEY": "test-key"}):
            from parallel import Parallel

            from tools.web_tools import _get_parallel_client

            client = _get_parallel_client()
            assert client is not None
            assert isinstance(client, Parallel)

    def test_no_key_raises_with_helpful_message(self):
        """No PARALLEL_API_KEY → ValueError with guidance."""
        from tools.web_tools import _get_parallel_client

        with pytest.raises(ValueError, match="PARALLEL_API_KEY"):
            _get_parallel_client()

    def test_singleton_returns_same_instance(self):
        """Second call returns cached client."""
        with patch.dict(os.environ, {"PARALLEL_API_KEY": "test-key"}):
            from tools.web_tools import _get_parallel_client

            client1 = _get_parallel_client()
            client2 = _get_parallel_client()
            assert client1 is client2


class TestWebSearchErrorHandling:
    """Test suite for web_search_tool() error responses."""

    def test_search_error_response_does_not_expose_diagnostics(self):
        import tools.web_tools

        firecrawl_client = MagicMock()
        firecrawl_client.search.side_effect = RuntimeError("boom")

        with (
            patch("tools.web_tools._get_backend", return_value="firecrawl"),
            patch(
                "tools.web_tools._get_firecrawl_client", return_value=firecrawl_client
            ),
            patch("tools.interrupt.is_interrupted", return_value=False),
            patch.object(tools.web_tools._debug, "log_call") as mock_log_call,
            patch.object(tools.web_tools._debug, "save"),
        ):
            result = json.loads(tools.web_tools.web_search_tool("test query", limit=3))

        assert result == {"error": "Error searching web: boom"}

        debug_payload = mock_log_call.call_args.args[1]
        assert debug_payload["error"] == "Error searching web: boom"
        assert "traceback" not in debug_payload["error"]
        assert "exception_type" not in debug_payload["error"]
        assert "config" not in result
        assert "exception_type" not in result
        assert "exception_chain" not in result
        assert "traceback" not in result


class TestCheckWebApiKey:
    """Test suite for check_web_api_key() unified availability check."""

    _ENV_KEYS = (
        "SPARK_ENABLE_NOUS_MANAGED_TOOLS",
        "EXA_API_KEY",
        "PARALLEL_API_KEY",
        "FIRECRAWL_API_KEY",
        "FIRECRAWL_API_URL",
        "FIRECRAWL_GATEWAY_URL",
        "TOOL_GATEWAY_DOMAIN",
        "TOOL_GATEWAY_SCHEME",
        "TOOL_GATEWAY_USER_TOKEN",
        "TAVILY_API_KEY",
    )

    def setup_method(self):
        os.environ["SPARK_ENABLE_NOUS_MANAGED_TOOLS"] = "1"
        for key in self._ENV_KEYS:
            if key != "SPARK_ENABLE_NOUS_MANAGED_TOOLS":
                os.environ.pop(key, None)

    def teardown_method(self):
        for key in self._ENV_KEYS:
            os.environ.pop(key, None)

    def test_parallel_key_only(self):
        with patch.dict(os.environ, {"PARALLEL_API_KEY": "test-key"}):
            from tools.web_tools import check_web_api_key

            assert check_web_api_key() is True

    def test_exa_key_only(self):
        with patch.dict(os.environ, {"EXA_API_KEY": "exa-test"}):
            from tools.web_tools import check_web_api_key

            assert check_web_api_key() is True

    def test_firecrawl_key_only(self):
        with patch.dict(os.environ, {"FIRECRAWL_API_KEY": "fc-test"}):
            from tools.web_tools import check_web_api_key

            assert check_web_api_key() is True

    def test_firecrawl_url_only(self):
        with patch.dict(os.environ, {"FIRECRAWL_API_URL": "http://localhost:3002"}):
            from tools.web_tools import check_web_api_key

            assert check_web_api_key() is True

    def test_tavily_key_only(self):
        with patch.dict(os.environ, {"TAVILY_API_KEY": "tvly-test"}):
            from tools.web_tools import check_web_api_key

            assert check_web_api_key() is True

    def test_no_keys_returns_false(self):
        from tools.web_tools import check_web_api_key

        assert check_web_api_key() is False

    def test_both_keys_returns_true(self):
        with patch.dict(
            os.environ,
            {
                "PARALLEL_API_KEY": "test-key",
                "FIRECRAWL_API_KEY": "fc-test",
            },
        ):
            from tools.web_tools import check_web_api_key

            assert check_web_api_key() is True

    def test_all_three_keys_returns_true(self):
        with patch.dict(
            os.environ,
            {
                "PARALLEL_API_KEY": "test-key",
                "FIRECRAWL_API_KEY": "fc-test",
                "TAVILY_API_KEY": "tvly-test",
            },
        ):
            from tools.web_tools import check_web_api_key

            assert check_web_api_key() is True

    def test_configured_backend_must_match_available_provider(self):
        with patch(
            "tools.web_tools._load_web_config", return_value={"backend": "parallel"}
        ):
            with patch.dict(
                os.environ,
                {"FIRECRAWL_GATEWAY_URL": "http://127.0.0.1:3002"},
                clear=False,
            ):
                from tools.web_tools import check_web_api_key

                assert check_web_api_key() is False

    def test_configured_firecrawl_backend_no_direct_config_returns_false(self):
        """With backend=firecrawl but no direct key/URL and gateway always off, returns False."""
        with patch(
            "tools.web_tools._load_web_config", return_value={"backend": "firecrawl"}
        ):
            with patch.dict(
                os.environ,
                {"FIRECRAWL_GATEWAY_URL": "http://127.0.0.1:3002"},
                clear=False,
            ):
                from tools.web_tools import check_web_api_key

                assert check_web_api_key() is False


def test_web_requires_env_includes_exa_key():
    from tools.web_tools import _web_requires_env

    assert "EXA_API_KEY" in _web_requires_env()


class TestWebToolFastDefaults:
    """Regression coverage for web tools staying fast in normal chat use."""

    def test_parallel_search_defaults_to_fast_mode(self):
        import tools.web_tools

        client = MagicMock()
        client.beta.search.return_value.results = []

        with patch("tools.web_tools._get_parallel_client", return_value=client), \
             patch.dict(os.environ, {}, clear=True), \
             patch("tools.interrupt.is_interrupted", return_value=False):
            result = tools.web_tools._parallel_search("best llm model", limit=5)

        assert result == {"success": True, "data": {"web": []}}
        assert client.beta.search.call_args.kwargs["mode"] == "fast"

    def test_registered_web_extract_handler_disables_llm_processing_by_default(self):
        import tools.web_tools as web_tools
        from tools.registry import registry

        assert web_tools.WEB_EXTRACT_SCHEMA["name"] == "web_extract"
        entry = registry.get_entry("web_extract")
        assert entry is not None

        with patch("tools.web_tools.web_extract_tool", new=AsyncMock(return_value='{"results": []}')) as mock_extract:
            result = asyncio.get_event_loop().run_until_complete(
                entry.handler({"urls": ["https://example.com"]})
            )

        assert result == '{"results": []}'
        assert mock_extract.await_args.kwargs["use_llm_processing"] is False
        assert mock_extract.await_args.kwargs["max_chars_per_page"] == 12_000

    def test_firecrawl_extract_scrapes_urls_concurrently(self):
        import tools.web_tools

        class FakeFirecrawl:
            def scrape(self, url, formats):
                time.sleep(0.3)
                return {
                    "metadata": {"title": url, "sourceURL": url},
                    "markdown": f"content for {url}",
                }

        urls = ["https://example.com/a", "https://example.com/b"]

        with patch("tools.web_tools._get_backend", return_value="firecrawl"), \
             patch("tools.web_tools._get_firecrawl_client", return_value=FakeFirecrawl()), \
             patch("tools.web_tools.is_safe_url", return_value=True), \
             patch("tools.web_tools.check_website_access", return_value=None), \
             patch("tools.interrupt.is_interrupted", return_value=False), \
             patch.dict(os.environ, {
                 "WEB_EXTRACT_CONCURRENCY": "2",
                 "WEB_EXTRACT_SCRAPE_TIMEOUT": "5",
                 "WEB_EXTRACT_FAST_FETCH": "false",
             }):
            start = time.monotonic()
            result = asyncio.get_event_loop().run_until_complete(
                tools.web_tools.web_extract_tool(urls, use_llm_processing=False)
            )
            elapsed = time.monotonic() - start

        payload = json.loads(result)
        assert elapsed < 0.55
        assert [item["url"] for item in payload["results"]] == urls
        assert all("content for https://example.com/" in item["content"] for item in payload["results"])

    def test_firecrawl_backend_uses_fast_fetch_before_scrape(self):
        import tools.web_tools

        class FakeResponse:
            url = "https://example.com/page"
            headers = {"content-type": "text/html; charset=utf-8"}
            text = """
            <html>
              <head><title>Example Page</title><script>ignore()</script></head>
              <body>
                <h1>Current LLM Rankings</h1>
                <p>Claude Opus 4.8 and GPT-5.5 are leading frontier models.</p>
                <p>This paragraph gives enough useful body content for fast extraction.</p>
                <p>Additional benchmark notes make the extracted page long enough.</p>
              </body>
            </html>
            """

            def raise_for_status(self):
                return None

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url):
                return FakeResponse()

        with patch("tools.web_tools._get_backend", return_value="firecrawl"), \
             patch("tools.web_tools.httpx.AsyncClient", FakeAsyncClient), \
             patch("tools.web_tools._get_firecrawl_client") as firecrawl_client, \
             patch("tools.web_tools.is_safe_url", return_value=True), \
             patch("tools.web_tools.check_website_access", return_value=None), \
             patch("tools.interrupt.is_interrupted", return_value=False), \
             patch.dict(os.environ, {
                 "WEB_EXTRACT_FAST_FETCH": "true",
                 "WEB_EXTRACT_FAST_FETCH_MIN_CHARS": "50",
             }):
            result = asyncio.get_event_loop().run_until_complete(
                tools.web_tools.web_extract_tool(["https://example.com/page"], use_llm_processing=False)
            )

        payload = json.loads(result)
        assert firecrawl_client.call_count == 0
        assert payload["results"][0]["title"] == "Example Page"
        assert "Current LLM Rankings" in payload["results"][0]["content"]
