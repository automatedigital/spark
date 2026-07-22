"""Regression tests for the Web UI Codex usage meter."""

from spark_cli.web_server import _codex_usage_windows


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
