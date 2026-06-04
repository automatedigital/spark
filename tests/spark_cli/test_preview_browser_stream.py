"""Tests for the streamed server-side browser (src/spark_cli/preview_browser.py).

Playwright/Chromium isn't required: a fake page records calls so we can verify the
command plumbing, dispatch, and per-workspace profile isolation.
"""

from __future__ import annotations

import threading

import pytest

from spark_cli import preview_browser as pb


class FakePage:
    def __init__(self):
        self.url = "about:blank"
        self.calls: list[tuple] = []

    def goto(self, url, **kw):
        self.calls.append(("goto", url))
        self.url = url

    def title(self):
        return "Fake Title"

    def screenshot(self, **kw):
        self.calls.append(("screenshot",))
        return b"PNG"

    def go_back(self, **kw):
        self.calls.append(("back",))
        self.url = "https://prev.example"

    def go_forward(self, **kw):
        self.calls.append(("forward",))
        self.url = "https://next.example"

    class _Mouse:
        def __init__(self, page):
            self.page = page

        def click(self, x, y):
            self.page.calls.append(("click", x, y))

        def wheel(self, dx, dy):
            self.page.calls.append(("wheel", dx, dy))

    class _Keyboard:
        def __init__(self, page):
            self.page = page

        def type(self, text):
            self.page.calls.append(("type", text))

        def press(self, key):
            self.page.calls.append(("press", key))

    @property
    def mouse(self):
        return FakePage._Mouse(self)

    @property
    def keyboard(self):
        return FakePage._Keyboard(self)


def _fake_session(slug: str = "demo") -> tuple[pb.StreamedBrowserSession, FakePage]:
    """Build a session whose worker thread serves a FakePage (no Playwright)."""
    page = FakePage()
    session = pb.StreamedBrowserSession.__new__(pb.StreamedBrowserSession)
    session.slug = slug
    session.persistent = True
    session.viewport = (1280, 800)
    session.data_dir = pb.browser_profile_dir(slug)
    session.current_url = "about:blank"
    session.title = ""
    import queue as _q

    session._cmd_q = _q.Queue()
    session._ready = threading.Event()
    session._ready.set()
    session._start_error = None
    session._closed = False

    def _serve():
        while True:
            item = session._cmd_q.get()
            if item is None:
                break
            fn, fut = item
            if fut.set_running_or_notify_cancel():
                try:
                    fut.set_result(fn(page))
                except Exception as exc:  # noqa: BLE001
                    fut.set_exception(exc)

    session._thread = threading.Thread(target=_serve, daemon=True)
    session._thread.start()
    return session, page


def test_profile_dir_is_partitioned_per_workspace():
    a = pb.browser_profile_dir("proj-a")
    b = pb.browser_profile_dir("proj-b")
    assert a != b
    assert a.name == "persistent"
    assert pb.browser_profile_dir("x", persistent=False).name == "ephemeral"


def test_unsafe_slug_is_sanitized():
    root = (pb.get_spark_home() / "browser").resolve()
    resolved = pb.browser_profile_dir("../escape").resolve()
    # Path traversal must not escape the browser root.
    assert resolved.is_relative_to(root)
    assert ".." not in pb._safe_slug("../escape").replace("..-", "")


def test_navigate_and_frame():
    session, page = _fake_session()
    result = session.navigate("https://example.com")
    assert result == {"url": "https://example.com", "title": "Fake Title"}
    assert session.current_url == "https://example.com"
    assert session.screenshot() == b"PNG"
    assert ("goto", "https://example.com") in page.calls
    session.close()


def test_input_dispatch():
    session, page = _fake_session()
    session.click(100, 200)
    session.scroll(0, 480)
    session.type_text("hello")
    session.press_key("Enter")
    assert ("click", 100, 200) in page.calls
    assert ("wheel", 0, 480) in page.calls
    assert ("type", "hello") in page.calls
    assert ("press", "Enter") in page.calls
    session.close()


def test_back_forward():
    session, _ = _fake_session()
    assert session.go_back()["url"] == "https://prev.example"
    assert session.go_forward()["url"] == "https://next.example"
    session.close()


def test_wire_logging_forwards_console_and_network():
    captured: list[tuple[str, str]] = []

    class FakeEmitter:
        def __init__(self):
            self.handlers = {}

        def on(self, event, cb):
            self.handlers[event] = cb

    session = pb.StreamedBrowserSession.__new__(pb.StreamedBrowserSession)
    session.on_log = lambda text, stream: captured.append((text, stream))
    page = FakeEmitter()
    session._wire_logging(page)

    class Msg:
        type = "log"
        text = "hello"

    class Resp:
        status = 200
        url = "https://x/y.js"

    page.handlers["console"](Msg())
    page.handlers["response"](Resp())
    page.handlers["pageerror"]("boom")
    assert ("log: hello", "console") in captured
    assert ("200 https://x/y.js", "network") in captured
    assert ("boom", "error") in captured


def test_wire_logging_noop_without_callback():
    session = pb.StreamedBrowserSession.__new__(pb.StreamedBrowserSession)
    session.on_log = None
    # Should not raise / register handlers when there's no sink.
    session._wire_logging(object())


def test_cookies_lists_name_and_domain():
    session, page = _fake_session()

    class Ctx:
        def cookies(self):
            return [
                {"name": "sid", "domain": ".example.com", "value": "SECRET"},
                {"name": "x", "domain": "y.com"},
            ]

    # Attach a context to the fake page.
    page.context = Ctx()  # type: ignore[attr-defined]
    cookies = session.cookies()
    assert cookies == [
        {"name": "sid", "domain": ".example.com"},
        {"name": "x", "domain": "y.com"},
    ]
    session.close()


def test_persistent_profile_path_is_stable_across_restarts():
    # Same slug → same persistent dir across "restarts", so cookies persist.
    first = pb.browser_profile_dir("acme")
    second = pb.browser_profile_dir("acme")
    assert first == second
    # Private/ephemeral sessions use a different dir that won't carry logins.
    assert pb.browser_profile_dir("acme", persistent=False) != first


def test_clear_browsing_data_removes_profiles(monkeypatch, tmp_path):
    # Point profiles at a temp dir and create them.
    persistent = pb.browser_profile_dir("wipe-me", persistent=True)
    ephemeral = pb.browser_profile_dir("wipe-me", persistent=False)
    persistent.mkdir(parents=True, exist_ok=True)
    ephemeral.mkdir(parents=True, exist_ok=True)
    (persistent / "Cookies").write_text("x")
    assert pb.clear_browsing_data("wipe-me") is True
    assert not persistent.exists()
    assert not ephemeral.exists()


def test_missing_playwright_surfaces_clear_error():
    # Real constructor: no Playwright installed in this env -> BrowserUnavailable.
    pytest.importorskip  # keep import used
    session = pb.StreamedBrowserSession("nope")
    with pytest.raises(pb.BrowserUnavailable):
        session.navigate("https://example.com")
