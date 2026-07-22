"""Regression tests for the Web UI Codex usage meter."""

from unittest.mock import MagicMock, patch

from spark_cli.web_server import _codex_usage_windows, get_codex_usage


def test_codex_usage_windows_uses_duration_not_position_for_weekly_label():
    windows = _codex_usage_windows({
        "primary_window": {
            "used_percent": 37,
            "reset_at": 123456,
            "reset_after_seconds": 900,
            "limit_window_seconds": 604800,
        },
        "secondary_window": None,
    })

    assert windows == [{
        "label": "Weekly limit",
        "used_percent": 37,
        "reset_at": 123456,
        "reset_after_seconds": 900,
        "window_seconds": 604800,
    }]


def test_codex_usage_windows_skips_missing_or_malformed_windows():
    assert _codex_usage_windows(None) == []
    assert _codex_usage_windows({"primary_window": None}) == []
    assert _codex_usage_windows({"primary_window": {"reset_at": 123456}}) == []


def test_codex_usage_windows_labels_other_durations():
    windows = _codex_usage_windows({
        "primary_window": {"used_percent": 10, "limit_window_seconds": 18000},
        "secondary_window": {"used_percent": 20, "limit_window_seconds": 86400},
    })

    assert [window["label"] for window in windows] == ["5h limit", "1d limit"]


def test_codex_usage_endpoint_does_not_require_optional_http2_runtime():
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "plan_type": "pro",
        "rate_limit": {
            "limit_reached": False,
            "primary_window": {
                "used_percent": 21,
                "limit_window_seconds": 604800,
            },
            "secondary_window": None,
        },
    }
    client = MagicMock()
    client.__enter__.return_value.get.return_value = response
    token = "header.eyJodHRwczovL2FwaS5vcGVuYWkuY29tL2F1dGgiOnt9fQ.signature"

    with (
        patch("spark_cli.web_server.load_config", return_value={
            "model": {"provider": "openai-codex", "default": "gpt-5.6-sol"},
        }),
        patch("spark_cli.auth.get_codex_auth_status", return_value={
            "logged_in": True,
            "api_key": token,
        }),
        patch("httpx.Client", return_value=client) as client_factory,
    ):
        result = get_codex_usage()

    client_factory.assert_called_once_with(timeout=10.0)
    assert result["windows"] == [{
        "label": "Weekly limit",
        "used_percent": 21,
        "reset_at": None,
        "reset_after_seconds": None,
        "window_seconds": 604800,
    }]
