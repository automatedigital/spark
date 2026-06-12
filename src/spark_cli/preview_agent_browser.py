"""agent-browser-backed streamed preview session (Item 2 scaffold).

This is the agent-browser counterpart to ``preview_browser.StreamedBrowserSession``.
It deliberately mirrors that class's public surface (``navigate``, ``screenshot``,
``click``, ``scroll``, ``type_text``, ``press_key``, ``go_back``, ``go_forward``,
``cookies``, ``close``) so the workspace routes can switch backends without
touching their endpoint logic.

Per the Item 2 spike decision (see PLAN.md), the preview pane and the agent share
ONE named agent-browser session per workspace (``spark-preview-<slug>``). Mutating
commands go through the ``agent-browser`` CLI against that session; the agent's
browser tools target the same session name, so what the agent does shows up live in
the pane and vice-versa.

STATUS: scaffold. The frame source here uses ``agent-browser screenshot`` (v1,
correct but polled). The low-latency CDP screencast path is item 2b. This module is
NOT yet wired into ``workspace_routes.py`` — the Playwright ``StreamedBrowserSession``
remains the active backend until parity (streaming + input + cookies) is confirmed.
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
        self.session = session_name(slug)
        self.current_url: str = "about:blank"
        self.title: str = ""
        self._lock = threading.Lock()
        self._closed = False
        if _agent_browser_bin() is None:
            raise AgentBrowserUnavailable(
                "agent-browser is not installed — run `spark doctor` or "
                "`python -m spark_cli.browser_runtime install`"
            )

    # ── CLI plumbing ────────────────────────────────────────────────────────
    def _run(self, args: list[str], *, timeout: float = _COMMAND_TIMEOUT) -> dict[str, Any]:
        binary = _agent_browser_bin()
        if binary is None or self._closed:
            raise AgentBrowserUnavailable("agent-browser session is unavailable")
        command = [
            binary,
            "--session",
            self.session,
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
        if proc.returncode != 0:
            detail = parsed.get("error") if isinstance(parsed, dict) else (proc.stderr or out)
            raise AgentBrowserUnavailable(detail or f"agent-browser exited {proc.returncode}")
        return parsed if isinstance(parsed, dict) else {"data": parsed}

    # ── public operations (mirror StreamedBrowserSession) ───────────────────
    def navigate(self, url: str) -> dict[str, Any]:
        self._run(["open", url])
        self.current_url = self._get("url") or url
        self.title = self._get("title") or ""
        return {"url": self.current_url, "title": self.title}

    def _get(self, what: str) -> str:
        try:
            result = self._run(["get", what])
        except AgentBrowserUnavailable:
            return ""
        data = result.get("data") if isinstance(result, dict) else None
        return data if isinstance(data, str) else ""

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
        # NOTE: pane sends pixel coords; agent-browser clicks by ref/selector.
        # Coordinate-based clicking goes through CDP Input.dispatchMouseEvent —
        # wired in the implementation pass (see PLAN.md item 2). Stub for now.
        raise NotImplementedError("coordinate click pending CDP input wiring (item 2)")

    def scroll(self, dx: float, dy: float) -> None:
        direction = "down" if dy >= 0 else "up"
        self._run(["scroll", direction, str(int(abs(dy)) or 300)])

    def type_text(self, text: str) -> None:
        self._run(["keyboard", "type", text])

    def press_key(self, key: str) -> None:
        self._run(["press", key])

    def go_back(self) -> dict[str, Any]:
        self._run(["back"])
        self.current_url = self._get("url") or self.current_url
        self.title = self._get("title") or self.title
        return {"url": self.current_url, "title": self.title}

    def go_forward(self) -> dict[str, Any]:
        self._run(["forward"])
        self.current_url = self._get("url") or self.current_url
        self.title = self._get("title") or self.title
        return {"url": self.current_url, "title": self.title}

    def cookies(self) -> list[dict[str, str]]:
        # agent-browser persists cookies via session state; surfacing name+domain
        # for the pane's cookie view is wired in the implementation pass.
        return []

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._run(["close"])
        except AgentBrowserUnavailable:
            pass
