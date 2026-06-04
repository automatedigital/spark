"""Persistent, streamable server-side browser sessions for the WebUI preview pane.

A normal browser tab can't embed external sites (``X-Frame-Options``/CSP), so the
WebUI streams a real server-side Chromium instead: the pane renders screenshot
frames and forwards pointer/keyboard input back here. Each workspace gets its own
persistent profile under ``SPARK_HOME/browser/<slug>`` so logins survive restarts.

Playwright's sync API is thread-affine, so every session owns a dedicated worker
thread that holds the browser context and serves commands off a queue. Playwright
is imported lazily — callers get a clear error when it isn't installed.
"""

from __future__ import annotations

import queue
import re
import threading
from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path
from typing import Any

from spark_cli.config import get_spark_home

_VIEWPORT = (1280, 800)
_COMMAND_TIMEOUT = 20.0

_sessions: dict[str, StreamedBrowserSession] = {}
_sessions_lock = threading.Lock()


class BrowserUnavailable(RuntimeError):
    """Raised when Playwright/Chromium is not available."""


def _safe_slug(slug: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "-", slug)


def browser_profile_dir(slug: str, *, persistent: bool = True) -> Path:
    """Per-workspace Chromium profile dir. Ephemeral sessions get a throwaway sub-dir."""
    root = get_spark_home() / "browser" / _safe_slug(slug)
    return root / ("persistent" if persistent else "ephemeral")


def _harden_dir_permissions(path: Path) -> None:
    """Restrict the profile dir to the owner (0700).

    At-rest encryption of the cookie jar itself is provided by the platform:
    on macOS Chromium encrypts cookies with a key held in the login Keychain
    ("Chrome Safe Storage"). We additionally lock the directory down so other
    local users can't read the profile. See PREVIEW_BROWSER_SECURITY.md.
    """
    import os

    try:
        os.chmod(path, 0o700)
        parent = path.parent
        if parent.name == _safe_slug(parent.name) or parent.name:
            os.chmod(parent, 0o700)
    except OSError:
        pass


class StreamedBrowserSession:
    """Owns a persistent Chromium context on a dedicated thread."""

    def __init__(
        self,
        slug: str,
        *,
        persistent: bool = True,
        viewport: tuple[int, int] = _VIEWPORT,
        on_log: Callable[[str, str], None] | None = None,
    ):
        self.slug = slug
        self.persistent = persistent
        self.viewport = viewport
        self.on_log = on_log
        self.data_dir = browser_profile_dir(slug, persistent=persistent)
        self.current_url: str = "about:blank"
        self.title: str = ""
        self._cmd_q: queue.Queue[tuple[Callable[[Any], Any], Future] | None] = queue.Queue()
        self._ready = threading.Event()
        self._start_error: Exception | None = None
        self._closed = False
        self._thread = threading.Thread(target=self._run, name=f"preview-browser-{slug}", daemon=True)
        self._thread.start()

    # ── thread body ────────────────────────────────────────────────────────
    def _run(self) -> None:
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except ImportError:
            self._start_error = BrowserUnavailable(
                "Playwright is not installed — run `pip install playwright && playwright install chromium`"
            )
            self._ready.set()
            return
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            _harden_dir_permissions(self.data_dir)
            with sync_playwright() as pw:
                context = pw.chromium.launch_persistent_context(
                    str(self.data_dir),
                    headless=True,
                    viewport={"width": self.viewport[0], "height": self.viewport[1]},
                )
                page = context.pages[0] if context.pages else context.new_page()
                self._page = page
                self._wire_logging(page)
                self._ready.set()
                while True:
                    item = self._cmd_q.get()
                    if item is None:
                        break
                    fn, fut = item
                    if fut.set_running_or_notify_cancel():
                        try:
                            fut.set_result(fn(page))
                        except Exception as exc:  # noqa: BLE001 — surface to caller
                            fut.set_exception(exc)
                context.close()
        except Exception as exc:  # noqa: BLE001
            self._start_error = exc
            self._ready.set()

    # ── logging ────────────────────────────────────────────────────────────
    def _log(self, text: str, stream: str) -> None:
        if self.on_log is not None:
            try:
                self.on_log(text, stream)
            except Exception:
                pass

    def _wire_logging(self, page: Any) -> None:
        """Forward the page's console + network activity to the log callback."""
        if self.on_log is None:
            return
        page.on("console", lambda msg: self._log(f"{msg.type}: {msg.text}", "console"))
        page.on("pageerror", lambda err: self._log(str(err), "error"))
        page.on("response", lambda resp: self._log(f"{resp.status} {resp.url}", "network"))

    # ── command plumbing ───────────────────────────────────────────────────
    def _submit(self, fn: Callable[[Any], Any]) -> Any:
        self._ready.wait(timeout=_COMMAND_TIMEOUT)
        if self._start_error is not None:
            raise self._start_error
        if self._closed:
            raise BrowserUnavailable("Browser session is closed")
        fut: Future = Future()
        self._cmd_q.put((fn, fut))
        return fut.result(timeout=_COMMAND_TIMEOUT)

    # ── public operations ──────────────────────────────────────────────────
    def navigate(self, url: str) -> dict[str, Any]:
        def _go(page: Any) -> dict[str, Any]:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            self.current_url = page.url
            self.title = page.title()
            return {"url": self.current_url, "title": self.title}

        return self._submit(_go)

    def screenshot(self) -> bytes:
        return self._submit(lambda page: page.screenshot(type="png"))

    def click(self, x: float, y: float) -> None:
        self._submit(lambda page: page.mouse.click(x, y))

    def scroll(self, dx: float, dy: float) -> None:
        self._submit(lambda page: page.mouse.wheel(dx, dy))

    def type_text(self, text: str) -> None:
        self._submit(lambda page: page.keyboard.type(text))

    def press_key(self, key: str) -> None:
        self._submit(lambda page: page.keyboard.press(key))

    def go_back(self) -> dict[str, Any]:
        def _back(page: Any) -> dict[str, Any]:
            page.go_back(wait_until="domcontentloaded", timeout=15000)
            self.current_url = page.url
            self.title = page.title()
            return {"url": self.current_url, "title": self.title}

        return self._submit(_back)

    def cookies(self) -> list[dict[str, str]]:
        """List cookies (name + domain only) from the persistent context."""

        def _cookies(page: Any) -> list[dict[str, str]]:
            return [
                {"name": c.get("name", ""), "domain": c.get("domain", "")}
                for c in page.context.cookies()
            ]

        return self._submit(_cookies)

    def go_forward(self) -> dict[str, Any]:
        def _fwd(page: Any) -> dict[str, Any]:
            page.go_forward(wait_until="domcontentloaded", timeout=15000)
            self.current_url = page.url
            self.title = page.title()
            return {"url": self.current_url, "title": self.title}

        return self._submit(_fwd)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._cmd_q.put(None)


def get_streamed_session(
    slug: str,
    *,
    persistent: bool = True,
    on_log: Callable[[str, str], None] | None = None,
) -> StreamedBrowserSession:
    """Return (creating if needed) the streamed browser session for a workspace."""
    with _sessions_lock:
        session = _sessions.get(slug)
        if session is not None and not session._closed and session.persistent == persistent:
            if on_log is not None:
                session.on_log = on_log
            return session
        if session is not None:
            session.close()
        session = StreamedBrowserSession(slug, persistent=persistent, on_log=on_log)
        _sessions[slug] = session
        return session


def close_streamed_session(slug: str) -> bool:
    with _sessions_lock:
        session = _sessions.pop(slug, None)
    if session is None:
        return False
    session.close()
    return True


def clear_browsing_data(slug: str) -> bool:
    """Close the session and delete the workspace's persistent + ephemeral profiles."""
    import shutil
    import time as _time

    close_streamed_session(slug)
    _time.sleep(0.2)  # let the browser process release file handles
    removed = False
    for persistent in (True, False):
        path = browser_profile_dir(slug, persistent=persistent)
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
            removed = True
    return removed


def viewport_size() -> tuple[int, int]:
    return _VIEWPORT
