"""agent-browser-backed streamed preview session (Item 2).

This is the agent-browser counterpart to ``preview_browser.StreamedBrowserSession``.
It deliberately mirrors that class's public surface (``navigate``, ``screenshot``,
``click``, ``scroll``, ``type_text``, ``press_key``, ``go_back``, ``go_forward``,
``cookies``, ``close``) so the workspace routes can switch backends without
touching their endpoint logic.

Per the Item 2 decision (see PLAN.md), the preview pane and the agent share ONE
named agent-browser session per workspace (``spark-preview-<slug>``). Mutating
commands go through the ``agent-browser`` CLI against that session; the agent's
browser tools target the same session name, so what the agent does shows up live
in the pane and vice-versa.

Persistent profiles: each workspace's session is launched with
``--profile SPARK_HOME/browser/<slug>/persistent`` so logins survive restarts —
the same on-disk layout the Playwright backend uses.

FRAME SOURCE (Item 2b — Streaming quality): the preferred path is a CDP
*screencast* (``Page.startScreencast``/``Page.screencastFrame``) opened over the
session's CDP WebSocket. Chromium pushes JPEG frames as they paint, which the
backend acks (``Page.screencastFrameAck``) and forwards to the pane over an SSE
channel — lower latency and smoother scrolling than polling. The v1 polled
``agent-browser screenshot`` source is kept as a graceful fallback whenever the
CDP screencast can't be established (no ``websockets`` lib, no CDP url, etc.).
WebRTC transport is explicitly out of scope (future work).

INPUT PARITY (Item 2b): coordinate input is forwarded through the CLI's
``mouse``/``keyboard``/``press`` primitives, which dispatch real CDP input events
against the shared session. Beyond plain clicks/typing this covers modifier key
combos, right-click (contextmenu), scroll, file-upload dialogs, and clipboard
read/write (copy/paste).
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from spark_cli.config import get_spark_home

_VIEWPORT = (1280, 800)
_COMMAND_TIMEOUT = 20.0
_MAX_OUTPUT = 12000
# JPEG quality / max frame-rate hints for the CDP screencast (Item 2b).
_SCREENCAST_QUALITY = 70
_SCREENCAST_MAX_WIDTH = 1280
_SCREENCAST_MAX_HEIGHT = 800


class AgentBrowserUnavailable(RuntimeError):
    """Raised when the agent-browser CLI/runtime is not available."""


class ScreencastUnavailable(RuntimeError):
    """Raised when a CDP screencast can't be established (→ polled fallback)."""


class ScreencastHandle:
    """Drives a CDP ``Page.startScreencast`` over a background WebSocket thread.

    Connects to the session's CDP WebSocket, enables the ``Page`` domain, starts
    a JPEG screencast, and invokes ``on_frame`` for each ``Page.screencastFrame``
    event (acking every frame so Chromium keeps pushing). All heavy deps
    (``websockets``) are imported lazily; failure surfaces as
    :class:`ScreencastUnavailable` so the caller falls back to polling.
    """

    def __init__(
        self,
        ws_url: str,
        on_frame: Callable[[bytes], None],
        viewport: tuple[int, int],
    ) -> None:
        self._ws_url = ws_url
        self._on_frame = on_frame
        self._viewport = viewport
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = threading.Event()

    def start(self) -> None:
        try:
            import websockets  # noqa: F401 — probe optional dep availability
        except ImportError as exc:  # pragma: no cover - dep guard
            raise ScreencastUnavailable(
                "CDP screencast requires the 'websockets' package; "
                "falling back to polled screenshots"
            ) from exc
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        # Give the loop a brief moment to connect; if it dies immediately the
        # caller's first frame poll will fall back gracefully.
        self._started.wait(timeout=3.0)

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)

    def _run_loop(self) -> None:
        import asyncio

        try:
            asyncio.run(self._pump())
        except Exception:  # noqa: BLE001 — background thread must not crash
            pass

    async def _pump(self) -> None:
        import asyncio

        import websockets

        next_id = 0

        def _cmd(method: str, params: dict[str, Any] | None = None) -> str:
            nonlocal next_id
            next_id += 1
            return json.dumps({"id": next_id, "method": method, "params": params or {}})

        try:
            async with websockets.connect(
                self._ws_url, max_size=None, open_timeout=3
            ) as ws:
                await ws.send(_cmd("Page.enable"))
                await ws.send(
                    _cmd(
                        "Page.startScreencast",
                        {
                            "format": "jpeg",
                            "quality": _SCREENCAST_QUALITY,
                            "maxWidth": min(self._viewport[0], _SCREENCAST_MAX_WIDTH),
                            "maxHeight": min(self._viewport[1], _SCREENCAST_MAX_HEIGHT),
                            "everyNthFrame": 1,
                        },
                    )
                )
                self._started.set()
                while not self._stop.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    except TimeoutError:
                        continue
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        continue
                    if msg.get("method") != "Page.screencastFrame":
                        continue
                    params = msg.get("params") or {}
                    session_id = params.get("sessionId")
                    data = params.get("data")
                    # Ack first so Chromium keeps the pipeline flowing.
                    if session_id is not None:
                        await ws.send(
                            _cmd("Page.screencastFrameAck", {"sessionId": session_id})
                        )
                    if isinstance(data, str) and data:
                        try:
                            frame = base64.b64decode(data)
                        except Exception:
                            continue
                        try:
                            self._on_frame(frame)
                        except Exception:  # noqa: BLE001 — consumer errors isolated
                            pass
                try:
                    await ws.send(_cmd("Page.stopScreencast"))
                except Exception:
                    pass
        finally:
            self._started.set()


def _safe_slug(slug: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "-", slug)


# Range for per-session CDP remote-debugging ports (avoids well-known ports).
_CDP_PORT_BASE = 41000
_CDP_PORT_SPAN = 2000


def _cdp_port_for(session: str) -> int:
    """Deterministic CDP port in a high range, derived from the session name.

    Stable across CLI invocations so the same browser/port is reused for a
    given workspace; collisions across workspaces are tolerated because each
    session launches at most one browser bound to its own port.
    """
    import hashlib

    digest = hashlib.sha1(session.encode("utf-8")).hexdigest()
    return _CDP_PORT_BASE + (int(digest[:8], 16) % _CDP_PORT_SPAN)


def session_name(slug: str) -> str:
    """Stable per-workspace agent-browser session name shared with the agent tools."""
    return f"spark-preview-{_safe_slug(slug)}"


def browser_profile_dir(slug: str) -> Path:
    """Per-workspace persistent profile dir, matching ``preview_browser``'s layout."""
    return get_spark_home() / "browser" / _safe_slug(slug) / "persistent"


def _agent_browser_bin() -> str | None:
    try:
        from spark_cli.browser_runtime import agent_browser_path

        return agent_browser_path()
    except Exception:  # pragma: no cover - import guard
        import shutil

        return shutil.which("agent-browser")


def is_available() -> bool:
    """True when the agent-browser CLI is resolvable (does not launch a browser)."""
    return _agent_browser_bin() is not None


class AgentBrowserSession:
    """Drives a per-workspace agent-browser session for the preview pane.

    Thread-safe: commands are serialized so concurrent pane input + agent calls
    don't interleave CLI invocations against the same session.
    """

    def __init__(
        self,
        slug: str,
        *,
        viewport: tuple[int, int] = _VIEWPORT,
    ) -> None:
        self.slug = slug
        self.viewport = viewport
        self.persistent = True  # parity with StreamedBrowserSession attribute
        self.session = session_name(slug)
        self.profile_dir = browser_profile_dir(slug)
        self.current_url: str = "about:blank"
        self.title: str = ""
        self._lock = threading.RLock()
        self._closed = False
        # Deterministic per-session CDP remote-debugging port. agent-browser
        # launches its own Chromium; we expose CDP via ``--remote-debugging-port``
        # so the screencast path (Item 2b) can connect. The port is derived from
        # the session name so repeated CLI invocations reuse the same browser.
        self._cdp_port: int = _cdp_port_for(self.session)
        if _agent_browser_bin() is None:
            raise AgentBrowserUnavailable(
                "agent-browser is not installed — run `spark doctor` or "
                "`python -m spark_cli.browser_runtime install`"
            )
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._harden_profile()
        # Ensure viewport matches the pane's render size so click coords line up.
        try:
            self._run(["set", "viewport", str(viewport[0]), str(viewport[1])])
        except AgentBrowserUnavailable:
            pass

    def _harden_profile(self) -> None:
        import os

        try:
            os.chmod(self.profile_dir, 0o700)
            os.chmod(self.profile_dir.parent, 0o700)
        except OSError:
            pass

    # ── CLI plumbing ────────────────────────────────────────────────────────
    def _run(self, args: list[str], *, timeout: float = _COMMAND_TIMEOUT) -> dict[str, Any]:
        binary = _agent_browser_bin()
        if binary is None or self._closed:
            raise AgentBrowserUnavailable("agent-browser session is unavailable")
        command = [
            binary,
            "--session",
            self.session,
            "--profile",
            str(self.profile_dir),
            # Expose CDP on a deterministic port so the screencast can connect.
            # Only honoured at browser launch; harmless on reuse.
            "--args",
            f"--remote-debugging-port={self._cdp_port}",
            "--json",
            "--max-output",
            str(_MAX_OUTPUT),
            *args,
        ]
        with self._lock:
            try:
                proc = subprocess.run(
                    command, text=True, capture_output=True, timeout=timeout, check=False
                )
            except Exception as exc:  # noqa: BLE001 — surface to caller
                raise AgentBrowserUnavailable(str(exc)) from exc
        out = (proc.stdout or "").strip()
        parsed: Any = None
        if out:
            try:
                parsed = json.loads(out)
            except Exception:
                parsed = out
        # agent-browser envelope: {"success": bool, "data": ..., "error": ...}
        if isinstance(parsed, dict) and parsed.get("success") is False:
            raise AgentBrowserUnavailable(
                str(parsed.get("error") or f"agent-browser exited {proc.returncode}")
            )
        if proc.returncode != 0 and not isinstance(parsed, dict):
            raise AgentBrowserUnavailable(
                (proc.stderr or out or f"agent-browser exited {proc.returncode}").strip()
            )
        if isinstance(parsed, dict):
            data = parsed.get("data")
            return data if isinstance(data, dict) else {"data": data}
        return {"data": parsed}

    def _get(self, what: str) -> str:
        try:
            data = self._run(["get", what])
        except AgentBrowserUnavailable:
            return ""
        value = data.get(what) if isinstance(data, dict) else None
        if value is None and isinstance(data, dict):
            value = data.get("data")
        return value if isinstance(value, str) else ""

    def _refresh_state(self) -> None:
        self.current_url = self._get("url") or self.current_url
        self.title = self._get("title") or self.title

    # ── public operations (mirror StreamedBrowserSession) ───────────────────
    def navigate(self, url: str) -> dict[str, Any]:
        data = self._run(["open", url])
        self.current_url = (data.get("url") if isinstance(data, dict) else None) or url
        self.title = (data.get("title") if isinstance(data, dict) else None) or ""
        return {"url": self.current_url, "title": self.title}

    def screenshot(self) -> bytes:
        """Capture a PNG frame from the shared session (v1 polled source)."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            path = tmp.name
        try:
            self._run(["screenshot", path])
            return Path(path).read_bytes()
        finally:
            Path(path).unlink(missing_ok=True)

    def click(
        self,
        x: float,
        y: float,
        *,
        button: str = "left",
    ) -> None:
        """Coordinate click via real CDP input (move → down → up).

        ``button`` may be ``left``/``right``/``middle``; a ``right`` click raises
        the page's contextmenu (right-click input parity).
        """
        ix, iy = int(x), int(y)
        btn = button if button in {"left", "right", "middle"} else "left"
        self._run(["mouse", "move", str(ix), str(iy)])
        self._run(["mouse", "down", btn])
        self._run(["mouse", "up", btn])
        self._refresh_state()

    def right_click(self, x: float, y: float) -> None:
        """Dispatch a right-click (contextmenu) at the given coordinates."""
        self.click(x, y, button="right")

    def scroll(self, dx: float, dy: float) -> None:
        # agent-browser's `mouse wheel <dy> [dx]` dispatches a CDP wheel event,
        # matching Playwright's mouse.wheel(dx, dy) semantics. Scroll *momentum*
        # is reproduced on the client by streaming successive wheel deltas; the
        # backend just forwards each delta faithfully.
        self._run(["mouse", "wheel", str(int(dy)), str(int(dx))])

    def type_text(self, text: str) -> None:
        self._run(["keyboard", "type", text])

    def press_key(self, key: str) -> None:
        # agent-browser's `press` accepts combos like "Control+a" / "Meta+c",
        # giving keyboard-shortcut parity with Playwright's keyboard.press.
        self._run(["press", key])

    def upload_files(self, paths: list[str]) -> None:
        """Set files on the page's active <input type=file> (upload dialog).

        Mirrors a user picking files in a native file-chooser. ``paths`` are
        absolute paths the agent-browser runtime can read.
        """
        clean = [p for p in paths if isinstance(p, str) and p]
        if not clean:
            return
        # `upload <sel> <files...>` — target the focused/last file input.
        self._run(["upload", "input[type=file]", *clean])

    def _eval(self, expression: str) -> Any:
        """Evaluate a JS expression in the page, returning the ``result`` value.

        agent-browser's ``eval`` envelope is ``{origin, result}``; we surface
        ``result``. Failures raise :class:`AgentBrowserUnavailable`.
        """
        data = self._run(["eval", expression])
        if isinstance(data, dict):
            if "result" in data:
                return data["result"]
            return data.get("data")
        return None

    def clipboard_read(self) -> str:
        """Read clipboard text (paste source).

        agent-browser has no clipboard verb, so we read through the page's
        ``navigator.clipboard`` API via ``eval``. Returns ``""`` when the page
        denies clipboard access (headless permissions, insecure origin, etc.).
        """
        try:
            value = self._eval("navigator.clipboard.readText()")
        except AgentBrowserUnavailable:
            return ""
        return value if isinstance(value, str) else ""

    def clipboard_write(self, text: str) -> None:
        """Write text into the page clipboard (so the page can paste it)."""
        payload = json.dumps(text)
        self._eval(f"navigator.clipboard.writeText({payload})")

    def clipboard_copy(self) -> None:
        """Copy the page's current selection (simulates Ctrl/Cmd+C).

        Uses ``Control+c`` (cross-platform Chromium maps it to the copy
        command); the page's own copy handlers fire as with a real shortcut.
        """
        self.press_key("Control+c")

    def clipboard_paste(self) -> None:
        """Paste clipboard contents into the page (simulates Ctrl/Cmd+V)."""
        self.press_key("Control+v")

    # ── CDP screencast (push frames) ─────────────────────────────────────────
    def cdp_url(self) -> str | None:
        """Resolve the *page* CDP WebSocket URL (None when unavailable).

        agent-browser launches Chromium with ``--remote-debugging-port`` (see
        :meth:`_run`); we query the DevTools HTTP discovery endpoint to find the
        first ``page`` target's ``webSocketDebuggerUrl`` — the target that
        ``Page.startScreencast`` must be driven against. Any failure (port not
        bound yet, no page target) returns ``None`` → polled fallback.
        """
        if self._closed:
            return None
        import urllib.request

        url = f"http://127.0.0.1:{self._cdp_port}/json/list"
        try:
            with urllib.request.urlopen(url, timeout=2.0) as resp:  # noqa: S310
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception:  # noqa: BLE001 — discovery best-effort → fallback
            return None
        if not isinstance(payload, list):
            return None
        for target in payload:
            if not isinstance(target, dict):
                continue
            if target.get("type") != "page":
                continue
            ws = target.get("webSocketDebuggerUrl")
            if isinstance(ws, str) and ws.startswith("ws"):
                return ws
        return None

    def start_screencast(self, on_frame: Callable[[bytes], None]) -> ScreencastHandle | None:
        """Start a CDP screencast, invoking ``on_frame`` with each JPEG frame.

        Returns a :class:`ScreencastHandle` (call ``.stop()`` to tear down) or
        ``None`` when a screencast can't be established — callers MUST fall back
        to the polled ``screenshot()`` source in that case.
        """
        if self._closed:
            return None
        ws_url = self.cdp_url()
        if not ws_url:
            return None
        try:
            handle = ScreencastHandle(ws_url, on_frame, self.viewport)
            handle.start()
        except ScreencastUnavailable:
            return None
        except Exception:  # noqa: BLE001 — any failure → polled fallback
            return None
        return handle

    def go_back(self) -> dict[str, Any]:
        self._run(["back"])
        self._refresh_state()
        return {"url": self.current_url, "title": self.title}

    def go_forward(self) -> dict[str, Any]:
        self._run(["forward"])
        self._refresh_state()
        return {"url": self.current_url, "title": self.title}

    def cookies(self) -> list[dict[str, str]]:
        """List cookies (name + domain only) from the shared session."""
        try:
            data = self._run(["cookies", "get"])
        except AgentBrowserUnavailable:
            return []
        raw = data.get("cookies") if isinstance(data, dict) else None
        if not isinstance(raw, list):
            return []
        return [
            {"name": str(c.get("name", "")), "domain": str(c.get("domain", ""))}
            for c in raw
            if isinstance(c, dict)
        ]

    def close(self) -> None:
        if self._closed:
            return
        self._closed = False  # allow the close command itself to run
        try:
            self._run(["close"])
        except AgentBrowserUnavailable:
            pass
        finally:
            self._closed = True


_sessions: dict[str, AgentBrowserSession] = {}
_sessions_lock = threading.Lock()


def get_agent_browser_session(slug: str) -> AgentBrowserSession:
    """Return (creating if needed) the shared agent-browser session for a workspace."""
    with _sessions_lock:
        session = _sessions.get(slug)
        if session is not None and not session._closed:
            return session
        session = AgentBrowserSession(slug)
        _sessions[slug] = session
        return session


def close_agent_browser_session(slug: str) -> bool:
    with _sessions_lock:
        session = _sessions.pop(slug, None)
    if session is None:
        return False
    session.close()
    return True


def clear_browsing_data(slug: str) -> bool:
    """Close the session and delete the workspace's persistent profile."""
    import shutil
    import time as _time

    close_agent_browser_session(slug)
    _time.sleep(0.2)
    path = browser_profile_dir(slug)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
        return True
    return False
