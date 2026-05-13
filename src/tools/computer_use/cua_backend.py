"""macOS background computer-use backend via cua-driver MCP subprocess.

Architecture:
    cua-driver subprocess (stdio MCP transport)
        ↓  asyncio bridge on daemon thread
    _AsyncBridge  (one event loop, sync↔async marshalling)
        ↓
    _CuaDriverSession  (lazy MCP session, re-entered on drop)
        ↓
    CuaDriverBackend  (stateful: tracks _active_pid, _active_window_id)
        ↓  sticky context updated by capture()
    Action methods: click, type_text, key, scroll, drag, set_value

Key design: capture() selects a window by app name and caches _active_pid +
_active_window_id.  Subsequent action calls reference that context without
re-enumerating windows on every call — fast for rapid action sequences.

Focus: focus_app() updates the window context only.  It never raises the
window or steals keyboard focus from the user.
"""

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# cua-driver binary name on PATH
_CUA_BINARY = os.environ.get("SPARK_CUA_DRIVER_BIN", "cua-driver")


def _resolve_cua_binary() -> Optional[str]:
    """Return executable path for cua-driver, or None."""
    import platform

    p = Path(_CUA_BINARY)
    if p.is_file():
        return str(p.resolve())
    which = shutil.which(_CUA_BINARY)
    if which:
        return which
    # pip/uv install into the same venv as Spark (often not on user PATH)
    venv_bin = Path(sys.executable).resolve().parent / _CUA_BINARY
    if venv_bin.is_file():
        return str(venv_bin)
    # User / Homebrew installs often land outside the active PATH (GUI apps, minimal env)
    if platform.system() == "Darwin":
        for candidate in (
            Path.home() / ".local" / "bin" / _CUA_BINARY,
            Path("/opt/homebrew/bin") / _CUA_BINARY,
            Path("/usr/local/bin") / _CUA_BINARY,
        ):
            try:
                if candidate.is_file() and os.access(candidate, os.X_OK):
                    return str(candidate.resolve())
            except OSError:
                continue
    return None


def cua_driver_resolution_hint() -> str:
    """Short diagnostic for humans when computer_use is unavailable on macOS."""
    import platform

    if platform.system() != "Darwin":
        return ""
    exe = sys.executable
    beside = Path(exe).resolve().parent / _CUA_BINARY
    lines = [
        f"  Spark Python: {exe}",
        f"  Look(ed) for `{_CUA_BINARY}` beside it: {beside}"
        f" {'(exists)' if beside.is_file() else '(missing)'}",
    ]
    w = shutil.which(_CUA_BINARY)
    if w:
        lines.append(f"  Also on PATH: {w}")
    lines.append(
        f"  Override: export SPARK_CUA_DRIVER_BIN=/path/to/{_CUA_BINARY}"
    )
    lines.append(f"  Install for this Spark: {cua_driver_install_command()}")
    return "\n".join(lines)


def cua_driver_install_command() -> str:
    """Return the exact pip command for the Python running this Spark process."""
    import shlex

    return f"{shlex.quote(sys.executable)} -m pip install cua-driver"


# Timeout in seconds for MCP tool calls
_CALL_TIMEOUT = float(os.environ.get("SPARK_CUA_TIMEOUT", "30"))


# ---------------------------------------------------------------------------
# Availability check (called as check_fn at registration time)
# ---------------------------------------------------------------------------

def is_available() -> bool:
    """Return True if cua-driver is installed and we're on macOS."""
    import platform
    if platform.system() != "Darwin":
        return False
    return _resolve_cua_binary() is not None


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CaptureResult:
    mode: str                          # "som" | "vision"
    width: int
    height: int
    png_b64: Optional[str]             # base64-encoded screenshot (may be None for som)
    elements: List[Dict]               # AX-tree element dicts from cua-driver
    app: Optional[str]
    window_title: Optional[str]


@dataclass
class ActionResult:
    success: bool
    message: str
    data: Optional[Dict] = None


# ---------------------------------------------------------------------------
# Async bridge  (one event loop on a daemon thread, sync→async marshalling)
# ---------------------------------------------------------------------------

class _AsyncBridge:
    """Daemon thread running a single asyncio event loop.

    Sync callers submit coroutines via run() and block on a Future.
    This avoids creating/destroying a loop per call, which would break
    cached async clients (httpx sessions, MCP connections) that remain
    bound to the loop they were created on.
    """

    def __init__(self):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._started = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="cua-async-bridge",
        )
        self._thread.start()
        self._started.wait(timeout=5)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._started.set()
        self._loop.run_forever()

    def run(self, coro, timeout: float = _CALL_TIMEOUT) -> Any:
        """Submit *coro* to the bridge loop and block until done."""
        if not self._loop or not self._thread or not self._thread.is_alive():
            self.start()
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def stop(self) -> None:
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)


# ---------------------------------------------------------------------------
# MCP session wrapper  (lazy start, re-entered on drop)
# ---------------------------------------------------------------------------

class _CuaDriverSession:
    """Wraps a cua-driver MCP subprocess (stdio transport).

    Lazy: the subprocess is not started until the first tool call.
    If the process dies, the next call restarts it transparently.
    """

    def __init__(self):
        self._process: Optional[subprocess.Popen] = None
        self._lock = asyncio.Lock()
        self._request_id = 0

    async def _ensure_started(self) -> None:
        if self._process and self._process.poll() is None:
            return
        logger.debug("Starting cua-driver subprocess")
        bin_path = _resolve_cua_binary()
        if not bin_path:
            raise RuntimeError("cua-driver not found")
        self._process = subprocess.Popen(
            [bin_path, "mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # MCP initialize handshake
        await self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "spark-agent", "version": "1.0"},
        })

    async def _send_request(self, method: str, params: Dict) -> Dict:
        self._request_id += 1
        req_id = self._request_id
        msg = json.dumps({
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }) + "\n"

        loop = asyncio.get_event_loop()

        # Write in executor to avoid blocking
        await loop.run_in_executor(
            None,
            lambda: self._process.stdin.write(msg.encode()) or self._process.stdin.flush()
        )

        # Read response line
        raw = await loop.run_in_executor(None, self._process.stdout.readline)
        if not raw:
            raise RuntimeError("cua-driver process closed stdout")
        return json.loads(raw.decode())

    async def call_tool(self, name: str, args: Dict) -> Dict[str, Any]:
        """Call a cua-driver MCP tool and return a normalised result dict.

        Returns:
            {
                "data": <str|dict|None>,
                "images": [<base64_str>, ...],
                "structuredContent": <dict|None>,
                "isError": bool,
            }
        """
        async with self._lock:
            await self._ensure_started()
            resp = await self._send_request("tools/call", {
                "name": name,
                "arguments": args,
            })

        if "error" in resp:
            return {"data": resp["error"].get("message", "Unknown error"),
                    "images": [], "structuredContent": None, "isError": True}

        result = resp.get("result", {})
        content_list = result.get("content", [])
        data = None
        images = []
        structured = result.get("structuredContent")

        for item in content_list:
            if item.get("type") == "text":
                data = item.get("text")
            elif item.get("type") == "image":
                images.append(item.get("data", ""))

        return {
            "data": data,
            "images": images,
            "structuredContent": structured,
            "isError": result.get("isError", False),
        }


# ---------------------------------------------------------------------------
# Backend  (stateful window context + action methods)
# ---------------------------------------------------------------------------

# Module-level singletons — shared across tool calls within a process
_bridge = _AsyncBridge()
_session = _CuaDriverSession()


class CuaDriverBackend:
    """Stateful macOS desktop control backend.

    Maintains _active_pid and _active_window_id across calls so that
    rapid action sequences target the same window without re-enumerating.
    """

    def __init__(self):
        self._active_pid: Optional[int] = None
        self._active_window_id: Optional[int] = None
        self._active_app: Optional[str] = None

    # ------------------------------------------------------------------
    # Capture (window selection + screenshot)
    # ------------------------------------------------------------------

    def capture(self, mode: str = "som", app: Optional[str] = None) -> CaptureResult:
        """Capture the target window.  Sets the sticky window context.

        Args:
            mode: "som" (AX-tree + optional overlay) or "vision" (screenshot only).
            app: App name substring filter (case-insensitive). If omitted,
                 uses the previously selected window.
        """
        return _bridge.run(self._capture_async(mode=mode, app=app))

    async def _capture_async(self, mode: str, app: Optional[str]) -> CaptureResult:
        if app:
            # Select window by app name
            windows_result = await _session.call_tool("list_windows", {})
            if windows_result["isError"]:
                raise RuntimeError(f"list_windows failed: {windows_result['data']}")

            windows = _parse_windows(windows_result)
            target = _select_window(windows, app)
            if not target:
                raise RuntimeError(
                    f"No window found for app '{app}'. "
                    f"Running apps: {[w.get('app', '') for w in windows]}"
                )
            self._active_pid = target.get("pid")
            self._active_window_id = target.get("windowId")
            self._active_app = target.get("app")

        capture_args: Dict[str, Any] = {"mode": mode}
        if self._active_pid is not None:
            capture_args["pid"] = self._active_pid
        if self._active_window_id is not None:
            capture_args["windowId"] = self._active_window_id

        result = await _session.call_tool("capture", capture_args)
        if result["isError"]:
            raise RuntimeError(f"capture failed: {result['data']}")

        structured = result.get("structuredContent") or {}
        elements = structured.get("elements", [])
        # Try parsing elements from text if structured content absent
        if not elements and result["data"]:
            try:
                parsed = json.loads(result["data"])
                elements = parsed.get("elements", [])
            except (json.JSONDecodeError, AttributeError):
                pass

        return CaptureResult(
            mode=mode,
            width=structured.get("width", 0),
            height=structured.get("height", 0),
            png_b64=result["images"][0] if result["images"] else None,
            elements=elements,
            app=self._active_app,
            window_title=structured.get("windowTitle"),
        )

    # ------------------------------------------------------------------
    # Click
    # ------------------------------------------------------------------

    def click(
        self,
        element: Optional[int] = None,
        x: Optional[float] = None,
        y: Optional[float] = None,
        button: str = "left",
        click_count: int = 1,
    ) -> ActionResult:
        return _bridge.run(self._action_async("click", {
            "pid": self._active_pid,
            "windowId": self._active_window_id,
            "element": element,
            "x": x,
            "y": y,
            "button": button,
            "clickCount": click_count,
        }))

    # ------------------------------------------------------------------
    # Type text
    # ------------------------------------------------------------------

    def type_text(self, text: str) -> ActionResult:
        return _bridge.run(self._action_async("type", {
            "pid": self._active_pid,
            "windowId": self._active_window_id,
            "text": text,
        }))

    # ------------------------------------------------------------------
    # Key combo
    # ------------------------------------------------------------------

    def key(self, keys: str) -> ActionResult:
        return _bridge.run(self._action_async("key", {
            "pid": self._active_pid,
            "windowId": self._active_window_id,
            "keys": keys,
        }))

    # ------------------------------------------------------------------
    # Scroll
    # ------------------------------------------------------------------

    def scroll(
        self,
        direction: str,
        amount: float,
        element: Optional[int] = None,
        x: Optional[float] = None,
        y: Optional[float] = None,
    ) -> ActionResult:
        return _bridge.run(self._action_async("scroll", {
            "pid": self._active_pid,
            "windowId": self._active_window_id,
            "direction": direction,
            "amount": amount,
            "element": element,
            "x": x,
            "y": y,
        }))

    # ------------------------------------------------------------------
    # Drag
    # ------------------------------------------------------------------

    def drag(
        self,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
    ) -> ActionResult:
        return _bridge.run(self._action_async("drag", {
            "pid": self._active_pid,
            "windowId": self._active_window_id,
            "startX": start_x,
            "startY": start_y,
            "endX": end_x,
            "endY": end_y,
        }))

    # ------------------------------------------------------------------
    # Set value (dropdowns / AXPopUpButton)
    # ------------------------------------------------------------------

    def set_value(self, value: str, element: int) -> ActionResult:
        return _bridge.run(self._action_async("setValue", {
            "pid": self._active_pid,
            "windowId": self._active_window_id,
            "element": element,
            "value": value,
        }))

    # ------------------------------------------------------------------
    # Focus app  (context update only — no focus theft)
    # ------------------------------------------------------------------

    def focus_app(self, app: str) -> ActionResult:
        """Update active window context for the named app.

        Does NOT bring the window to front or steal keyboard focus.
        """
        try:
            result = _bridge.run(self._focus_app_async(app))
            return result
        except Exception as e:
            return ActionResult(success=False, message=str(e))

    async def _focus_app_async(self, app: str) -> ActionResult:
        windows_result = await _session.call_tool("list_windows", {})
        if windows_result["isError"]:
            return ActionResult(
                success=False,
                message=f"list_windows failed: {windows_result['data']}"
            )
        windows = _parse_windows(windows_result)
        target = _select_window(windows, app)
        if not target:
            return ActionResult(
                success=False,
                message=f"No window found for app '{app}'"
            )
        self._active_pid = target.get("pid")
        self._active_window_id = target.get("windowId")
        self._active_app = target.get("app")
        return ActionResult(
            success=True,
            message=f"Context set to {self._active_app} (pid={self._active_pid})",
        )

    # ------------------------------------------------------------------
    # List apps
    # ------------------------------------------------------------------

    def list_apps(self) -> List[str]:
        return _bridge.run(self._list_apps_async())

    async def _list_apps_async(self) -> List[str]:
        result = await _session.call_tool("list_windows", {})
        if result["isError"]:
            return []
        windows = _parse_windows(result)
        seen = {}
        for w in windows:
            app = w.get("app", "")
            if app and app not in seen:
                seen[app] = True
        return sorted(seen.keys())

    # ------------------------------------------------------------------
    # Generic action helper
    # ------------------------------------------------------------------

    async def _action_async(self, tool_name: str, args: Dict) -> ActionResult:
        # Strip None values — cua-driver rejects unknown null fields
        clean_args = {k: v for k, v in args.items() if v is not None}
        result = await _session.call_tool(tool_name, clean_args)
        if result["isError"]:
            return ActionResult(success=False, message=str(result["data"]))
        msg = str(result["data"]) if result["data"] else "ok"
        return ActionResult(success=True, message=msg, data=result.get("structuredContent"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_windows(result: Dict) -> List[Dict]:
    """Extract window list from a call_tool result."""
    structured = result.get("structuredContent")
    if isinstance(structured, list):
        return structured
    if isinstance(structured, dict):
        return structured.get("windows", [])
    if result.get("data"):
        try:
            parsed = json.loads(result["data"])
            if isinstance(parsed, list):
                return parsed
            return parsed.get("windows", [])
        except (json.JSONDecodeError, AttributeError):
            pass
    return []


def _select_window(windows: List[Dict], app: str) -> Optional[Dict]:
    """Return the best-matching window for *app*.

    Matches by case-insensitive substring.  Among matches, prefers the
    window with the lowest z-index (frontmost on macOS).
    """
    app_lower = app.lower()
    matches = [
        w for w in windows
        if app_lower in w.get("app", "").lower()
    ]
    if not matches:
        return None
    # Lower z-index = closer to front
    matches.sort(key=lambda w: w.get("zIndex", 9999))
    return matches[0]
