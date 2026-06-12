"""Tests for the WebUI preview browser backend selector, AgentBrowserSession
surface, and the display.preview_browser_backend config migration (Item 2)."""

import json
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
    assert ["mouse", "down", "left"] in calls
    assert ["mouse", "up", "left"] in calls


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


# ── Item 2b: input parity (right-click, scroll, upload, clipboard, combos) ────


def _record_calls(sess):
    calls: list = []
    return calls, patch.object(
        sess, "_run", side_effect=lambda args, **k: calls.append(args) or {}
    )


def test_right_click_dispatches_right_button(tmp_path):
    sess = _make_session(tmp_path)
    calls, ctx = _record_calls(sess)
    with ctx:
        sess.right_click(10, 20)
    assert ["mouse", "down", "right"] in calls
    assert ["mouse", "up", "right"] in calls


def test_click_unknown_button_falls_back_to_left(tmp_path):
    sess = _make_session(tmp_path)
    calls, ctx = _record_calls(sess)
    with ctx:
        sess.click(1, 2, button="bogus")
    assert ["mouse", "down", "left"] in calls


def test_scroll_forwards_wheel_delta(tmp_path):
    sess = _make_session(tmp_path)
    calls, ctx = _record_calls(sess)
    with ctx:
        sess.scroll(5, 40)
    # agent-browser wheel takes <dy> [dx]; momentum is reproduced client-side.
    assert ["mouse", "wheel", "40", "5"] in calls


def test_press_key_forwards_modifier_combo(tmp_path):
    sess = _make_session(tmp_path)
    calls, ctx = _record_calls(sess)
    with ctx:
        sess.press_key("Control+c")
    assert ["press", "Control+c"] in calls


def test_upload_files_targets_file_input(tmp_path):
    sess = _make_session(tmp_path)
    calls, ctx = _record_calls(sess)
    with ctx:
        sess.upload_files(["/tmp/a.png", "", "/tmp/b.png"])
    assert ["upload", "input[type=file]", "/tmp/a.png", "/tmp/b.png"] in calls


def test_upload_files_noop_when_empty(tmp_path):
    sess = _make_session(tmp_path)
    calls, ctx = _record_calls(sess)
    with ctx:
        sess.upload_files([])
    assert calls == []


def test_clipboard_write_uses_navigator_clipboard(tmp_path):
    sess = _make_session(tmp_path)
    calls, ctx = _record_calls(sess)
    with ctx:
        sess.clipboard_write('he said "hi"')
    # Must be a single eval with a JSON-escaped argument (no clipboard verb).
    eval_calls = [c for c in calls if c and c[0] == "eval"]
    assert len(eval_calls) == 1
    assert 'navigator.clipboard.writeText(' in eval_calls[0][1]
    assert '\\"hi\\"' in eval_calls[0][1]


def test_clipboard_read_returns_result(tmp_path):
    sess = _make_session(tmp_path)
    with patch.object(sess, "_run", return_value={"result": "pasted"}):
        assert sess.clipboard_read() == "pasted"


def test_clipboard_read_empty_on_failure(tmp_path):
    import spark_cli.preview_agent_browser as pab

    sess = _make_session(tmp_path)
    with patch.object(
        sess, "_run", side_effect=pab.AgentBrowserUnavailable("denied")
    ):
        assert sess.clipboard_read() == ""


def test_clipboard_copy_paste_use_shortcuts(tmp_path):
    sess = _make_session(tmp_path)
    calls, ctx = _record_calls(sess)
    with ctx:
        sess.clipboard_copy()
        sess.clipboard_paste()
    assert ["press", "Control+c"] in calls
    assert ["press", "Control+v"] in calls


def test_input_parity_surface_present(tmp_path):
    sess = _make_session(tmp_path)
    for name in (
        "right_click", "upload_files", "clipboard_read", "clipboard_write",
        "clipboard_copy", "clipboard_paste", "cdp_url", "start_screencast",
    ):
        assert callable(getattr(sess, name)), name


# ── Item 2b: CDP screencast (push frames) ────────────────────────────────────


def test_cdp_port_is_deterministic_and_in_range(tmp_path):
    import spark_cli.preview_agent_browser as pab

    p1 = pab._cdp_port_for("spark-preview-ws-1")
    p2 = pab._cdp_port_for("spark-preview-ws-1")
    p3 = pab._cdp_port_for("spark-preview-ws-2")
    assert p1 == p2  # stable across calls → same browser reused
    assert p1 != p3  # different workspaces get different ports
    assert pab._CDP_PORT_BASE <= p1 < pab._CDP_PORT_BASE + pab._CDP_PORT_SPAN


def test_cdp_url_discovers_page_target(tmp_path):
    sess = _make_session(tmp_path)
    listing = json.dumps(
        [
            {"type": "background_page", "webSocketDebuggerUrl": "ws://x/bg"},
            {"type": "page", "webSocketDebuggerUrl": "ws://127.0.0.1:1/devtools/page/A"},
        ]
    ).encode()

    class _Resp:
        def read(self):
            return listing

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    with patch("urllib.request.urlopen", return_value=_Resp()):
        assert sess.cdp_url() == "ws://127.0.0.1:1/devtools/page/A"


def test_cdp_url_none_when_discovery_fails(tmp_path):
    sess = _make_session(tmp_path)
    with patch("urllib.request.urlopen", side_effect=OSError("refused")):
        assert sess.cdp_url() is None


def test_start_screencast_returns_none_without_cdp(tmp_path):
    sess = _make_session(tmp_path)
    # No CDP url available → must return None so caller polls (graceful fallback).
    with patch.object(sess, "cdp_url", return_value=None):
        assert sess.start_screencast(lambda _f: None) is None


def test_screencast_handle_unavailable_without_websockets(tmp_path):
    import builtins

    import spark_cli.preview_agent_browser as pab

    real_import = builtins.__import__

    def _no_ws(name, *args, **kwargs):
        if name == "websockets":
            raise ImportError("no websockets")
        return real_import(name, *args, **kwargs)

    handle = pab.ScreencastHandle("ws://x", lambda _f: None, (800, 600))
    with patch("builtins.__import__", side_effect=_no_ws):
        try:
            handle.start()
        except pab.ScreencastUnavailable:
            return
    raise AssertionError("expected ScreencastUnavailable when websockets missing")


def test_screencast_pump_acks_and_forwards_frames(tmp_path):
    """Drive _pump against a fake CDP websocket: it must ack each frame and
    forward the decoded JPEG bytes to the on_frame callback."""
    import asyncio
    import base64

    import spark_cli.preview_agent_browser as pab

    sent: list = []
    frame_bytes = b"\xff\xd8jpeg-bytes\xff\xd9"
    frame_b64 = base64.b64encode(frame_bytes).decode()
    incoming = [
        json.dumps(
            {
                "method": "Page.screencastFrame",
                "params": {"sessionId": 7, "data": frame_b64},
            }
        )
    ]

    class _FakeWS:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def send(self, msg):
            sent.append(json.loads(msg))

        async def recv(self):
            if incoming:
                return incoming.pop(0)
            raise asyncio.CancelledError

    received: list = []
    handle = pab.ScreencastHandle("ws://x", received.append, (800, 600))

    class _FakeWebsockets:
        @staticmethod
        def connect(*a, **k):
            return _FakeWS()

    with patch.dict("sys.modules", {"websockets": _FakeWebsockets}):
        try:
            asyncio.run(handle._pump())
        except asyncio.CancelledError:
            pass

    methods = [m.get("method") for m in sent]
    assert "Page.enable" in methods
    assert "Page.startScreencast" in methods
    assert "Page.screencastFrameAck" in methods
    assert received == [frame_bytes]
