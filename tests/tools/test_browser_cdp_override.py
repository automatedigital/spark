from unittest.mock import Mock, patch

import pytest

HOST = "example-host"
PORT = 9223
WS_URL = f"ws://{HOST}:{PORT}/devtools/browser/abc123"
HTTP_URL = f"http://{HOST}:{PORT}"
VERSION_URL = f"{HTTP_URL}/json/version"


class TestResolveCdpOverride:
    @pytest.fixture(autouse=True)
    def _safe_cdp_defaults(self, monkeypatch):
        import tools.browser_tool as browser_tool

        monkeypatch.setattr(browser_tool, "_allow_private_urls", lambda: False)
        monkeypatch.setattr(browser_tool, "_is_safe_url", lambda url: True)

    def test_keeps_full_devtools_websocket_url(self):
        from tools.browser_tool import _resolve_cdp_override

        assert _resolve_cdp_override(WS_URL) == WS_URL

    def test_allows_loopback_devtools_websocket_when_url_safety_blocks(self, monkeypatch):
        import tools.browser_tool as browser_tool
        from tools.browser_tool import _resolve_cdp_override

        monkeypatch.setattr(browser_tool, "_is_safe_url", lambda url: False)

        url = "ws://127.0.0.1:9222/devtools/browser/local"
        assert _resolve_cdp_override(url) == url

    def test_blocks_private_devtools_websocket_by_default(self, monkeypatch):
        import tools.browser_tool as browser_tool
        from tools.browser_tool import _resolve_cdp_override

        monkeypatch.setattr(browser_tool, "_is_safe_url", lambda url: False)

        assert _resolve_cdp_override("ws://192.168.1.50:9222/devtools/browser/abc") == ""

    def test_resolves_http_discovery_endpoint_to_websocket(self):
        from tools.browser_tool import _resolve_cdp_override

        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"webSocketDebuggerUrl": WS_URL}

        with patch("tools.browser_tool.requests.get", return_value=response) as mock_get:
            resolved = _resolve_cdp_override(HTTP_URL)

        assert resolved == WS_URL
        mock_get.assert_called_once_with(VERSION_URL, timeout=10)

    def test_resolves_bare_ws_hostport_to_discovery_websocket(self):
        from tools.browser_tool import _resolve_cdp_override

        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"webSocketDebuggerUrl": WS_URL}

        with patch("tools.browser_tool.requests.get", return_value=response) as mock_get:
            resolved = _resolve_cdp_override(f"ws://{HOST}:{PORT}")

        assert resolved == WS_URL
        mock_get.assert_called_once_with(VERSION_URL, timeout=10)

    def test_blocks_private_http_discovery_endpoint_before_request(self, monkeypatch):
        import tools.browser_tool as browser_tool
        from tools.browser_tool import _resolve_cdp_override

        monkeypatch.setattr(browser_tool, "_is_safe_url", lambda url: False)

        with patch("tools.browser_tool.requests.get") as mock_get:
            assert _resolve_cdp_override("http://10.0.0.5:9222") == ""

        mock_get.assert_not_called()

    def test_blocks_private_websocket_returned_by_discovery(self, monkeypatch):
        import tools.browser_tool as browser_tool
        from tools.browser_tool import _resolve_cdp_override

        monkeypatch.setattr(
            browser_tool,
            "_is_safe_url",
            lambda url: "10.0.0.5" not in url,
        )

        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "webSocketDebuggerUrl": "ws://10.0.0.5:9222/devtools/browser/abc",
        }

        with patch("tools.browser_tool.requests.get", return_value=response):
            assert _resolve_cdp_override(HTTP_URL) == ""

    def test_falls_back_to_raw_url_when_discovery_fails(self):
        from tools.browser_tool import _resolve_cdp_override

        with patch("tools.browser_tool.requests.get", side_effect=RuntimeError("boom")):
            assert _resolve_cdp_override(HTTP_URL) == HTTP_URL

    def test_normalizes_provider_returned_http_cdp_url_when_creating_session(self, monkeypatch):
        import tools.browser_tool as browser_tool

        provider = Mock()
        provider.create_session.return_value = {
            "session_name": "cloud-session",
            "bb_session_id": "bu_123",
            "cdp_url": "https://cdp.browser-use.example/session",
            "features": {"browser_use": True},
        }

        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"webSocketDebuggerUrl": WS_URL}

        monkeypatch.setattr(browser_tool, "_active_sessions", {})
        monkeypatch.setattr(browser_tool, "_session_last_activity", {})
        monkeypatch.setattr(browser_tool, "_start_browser_cleanup_thread", lambda: None)
        monkeypatch.setattr(browser_tool, "_update_session_activity", lambda task_id: None)
        monkeypatch.setattr(browser_tool, "_get_cdp_override", lambda: "")
        monkeypatch.setattr(browser_tool, "_get_cloud_provider", lambda: provider)

        with patch("tools.browser_tool.requests.get", return_value=response) as mock_get:
            session_info = browser_tool._get_session_info("task-browser-use")

        assert session_info["cdp_url"] == WS_URL
        provider.create_session.assert_called_once_with("task-browser-use")
        mock_get.assert_called_once_with(
            "https://cdp.browser-use.example/session/json/version",
            timeout=10,
        )
