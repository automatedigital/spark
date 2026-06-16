"""Tests for gateway.platforms.telegram_network – fallback transport layer.

Background
----------
api.telegram.org resolves to an IP (e.g. 149.154.166.110) that is unreachable
from some networks.  The workaround: route TCP through a different IP in the
same Telegram-owned 149.154.160.0/20 block (e.g. 149.154.167.220) while
keeping TLS SNI and the Host header as api.telegram.org so Telegram's edge
servers still accept the request.  This is the programmatic equivalent of:

    curl --resolve api.telegram.org:443:149.154.167.220 https://api.telegram.org/bot<token>/getMe

The TelegramFallbackTransport implements this: try the primary (DNS-resolved)
path first, and on ConnectTimeout / ConnectError fall through to configured
fallback IPs in order, then "stick" to whichever IP works.
"""

import httpx
import pytest

from gateway.platforms import telegram_network as tnet


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeTransport(httpx.AsyncBaseTransport):
    """Records calls and raises / returns based on a host→action mapping."""

    def __init__(self, calls, behavior):
        self.calls = calls
        self.behavior = behavior
        self.closed = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(
            {
                "url_host": request.url.host,
                "host_header": request.headers.get("host"),
                "sni_hostname": request.extensions.get("sni_hostname"),
                "path": request.url.path,
            }
        )
        action = self.behavior.get(request.url.host, "ok")
        if action == "timeout":
            raise httpx.ConnectTimeout("timed out")
        if action == "connect_error":
            raise httpx.ConnectError("connect error")
        if isinstance(action, Exception):
            raise action
        return httpx.Response(200, request=request, text="ok")

    async def aclose(self) -> None:
        self.closed = True


def _fake_transport_factory(calls, behavior):
    """Returns a factory that creates FakeTransport instances."""
    instances = []

    def factory(**kwargs):
        t = FakeTransport(calls, behavior)
        instances.append(t)
        return t

    factory.instances = instances
    return factory


def _telegram_request(path="/botTOKEN/getMe"):
    return httpx.Request("GET", f"https://api.telegram.org{path}")


@pytest.fixture(autouse=True)
def _fast_fallback_retries(monkeypatch):
    """Keep per-IP retry behaviour deterministic and instant in tests.

    Default to a single connect attempt (so existing call-count assertions
    hold) and zero backoff (so failure paths don't actually sleep). Tests that
    exercise the retry logic override ``_FALLBACK_CONNECT_ATTEMPTS`` locally.
    """
    monkeypatch.setattr(tnet, "_FALLBACK_CONNECT_ATTEMPTS", 1)
    monkeypatch.setattr(tnet, "_FALLBACK_RETRY_BACKOFF", 0)


# ═══════════════════════════════════════════════════════════════════════════
# IP parsing & validation
# ═══════════════════════════════════════════════════════════════════════════

class TestParseFallbackIpEnv:
    def test_filters_invalid_and_ipv6(self, caplog):
        ips = tnet.parse_fallback_ip_env("149.154.167.220, bad, 2001:67c:4e8:f004::9,149.154.167.220")
        assert ips == ["149.154.167.220", "149.154.167.220"]
        assert "Ignoring invalid Telegram fallback IP" in caplog.text
        assert "Ignoring non-IPv4 Telegram fallback IP" in caplog.text

    def test_none_returns_empty(self):
        assert tnet.parse_fallback_ip_env(None) == []

    def test_empty_string_returns_empty(self):
        assert tnet.parse_fallback_ip_env("") == []

    def test_whitespace_only_returns_empty(self):
        assert tnet.parse_fallback_ip_env("  ,  , ") == []

    def test_single_valid_ip(self):
        assert tnet.parse_fallback_ip_env("149.154.167.220") == ["149.154.167.220"]

    def test_multiple_valid_ips(self):
        ips = tnet.parse_fallback_ip_env("149.154.167.220, 149.154.167.221")
        assert ips == ["149.154.167.220", "149.154.167.221"]

    def test_rejects_leading_zeros(self, caplog):
        """Leading zeros are ambiguous (octal?) so ipaddress rejects them."""
        ips = tnet.parse_fallback_ip_env("149.154.167.010")
        assert ips == []
        assert "Ignoring invalid" in caplog.text


class TestNormalizeFallbackIps:
    def test_deduplication_happens_at_transport_level(self):
        """_normalize does not dedup; TelegramFallbackTransport.__init__ does."""
        raw = ["149.154.167.220", "149.154.167.220"]
        assert tnet._normalize_fallback_ips(raw) == ["149.154.167.220", "149.154.167.220"]

    def test_empty_strings_skipped(self):
        assert tnet._normalize_fallback_ips(["", "  ", "149.154.167.220"]) == ["149.154.167.220"]


# ═══════════════════════════════════════════════════════════════════════════
# Request rewriting
# ═══════════════════════════════════════════════════════════════════════════

class TestRewriteRequestForIp:
    def test_preserves_host_and_sni(self):
        request = _telegram_request()
        rewritten = tnet._rewrite_request_for_ip(request, "149.154.167.220")

        assert rewritten.url.host == "149.154.167.220"
        assert rewritten.headers["host"] == "api.telegram.org"
        assert rewritten.extensions["sni_hostname"] == "api.telegram.org"
        assert rewritten.url.path == "/botTOKEN/getMe"

    def test_preserves_method_and_path(self):
        request = httpx.Request("POST", "https://api.telegram.org/botTOKEN/sendMessage")
        rewritten = tnet._rewrite_request_for_ip(request, "149.154.167.220")

        assert rewritten.method == "POST"
        assert rewritten.url.path == "/botTOKEN/sendMessage"


# ═══════════════════════════════════════════════════════════════════════════
# Fallback transport – core behavior
# ═══════════════════════════════════════════════════════════════════════════

class TestFallbackTransport:
    """Primary path fails → try fallback IPs → stick to whichever works."""

    @pytest.mark.asyncio
    async def test_falls_back_on_connect_timeout_and_becomes_sticky(self, monkeypatch):
        calls = []
        behavior = {"api.telegram.org": "timeout", "149.154.167.220": "ok"}
        monkeypatch.setattr(tnet.httpx, "AsyncHTTPTransport", _fake_transport_factory(calls, behavior))

        transport = tnet.TelegramFallbackTransport(["149.154.167.220"])
        resp = await transport.handle_async_request(_telegram_request())

        assert resp.status_code == 200
        assert transport._sticky_ip == "149.154.167.220"
        # First attempt was primary (api.telegram.org), second was fallback
        assert calls[0]["url_host"] == "api.telegram.org"
        assert calls[1]["url_host"] == "149.154.167.220"
        assert calls[1]["host_header"] == "api.telegram.org"
        assert calls[1]["sni_hostname"] == "api.telegram.org"

        # Second request goes straight to sticky IP
        calls.clear()
        resp2 = await transport.handle_async_request(_telegram_request())
        assert resp2.status_code == 200
        assert calls[0]["url_host"] == "149.154.167.220"

    @pytest.mark.asyncio
    async def test_falls_back_on_connect_error(self, monkeypatch):
        calls = []
        behavior = {"api.telegram.org": "connect_error", "149.154.167.220": "ok"}
        monkeypatch.setattr(tnet.httpx, "AsyncHTTPTransport", _fake_transport_factory(calls, behavior))

        transport = tnet.TelegramFallbackTransport(["149.154.167.220"])
        resp = await transport.handle_async_request(_telegram_request())

        assert resp.status_code == 200
        assert transport._sticky_ip == "149.154.167.220"

    @pytest.mark.asyncio
    async def test_does_not_fallback_on_non_connect_error(self, monkeypatch):
        """Errors like ReadTimeout are not connection issues — don't retry."""
        calls = []
        behavior = {"api.telegram.org": httpx.ReadTimeout("read timeout"), "149.154.167.220": "ok"}
        monkeypatch.setattr(tnet.httpx, "AsyncHTTPTransport", _fake_transport_factory(calls, behavior))

        transport = tnet.TelegramFallbackTransport(["149.154.167.220"])

        with pytest.raises(httpx.ReadTimeout):
            await transport.handle_async_request(_telegram_request())

        assert [c["url_host"] for c in calls] == ["api.telegram.org"]

    @pytest.mark.asyncio
    async def test_all_ips_fail_raises_last_error(self, monkeypatch):
        calls = []
        behavior = {"api.telegram.org": "timeout", "149.154.167.220": "timeout"}
        monkeypatch.setattr(tnet.httpx, "AsyncHTTPTransport", _fake_transport_factory(calls, behavior))

        transport = tnet.TelegramFallbackTransport(["149.154.167.220"])

        with pytest.raises(httpx.ConnectTimeout):
            await transport.handle_async_request(_telegram_request())

        assert [c["url_host"] for c in calls] == ["api.telegram.org", "149.154.167.220"]
        assert transport._sticky_ip is None

    @pytest.mark.asyncio
    async def test_multiple_fallback_ips_tried_in_order(self, monkeypatch):
        calls = []
        behavior = {
            "api.telegram.org": "timeout",
            "149.154.167.220": "timeout",
            "149.154.167.221": "ok",
        }
        monkeypatch.setattr(tnet.httpx, "AsyncHTTPTransport", _fake_transport_factory(calls, behavior))

        transport = tnet.TelegramFallbackTransport(["149.154.167.220", "149.154.167.221"])
        resp = await transport.handle_async_request(_telegram_request())

        assert resp.status_code == 200
        assert transport._sticky_ip == "149.154.167.221"
        assert [c["url_host"] for c in calls] == [
            "api.telegram.org",
            "149.154.167.220",
            "149.154.167.221",
        ]

    @pytest.mark.asyncio
    async def test_sticky_ip_tried_first_but_falls_through_if_stale(self, monkeypatch):
        """If the sticky IP stops working, the transport retries others."""
        calls = []
        behavior = {
            "api.telegram.org": "timeout",
            "149.154.167.220": "ok",
            "149.154.167.221": "ok",
        }
        monkeypatch.setattr(tnet.httpx, "AsyncHTTPTransport", _fake_transport_factory(calls, behavior))

        transport = tnet.TelegramFallbackTransport(["149.154.167.220", "149.154.167.221"])

        # First request: primary fails → .220 works → becomes sticky
        await transport.handle_async_request(_telegram_request())
        assert transport._sticky_ip == "149.154.167.220"

        # Now .220 goes bad too
        calls.clear()
        behavior["149.154.167.220"] = "timeout"

        resp = await transport.handle_async_request(_telegram_request())
        assert resp.status_code == 200
        # Tried sticky (.220) first, then fell through to .221
        assert [c["url_host"] for c in calls] == ["149.154.167.220", "149.154.167.221"]
        assert transport._sticky_ip == "149.154.167.221"


class TestFallbackTransportPassthrough:
    """Requests that don't need fallback behavior."""

    @pytest.mark.asyncio
    async def test_non_telegram_host_bypasses_fallback(self, monkeypatch):
        calls = []
        behavior = {}
        monkeypatch.setattr(tnet.httpx, "AsyncHTTPTransport", _fake_transport_factory(calls, behavior))

        transport = tnet.TelegramFallbackTransport(["149.154.167.220"])
        request = httpx.Request("GET", "https://example.com/path")
        resp = await transport.handle_async_request(request)

        assert resp.status_code == 200
        assert calls[0]["url_host"] == "example.com"
        assert transport._sticky_ip is None

    @pytest.mark.asyncio
    async def test_empty_fallback_list_uses_primary_only(self, monkeypatch):
        calls = []
        behavior = {}
        monkeypatch.setattr(tnet.httpx, "AsyncHTTPTransport", _fake_transport_factory(calls, behavior))

        transport = tnet.TelegramFallbackTransport([])
        resp = await transport.handle_async_request(_telegram_request())

        assert resp.status_code == 200
        assert calls[0]["url_host"] == "api.telegram.org"

    @pytest.mark.asyncio
    async def test_primary_succeeds_no_fallback_needed(self, monkeypatch):
        calls = []
        behavior = {"api.telegram.org": "ok"}
        monkeypatch.setattr(tnet.httpx, "AsyncHTTPTransport", _fake_transport_factory(calls, behavior))

        transport = tnet.TelegramFallbackTransport(["149.154.167.220"])
        resp = await transport.handle_async_request(_telegram_request())

        assert resp.status_code == 200
        assert transport._sticky_ip is None
        assert len(calls) == 1


class TestFallbackTransportInit:
    def test_deduplicates_fallback_ips(self, monkeypatch):
        monkeypatch.setattr(
            tnet.httpx, "AsyncHTTPTransport", lambda **kw: FakeTransport([], {})
        )
        transport = tnet.TelegramFallbackTransport(["149.154.167.220", "149.154.167.220"])
        assert transport._fallback_ips == ["149.154.167.220"]

    def test_filters_invalid_ips_at_init(self, monkeypatch):
        monkeypatch.setattr(
            tnet.httpx, "AsyncHTTPTransport", lambda **kw: FakeTransport([], {})
        )
        transport = tnet.TelegramFallbackTransport(["149.154.167.220", "not-an-ip"])
        assert transport._fallback_ips == ["149.154.167.220"]

    def test_uses_proxy_env_for_primary_and_fallback_transports(self, monkeypatch):
        seen_kwargs = []

        def factory(**kwargs):
            seen_kwargs.append(kwargs.copy())
            return FakeTransport([], {})

        for key in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy"):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:8080")
        monkeypatch.setattr(tnet.httpx, "AsyncHTTPTransport", factory)

        transport = tnet.TelegramFallbackTransport(["149.154.167.220"])

        assert transport._fallback_ips == ["149.154.167.220"]
        assert len(seen_kwargs) == 2
        assert all(kwargs["proxy"] == "http://proxy.example:8080" for kwargs in seen_kwargs)


class TestFallbackTransportClose:
    @pytest.mark.asyncio
    async def test_aclose_closes_all_transports(self, monkeypatch):
        factory = _fake_transport_factory([], {})
        monkeypatch.setattr(tnet.httpx, "AsyncHTTPTransport", factory)

        transport = tnet.TelegramFallbackTransport(["149.154.167.220", "149.154.167.221"])
        await transport.aclose()

        # 1 primary + 2 fallback transports
        assert len(factory.instances) == 3
        assert all(t.closed for t in factory.instances)


# ═══════════════════════════════════════════════════════════════════════════
# Config layer – TELEGRAM_FALLBACK_IPS env → config.extra
# ═══════════════════════════════════════════════════════════════════════════

class TestConfigFallbackIps:
    def test_env_var_populates_config_extra(self, monkeypatch):
        from gateway.config import GatewayConfig, Platform, PlatformConfig, _apply_env_overrides

        monkeypatch.setenv("TELEGRAM_FALLBACK_IPS", "149.154.167.220,149.154.167.221")
        config = GatewayConfig(platforms={Platform.TELEGRAM: PlatformConfig(enabled=True, token="tok")})
        _apply_env_overrides(config)

        assert config.platforms[Platform.TELEGRAM].extra["fallback_ips"] == [
            "149.154.167.220", "149.154.167.221",
        ]

    def test_env_var_creates_platform_if_missing(self, monkeypatch):
        from gateway.config import GatewayConfig, Platform, _apply_env_overrides

        monkeypatch.setenv("TELEGRAM_FALLBACK_IPS", "149.154.167.220")
        config = GatewayConfig(platforms={})
        _apply_env_overrides(config)

        assert Platform.TELEGRAM in config.platforms
        assert config.platforms[Platform.TELEGRAM].extra["fallback_ips"] == ["149.154.167.220"]

    def test_env_var_strips_whitespace(self, monkeypatch):
        from gateway.config import GatewayConfig, Platform, PlatformConfig, _apply_env_overrides

        monkeypatch.setenv("TELEGRAM_FALLBACK_IPS", "  149.154.167.220 , 149.154.167.221  ")
        config = GatewayConfig(platforms={Platform.TELEGRAM: PlatformConfig(enabled=True, token="tok")})
        _apply_env_overrides(config)

        assert config.platforms[Platform.TELEGRAM].extra["fallback_ips"] == [
            "149.154.167.220", "149.154.167.221",
        ]

    def test_empty_env_var_does_not_populate(self, monkeypatch):
        from gateway.config import GatewayConfig, Platform, PlatformConfig, _apply_env_overrides

        monkeypatch.setenv("TELEGRAM_FALLBACK_IPS", "")
        config = GatewayConfig(platforms={Platform.TELEGRAM: PlatformConfig(enabled=True, token="tok")})
        _apply_env_overrides(config)

        assert "fallback_ips" not in config.platforms[Platform.TELEGRAM].extra


# ═══════════════════════════════════════════════════════════════════════════
# Adapter layer – _fallback_ips() reads config correctly
# ═══════════════════════════════════════════════════════════════════════════

class TestAdapterFallbackIps:
    def _make_adapter(self, extra=None):
        import sys
        from unittest.mock import MagicMock

        # Ensure telegram mock is in place
        if "telegram" not in sys.modules or not hasattr(sys.modules["telegram"], "__file__"):
            mod = MagicMock()
            mod.ext.ContextTypes.DEFAULT_TYPE = type(None)
            mod.constants.ParseMode.MARKDOWN_V2 = "MarkdownV2"
            mod.constants.ChatType.GROUP = "group"
            mod.constants.ChatType.SUPERGROUP = "supergroup"
            mod.constants.ChatType.CHANNEL = "channel"
            mod.constants.ChatType.PRIVATE = "private"
            for name in ("telegram", "telegram.ext", "telegram.constants", "telegram.request"):
                sys.modules.setdefault(name, mod)

        from gateway.config import PlatformConfig
        from gateway.platforms.telegram import TelegramAdapter

        config = PlatformConfig(enabled=True, token="test-token")
        if extra:
            config.extra.update(extra)
        return TelegramAdapter(config)

    def test_list_in_extra(self):
        adapter = self._make_adapter(extra={"fallback_ips": ["149.154.167.220"]})
        assert adapter._fallback_ips() == ["149.154.167.220"]

    def test_csv_string_in_extra(self):
        adapter = self._make_adapter(extra={"fallback_ips": "149.154.167.220,149.154.167.221"})
        assert adapter._fallback_ips() == ["149.154.167.220", "149.154.167.221"]

    def test_empty_extra(self):
        adapter = self._make_adapter()
        assert adapter._fallback_ips() == []

    def test_no_extra_attr(self):
        adapter = self._make_adapter()
        adapter.config.extra = None
        assert adapter._fallback_ips() == []

    def test_invalid_ips_filtered(self):
        adapter = self._make_adapter(extra={"fallback_ips": ["149.154.167.220", "not-valid"]})
        assert adapter._fallback_ips() == ["149.154.167.220"]


# ═══════════════════════════════════════════════════════════════════════════
# DoH auto-discovery
# ═══════════════════════════════════════════════════════════════════════════

def _doh_answer(*ips: str) -> dict:
    """Build a minimal DoH JSON response with A records."""
    return {"Answer": [{"type": 1, "data": ip} for ip in ips]}


class FakeDoHClient:
    """Mock httpx.AsyncClient for DoH queries."""

    def __init__(self, responses: dict):
        # responses: URL prefix → (status, json_body) | Exception
        self._responses = responses
        self.requests_made: list[dict] = []

    @staticmethod
    def _make_response(status, body, url):
        """Build an httpx.Response with a request attached (needed for raise_for_status)."""
        request = httpx.Request("GET", url)
        return httpx.Response(status, json=body, request=request)

    async def get(self, url, *, params=None, headers=None, **kwargs):
        self.requests_made.append({"url": url, "params": params, "headers": headers})
        for prefix, action in self._responses.items():
            if url.startswith(prefix):
                if isinstance(action, Exception):
                    raise action
                status, body = action
                return self._make_response(status, body, url)
        return self._make_response(200, {}, url)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class TestDiscoverFallbackIps:
    """Tests for discover_fallback_ips() — DoH-based auto-discovery."""

    def _patch_doh(self, monkeypatch, responses, system_dns_ips=None):
        """Wire up fake DoH client and system DNS."""
        client = FakeDoHClient(responses)
        monkeypatch.setattr(tnet.httpx, "AsyncClient", lambda **kw: client)

        if system_dns_ips is not None:
            addrs = [(None, None, None, None, (ip, 443)) for ip in system_dns_ips]
            monkeypatch.setattr(tnet.socket, "getaddrinfo", lambda *a, **kw: addrs)
        else:
            def _fail(*a, **kw):
                raise OSError("dns failed")
            monkeypatch.setattr(tnet.socket, "getaddrinfo", _fail)
        return client

    @pytest.mark.asyncio
    async def test_google_and_cloudflare_ips_collected(self, monkeypatch):
        self._patch_doh(monkeypatch, {
            "https://dns.google": (200, _doh_answer("149.154.167.220")),
            "https://cloudflare-dns.com": (200, _doh_answer("149.154.167.221")),
        }, system_dns_ips=["149.154.166.110"])

        ips = await tnet.discover_fallback_ips()
        assert "149.154.167.220" in ips
        assert "149.154.167.221" in ips

    @pytest.mark.asyncio
    async def test_system_dns_ip_excluded(self, monkeypatch):
        """The IP from system DNS is the one that doesn't work — exclude it."""
        self._patch_doh(monkeypatch, {
            "https://dns.google": (200, _doh_answer("149.154.166.110", "149.154.167.220")),
            "https://cloudflare-dns.com": (200, _doh_answer("149.154.166.110")),
        }, system_dns_ips=["149.154.166.110"])

        ips = await tnet.discover_fallback_ips()
        assert ips == ["149.154.167.220"]

    @pytest.mark.asyncio
    async def test_doh_results_deduplicated(self, monkeypatch):
        self._patch_doh(monkeypatch, {
            "https://dns.google": (200, _doh_answer("149.154.167.220")),
            "https://cloudflare-dns.com": (200, _doh_answer("149.154.167.220")),
        }, system_dns_ips=["149.154.166.110"])

        ips = await tnet.discover_fallback_ips()
        assert ips == ["149.154.167.220"]

    @pytest.mark.asyncio
    async def test_doh_timeout_falls_back_to_seed(self, monkeypatch):
        self._patch_doh(monkeypatch, {
            "https://dns.google": httpx.TimeoutException("timeout"),
            "https://cloudflare-dns.com": httpx.TimeoutException("timeout"),
        }, system_dns_ips=["149.154.166.110"])

        ips = await tnet.discover_fallback_ips()
        assert ips == tnet._SEED_FALLBACK_IPS

    @pytest.mark.asyncio
    async def test_doh_connect_error_falls_back_to_seed(self, monkeypatch):
        self._patch_doh(monkeypatch, {
            "https://dns.google": httpx.ConnectError("refused"),
            "https://cloudflare-dns.com": httpx.ConnectError("refused"),
        }, system_dns_ips=["149.154.166.110"])

        ips = await tnet.discover_fallback_ips()
        assert ips == tnet._SEED_FALLBACK_IPS

    @pytest.mark.asyncio
    async def test_doh_malformed_json_falls_back_to_seed(self, monkeypatch):
        self._patch_doh(monkeypatch, {
            "https://dns.google": (200, {"Status": 0}),  # no Answer key
            "https://cloudflare-dns.com": (200, {"garbage": True}),
        }, system_dns_ips=["149.154.166.110"])

        ips = await tnet.discover_fallback_ips()
        assert ips == tnet._SEED_FALLBACK_IPS

    @pytest.mark.asyncio
    async def test_one_provider_fails_other_succeeds(self, monkeypatch):
        self._patch_doh(monkeypatch, {
            "https://dns.google": httpx.TimeoutException("timeout"),
            "https://cloudflare-dns.com": (200, _doh_answer("149.154.167.220")),
        }, system_dns_ips=["149.154.166.110"])

        ips = await tnet.discover_fallback_ips()
        assert ips == ["149.154.167.220"]

    @pytest.mark.asyncio
    async def test_system_dns_failure_keeps_all_doh_ips(self, monkeypatch):
        """If system DNS fails, nothing gets excluded — all DoH IPs kept."""
        self._patch_doh(monkeypatch, {
            "https://dns.google": (200, _doh_answer("149.154.166.110", "149.154.167.220")),
            "https://cloudflare-dns.com": (200, _doh_answer()),
        }, system_dns_ips=None)  # triggers OSError

        ips = await tnet.discover_fallback_ips()
        assert "149.154.166.110" in ips
        assert "149.154.167.220" in ips

    @pytest.mark.asyncio
    async def test_all_doh_ips_same_as_system_dns_uses_seed(self, monkeypatch):
        """DoH returns only the same blocked IP — seed list is the fallback."""
        self._patch_doh(monkeypatch, {
            "https://dns.google": (200, _doh_answer("149.154.166.110")),
            "https://cloudflare-dns.com": (200, _doh_answer("149.154.166.110")),
        }, system_dns_ips=["149.154.166.110"])

        ips = await tnet.discover_fallback_ips()
        assert ips == tnet._SEED_FALLBACK_IPS

    @pytest.mark.asyncio
    async def test_cloudflare_gets_accept_header(self, monkeypatch):
        client = self._patch_doh(monkeypatch, {
            "https://dns.google": (200, _doh_answer("149.154.167.220")),
            "https://cloudflare-dns.com": (200, _doh_answer("149.154.167.221")),
        }, system_dns_ips=["149.154.166.110"])

        await tnet.discover_fallback_ips()

        cf_reqs = [r for r in client.requests_made if "cloudflare" in r["url"]]
        assert cf_reqs
        assert cf_reqs[0]["headers"]["Accept"] == "application/dns-json"

    @pytest.mark.asyncio
    async def test_non_a_records_ignored(self, monkeypatch):
        """AAAA records (type 28) and CNAME (type 5) should be skipped."""
        answer = {
            "Answer": [
                {"type": 5, "data": "telegram.org"},  # CNAME
                {"type": 28, "data": "2001:67c:4e8:f004::9"},  # AAAA
                {"type": 1, "data": "149.154.167.220"},  # A ✓
            ]
        }
        self._patch_doh(monkeypatch, {
            "https://dns.google": (200, answer),
            "https://cloudflare-dns.com": (200, _doh_answer()),
        }, system_dns_ips=["149.154.166.110"])

        ips = await tnet.discover_fallback_ips()
        assert ips == ["149.154.167.220"]

    @pytest.mark.asyncio
    async def test_invalid_ip_in_doh_response_skipped(self, monkeypatch):
        answer = {"Answer": [
            {"type": 1, "data": "not-an-ip"},
            {"type": 1, "data": "149.154.167.220"},
        ]}
        self._patch_doh(monkeypatch, {
            "https://dns.google": (200, answer),
            "https://cloudflare-dns.com": (200, _doh_answer()),
        }, system_dns_ips=["149.154.166.110"])

        ips = await tnet.discover_fallback_ips()
        assert ips == ["149.154.167.220"]


# ═══════════════════════════════════════════════════════════════════════════
# Phase 0.4 — seed IPs, retry/backoff, and failure-cause logging
# ═══════════════════════════════════════════════════════════════════════════

class TestSeedFallbackIps:
    def test_seed_default_is_multiple_in_range_ips(self):
        seed = tnet._SEED_FALLBACK_IPS
        assert len(seed) >= 2, "seed should provide multiple fallback endpoints"
        import ipaddress
        net = ipaddress.ip_network("149.154.160.0/20")
        for ip in seed:
            assert ipaddress.ip_address(ip) in net, f"{ip} not in Telegram DC block"
        # All entries survive validation/normalization
        assert tnet._normalize_fallback_ips(seed) == seed

    def test_get_seed_returns_multi_ip_default_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_FALLBACK_IPS", raising=False)
        assert tnet.get_seed_fallback_ips() == list(tnet._SEED_FALLBACK_IPS)

    def test_env_override_replaces_seed(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_FALLBACK_IPS", "149.154.171.5, 149.154.175.50")
        assert tnet.get_seed_fallback_ips() == ["149.154.171.5", "149.154.175.50"]

    def test_env_override_with_only_invalid_falls_back_to_seed(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_FALLBACK_IPS", "bad, 10.0.0.1, ::1")
        assert tnet.get_seed_fallback_ips() == list(tnet._SEED_FALLBACK_IPS)


class TestDescribeExc:
    def test_includes_type_when_message_empty(self):
        # httpx.ConnectError with no message → empty str(), the original bug
        exc = httpx.ConnectError("")
        assert str(exc) == ""
        desc = tnet._describe_exc(exc)
        assert "ConnectError" in desc and desc.strip() != ""

    def test_includes_message_when_present(self):
        desc = tnet._describe_exc(httpx.ConnectError("Network is unreachable"))
        assert "ConnectError" in desc
        assert "Network is unreachable" in desc

    def test_surfaces_underlying_cause(self):
        try:
            try:
                raise OSError("Network is unreachable")
            except OSError as os_err:
                raise httpx.ConnectError("") from os_err
        except httpx.ConnectError as exc:
            desc = tnet._describe_exc(exc)
        assert "Network is unreachable" in desc


class TestFailureLoggingIncludesCause:
    @pytest.mark.asyncio
    async def test_fallback_failure_log_is_not_empty(self, monkeypatch, caplog):
        calls = []
        # ConnectError with empty message reproduces the empty-reason bug
        empty_err = httpx.ConnectError("")
        behavior = {"api.telegram.org": "timeout", "149.154.167.220": empty_err}
        monkeypatch.setattr(
            tnet.httpx, "AsyncHTTPTransport", _fake_transport_factory(calls, behavior)
        )

        transport = tnet.TelegramFallbackTransport(["149.154.167.220"])
        with caplog.at_level("WARNING"):
            with pytest.raises(httpx.ConnectError):
                await transport.handle_async_request(_telegram_request())

        # The log line for the failed fallback IP must include a cause, not
        # end with a bare colon.
        fallback_lines = [
            r.getMessage() for r in caplog.records
            if "Fallback IP 149.154.167.220 failed" in r.getMessage()
        ]
        assert fallback_lines, "expected a fallback-failure log line"
        line = fallback_lines[0]
        assert not line.rstrip().endswith("failed:"), "log still has empty reason"
        assert "ConnectError" in line


class TestRetryBackoff:
    @pytest.mark.asyncio
    async def test_retries_each_ip_before_giving_up(self, monkeypatch):
        monkeypatch.setattr(tnet, "_FALLBACK_CONNECT_ATTEMPTS", 3)
        monkeypatch.setattr(tnet, "_FALLBACK_RETRY_BACKOFF", 0)
        sleeps = []

        async def fake_sleep(secs):
            sleeps.append(secs)

        monkeypatch.setattr(tnet.asyncio, "sleep", fake_sleep)

        calls = []
        behavior = {"api.telegram.org": "timeout", "149.154.167.220": "timeout"}
        monkeypatch.setattr(
            tnet.httpx, "AsyncHTTPTransport", _fake_transport_factory(calls, behavior)
        )

        transport = tnet.TelegramFallbackTransport(["149.154.167.220"])
        with pytest.raises(httpx.ConnectTimeout):
            await transport.handle_async_request(_telegram_request())

        # primary tried 3x + fallback tried 3x
        assert [c["url_host"] for c in calls].count("api.telegram.org") == 3
        assert [c["url_host"] for c in calls].count("149.154.167.220") == 3
        # backoff slept between retries (2 per IP * 2 IPs = 4)
        assert len(sleeps) == 4

    @pytest.mark.asyncio
    async def test_retry_recovers_within_same_ip(self, monkeypatch):
        monkeypatch.setattr(tnet, "_FALLBACK_CONNECT_ATTEMPTS", 3)
        monkeypatch.setattr(tnet, "_FALLBACK_RETRY_BACKOFF", 0)

        calls = []
        # A transport whose .220 path fails once then succeeds
        state = {"fail_count": 1}

        class FlakyTransport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                calls.append({"url_host": request.url.host})
                if request.url.host == "api.telegram.org":
                    raise httpx.ConnectTimeout("primary down")
                if state["fail_count"] > 0:
                    state["fail_count"] -= 1
                    raise httpx.ConnectError("transient")
                return httpx.Response(200, request=request, text="ok")

            async def aclose(self):
                pass

        monkeypatch.setattr(tnet.httpx, "AsyncHTTPTransport", lambda **kw: FlakyTransport())

        transport = tnet.TelegramFallbackTransport(["149.154.167.220"])
        resp = await transport.handle_async_request(_telegram_request())
        assert resp.status_code == 200
        assert transport._sticky_ip == "149.154.167.220"
