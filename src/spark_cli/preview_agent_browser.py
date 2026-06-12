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

STATUS (v1): the frame source uses ``agent-browser screenshot`` (polled, correct
parity with the current Playwright preview UX). A low-latency CDP screencast path
is a follow-up (Item 2b). Coordinate input is forwarded through the CLI's
``mouse``/``keyboard`` primitives, which dispatch real CDP input events against
the shared session.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any

from spark_cli.config import get_spark_home

_VIEWPORT = (1280, 800)
_COMMAND_TIMEOUT = 20.0
_MAX_OUTPUT = 12000


class AgentBrowserUnavailable(RuntimeError):
    """Raised when the agent-browser CLI/runtime is not available."""


def _safe_slug(slug: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "-", slug)


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

    def click(self, x: float, y: float) -> None:
        """Coordinate click via real CDP input (move → down → up)."""
        ix, iy = int(x), int(y)
        self._run(["mouse", "move", str(ix), str(iy)])
        self._run(["mouse", "down"])
        self._run(["mouse", "up"])
        self._refresh_state()

    def scroll(self, dx: float, dy: float) -> None:
        # agent-browser's `mouse wheel <dy> [dx]` dispatches a CDP wheel event,
        # matching Playwright's mouse.wheel(dx, dy) semantics.
        self._run(["mouse", "wheel", str(int(dy)), str(int(dx))])

    def type_text(self, text: str) -> None:
        self._run(["keyboard", "type", text])

    def press_key(self, key: str) -> None:
        self._run(["press", key])

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
