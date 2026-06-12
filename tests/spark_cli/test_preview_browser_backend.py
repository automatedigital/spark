"""Tests for the WebUI preview browser backend selector, AgentBrowserSession
surface, and the display.preview_browser_backend config migration (Item 2)."""

import os
from unittest.mock import patch

import yaml

from spark_cli.config import DEFAULT_CONFIG, load_config, migrate_config

# ── Config flag + migration ──────────────────────────────────────────────────


def test_default_config_has_preview_browser_backend():
    assert DEFAULT_CONFIG["display"]["preview_browser_backend"] == "auto"
    assert DEFAULT_CONFIG["_config_version"] >= 23


def test_migration_adds_preview_browser_backend(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({"_config_version": 22, "display": {}}))
    with patch.dict(os.environ, {"SPARK_HOME": str(tmp_path)}):
        migrate_config(interactive=False, quiet=True)
        cfg = load_config()
    assert cfg["display"]["preview_browser_backend"] == "auto"
    assert cfg["_config_version"] >= 23


def test_migration_preserves_existing_preview_backend(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {"_config_version": 22, "display": {"preview_browser_backend": "playwright"}}
        )
    )
    with patch.dict(os.environ, {"SPARK_HOME": str(tmp_path)}):
        migrate_config(interactive=False, quiet=True)
        cfg = load_config()
    # An explicit user choice must not be clobbered by the migration.
    assert cfg["display"]["preview_browser_backend"] == "playwright"


# ── Backend selector (flag resolution + fallback) ────────────────────────────


def _resolve(flag, *, available):
    import spark_cli.workspace_routes as wr

    cfg = {"display": {"preview_browser_backend": flag}}
    with (
        patch("spark_cli.config.load_config", return_value=cfg),
        patch("spark_cli.preview_agent_browser.is_available", return_value=available),
    ):
        return wr._resolve_preview_backend()


def test_selector_auto_prefers_agent_browser_when_available():
    assert _resolve("auto", available=True) == "agent-browser"


def test_selector_auto_falls_back_to_playwright_when_unavailable():
    assert _resolve("auto", available=False) == "playwright"


def test_selector_explicit_agent_browser():
    # Explicit choice does not fall back even if availability probing says no.
    assert _resolve("agent-browser", available=False) == "agent-browser"


def test_selector_explicit_playwright():
    assert _resolve("playwright", available=True) == "playwright"


def test_selector_unknown_value_behaves_like_auto():
    assert _resolve("bogus", available=True) == "agent-browser"
    assert _resolve("bogus", available=False) == "playwright"


# ── AgentBrowserSession surface (mock the agent-browser runtime) ─────────────


def _make_session(tmp_path):
    import spark_cli.preview_agent_browser as pab

    # Pretend the binary exists; stub the CLI runner so no real browser launches.
    with (
        patch.dict(os.environ, {"SPARK_HOME": str(tmp_path)}),
        patch.object(pab, "_agent_browser_bin", return_value="/fake/agent-browser"),
        patch.object(pab.AgentBrowserSession, "_run", return_value={}),
    ):
        return pab.AgentBrowserSession("ws-1")


def test_session_unavailable_raises(tmp_path):
    import spark_cli.preview_agent_browser as pab

    with (
        patch.dict(os.environ, {"SPARK_HOME": str(tmp_path)}),
        patch.object(pab, "_agent_browser_bin", return_value=None),
    ):
        try:
            pab.AgentBrowserSession("ws-1")
        except pab.AgentBrowserUnavailable:
            return
        raise AssertionError("expected AgentBrowserUnavailable")


def test_session_name_and_profile_layout(tmp_path):
    import spark_cli.preview_agent_browser as pab

    with patch.dict(os.environ, {"SPARK_HOME": str(tmp_path)}):
        assert pab.session_name("My Proj!") == "spark-preview-My-Proj-"
        prof = pab.browser_profile_dir("My Proj!")
        assert prof.name == "persistent"
        assert prof.parent.name == "My-Proj-"
        assert str(tmp_path) in str(prof)


def test_session_click_dispatches_cdp_mouse(tmp_path):
    sess = _make_session(tmp_path)
    calls = []
    with patch.object(sess, "_run", side_effect=lambda args, **k: calls.append(args) or {}):
        sess.click(100, 200)
    assert ["mouse", "move", "100", "200"] in calls
    assert ["mouse", "down"] in calls
    assert ["mouse", "up"] in calls


def test_session_navigate_returns_url_title(tmp_path):
    sess = _make_session(tmp_path)
    with patch.object(sess, "_run", return_value={"url": "https://ex.com", "title": "Ex"}):
        result = sess.navigate("https://ex.com")
    assert result == {"url": "https://ex.com", "title": "Ex"}


def test_session_cookies_surfaces_name_and_domain(tmp_path):
    sess = _make_session(tmp_path)
    payload = {"cookies": [{"name": "sid", "domain": ".ex.com", "value": "secret"}]}
    with patch.object(sess, "_run", return_value=payload):
        cookies = sess.cookies()
    # value must not leak — only name + domain.
    assert cookies == [{"name": "sid", "domain": ".ex.com"}]


def test_session_has_playwright_parity_surface(tmp_path):
    sess = _make_session(tmp_path)
    for name in (
        "navigate", "screenshot", "click", "scroll", "type_text",
        "press_key", "go_back", "go_forward", "cookies", "close",
    ):
        assert callable(getattr(sess, name)), name
