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
    # Legacy installs may place cua-driver beside the Python running Spark.
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
    lines.append(f"  Install cua-driver: {cua_driver_install_command()}")
    return "\n".join(lines)


def cua_driver_install_command() -> str:
    """Return the official macOS installer command for Cua Driver."""
    return (
        '/bin/bash -c "$(curl -fsSL '
        'https://raw.githubusercontent.com/trycua/cua/main/libs/cua-driver/scripts/install.sh)"'
    )


def _cua_timeout_message() -> str:
    return (
        "cua-driver did not respond within "
        f"{int(_CALL_TIMEOUT)}s. Start the CuaDriver daemon and grant macOS "
        "Accessibility + Screen Recording permissions, then retry: "
        "open -n -g -a CuaDriver --args serve && cua-driver check_permissions"
    )


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
    pid: Optional[int] = None
    window_id: Optional[int] = None
    tree_markdown: Optional[str] = None


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

    def run(self, coro, timeout: float = _CALL_TIMEOUT + 5) -> Any:
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
        try:
            await self._send_request_with_timeout("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "spark-agent", "version": "1.0"},
            })
        except TimeoutError:
            self._terminate_process()
            raise

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

        def _write_and_flush() -> None:
            self._process.stdin.write(msg.encode())
            self._process.stdin.flush()

        # Write in executor to avoid blocking
        await loop.run_in_executor(
            None,
            _write_and_flush,
        )

        # Read response line
        raw = await loop.run_in_executor(None, self._process.stdout.readline)
        if not raw:
            raise RuntimeError("cua-driver process closed stdout")
        return json.loads(raw.decode())

    async def _send_request_with_timeout(
        self,
        method: str,
        params: Dict,
        timeout: float = _CALL_TIMEOUT,
    ) -> Dict:
        try:
            return await asyncio.wait_for(
                self._send_request(method, params),
                timeout=timeout,
            )
        except asyncio.TimeoutError as e:
            raise TimeoutError(_cua_timeout_message()) from e

    def _terminate_process(self) -> None:
        proc = self._process
        self._process = None
        if not proc or proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

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
            try:
                await self._ensure_started()
                timeout = 5 if name in {"list_apps", "list_windows"} else _CALL_TIMEOUT
                resp = await self._send_request_with_timeout(
                    "tools/call",
                    {
                        "name": name,
                        "arguments": args,
                    },
                    timeout=timeout,
                )
            except TimeoutError as e:
                self._terminate_process()
                return {
                    "data": str(e),
                    "images": [],
                    "structuredContent": None,
                    "isError": True,
                }

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
        self._last_elements: list[dict] = []
        self._last_capture_size: tuple[int, int] = (0, 0)
        self._last_window_origin: tuple[float, float] | None = None

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
                launch = await _session.call_tool(
                    "launch_app",
                    {"name": _normalize_app_query(app)},
                )
                if launch["isError"]:
                    raise RuntimeError(f"launch_app failed: {launch['data']}")
                windows = _parse_launch_windows(launch)
                target = _select_window(windows, app)
                if not target and len(windows) == 1 and _valid_window_target(windows[0]):
                    target = windows[0]
            if not target or not _valid_window_target(target):
                raise RuntimeError(
                    f"No usable window found for app '{app}' (need pid and window_id). "
                    f"Running apps: {[_window_app(w) for w in windows]}"
                )
            self._active_pid = target.get("pid")
            self._active_window_id = _window_id(target)
            self._active_app = _window_app(target)
            self._last_window_origin = _window_origin(target)
        elif self._active_pid is None:
            raise RuntimeError(
                "capture requires app=<name> before any active window has been selected. "
                "Retry with action='capture' and app set to the native app name, "
                "for example app='Notion'."
            )

        capture_args: Dict[str, Any] = {}
        if self._active_pid is not None:
            capture_args["pid"] = self._active_pid
        if self._active_window_id is not None:
            capture_args["window_id"] = self._active_window_id

        result = await _session.call_tool("get_window_state", capture_args)
        if result["isError"]:
            raise RuntimeError(f"capture failed: {result['data']}")

        structured = result.get("structuredContent") or {}
        elements = structured.get("elements") or _parse_elements_from_markdown(
            structured.get("tree_markdown") or result.get("data") or ""
        )
        # Try parsing elements from text if structured content absent
        if not elements and result["data"]:
            try:
                parsed = json.loads(result["data"])
                elements = parsed.get("elements", [])
            except (json.JSONDecodeError, AttributeError):
                pass

        width = structured.get("screenshot_width", structured.get("width", 0))
        height = structured.get("screenshot_height", structured.get("height", 0))
        self._last_elements = elements if isinstance(elements, list) else []
        self._last_capture_size = (int(width or 0), int(height or 0))
        self._last_window_origin = _window_origin(
            structured,
            fallback=self._last_window_origin,
        )

        return CaptureResult(
            mode=mode,
            width=width,
            height=height,
            png_b64=result["images"][0] if result["images"] else None,
            elements=elements,
            app=self._active_app,
            window_title=structured.get("window_title") or structured.get("windowTitle"),
            pid=self._active_pid,
            window_id=self._active_window_id,
            tree_markdown=structured.get("tree_markdown") or result.get("data"),
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
        args: Dict[str, Any] = {
            "pid": self._active_pid,
            "window_id": self._active_window_id,
            "element_index": element,
            "x": x,
            "y": y,
            "count": click_count,
        }
        if button == "right" and element is not None:
            args["action"] = "show_menu"
        result = _bridge.run(self._action_async("click", args))
        self._attach_pointer_metadata(result, x=x, y=y, element=element, kind="click")
        return result

    # ------------------------------------------------------------------
    # Type text
    # ------------------------------------------------------------------

    def type_text(self, text: str) -> ActionResult:
        return _bridge.run(self._action_async("type_text", {
            "pid": self._active_pid,
            "window_id": self._active_window_id,
            "text": text,
        }))

    # ------------------------------------------------------------------
    # Key combo
    # ------------------------------------------------------------------

    def key(self, keys: str) -> ActionResult:
        normalized = _parse_key_combo(keys)
        if len(normalized) > 1:
            return _bridge.run(self._action_async("hotkey", {
                "pid": self._active_pid,
                "window_id": self._active_window_id,
                "keys": normalized,
            }))
        return _bridge.run(self._action_async("press_key", {
            "pid": self._active_pid,
            "window_id": self._active_window_id,
            "key": normalized[0],
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
        result = _bridge.run(self._action_async("scroll", {
            "pid": self._active_pid,
            "window_id": self._active_window_id,
            "direction": direction,
            "amount": amount,
            "element_index": element,
        }))
        self._attach_pointer_metadata(
            result,
            x=x,
            y=y,
            element=element,
            kind="scroll",
            extra={"direction": direction, "amount": amount},
        )
        return result

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
        result = _bridge.run(self._action_async("drag", {
            "pid": self._active_pid,
            "window_id": self._active_window_id,
            "from_x": start_x,
            "from_y": start_y,
            "to_x": end_x,
            "to_y": end_y,
        }))
        self._attach_pointer_metadata(
            result,
            x=end_x,
            y=end_y,
            kind="drag",
            extra={"start_x": start_x, "start_y": start_y, "end_x": end_x, "end_y": end_y},
        )
        return result

    # ------------------------------------------------------------------
    # Set value (dropdowns / AXPopUpButton)
    # ------------------------------------------------------------------

    def set_value(self, value: str, element: int) -> ActionResult:
        result = _bridge.run(self._action_async("set_value", {
            "pid": self._active_pid,
            "window_id": self._active_window_id,
            "element_index": element,
            "value": value,
        }))
        self._attach_pointer_metadata(result, element=element, kind="set_value")
        return result

    def _attach_pointer_metadata(
        self,
        result: ActionResult,
        *,
        x: float | None = None,
        y: float | None = None,
        element: int | None = None,
        kind: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Add best-effort visual pointer metadata for desktop chat UI."""
        if not result.success:
            return
        px, py = _resolve_pointer_xy(self._last_elements, element=element, x=x, y=y)
        if px is None or py is None:
            return
        width, height = self._last_capture_size
        if self._last_window_origin is None:
            return
        origin_x, origin_y = self._last_window_origin
        screen_x = origin_x + px
        screen_y = origin_y + py
        data = dict(result.data or {})
        pointer = {
            "kind": kind,
            "x": px,
            "y": py,
            "screen_x": screen_x,
            "screen_y": screen_y,
            "element": element,
            "window_width": width,
            "window_height": height,
            "window_x": origin_x,
            "window_y": origin_y,
            "app": self._active_app,
        }
        if extra:
            pointer.update(extra)
        data["pointer"] = pointer
        result.data = data

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
        self._active_window_id = _window_id(target)
        self._active_app = _window_app(target)
        self._last_window_origin = _window_origin(target)
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
            app = _window_app(w)
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


def _resolve_pointer_xy(
    elements: list[dict],
    *,
    element: int | None,
    x: float | None,
    y: float | None,
) -> tuple[float | None, float | None]:
    if x is not None and y is not None:
        return float(x), float(y)
    if element is None or element < 0 or element >= len(elements):
        return None, None

    item = elements[element]
    bounds = (
        item.get("bounds")
        or item.get("frame")
        or item.get("rect")
        or item.get("bbox")
        or {}
    )
    if not isinstance(bounds, dict):
        return None, None

    left = _first_number(bounds, "x", "left", "min_x")
    top = _first_number(bounds, "y", "top", "min_y")
    width = _first_number(bounds, "width", "w")
    height = _first_number(bounds, "height", "h")
    right = _first_number(bounds, "right", "max_x")
    bottom = _first_number(bounds, "bottom", "max_y")

    if left is None or top is None:
        return None, None
    if width is None and right is not None:
        width = right - left
    if height is None and bottom is not None:
        height = bottom - top

    return left + (width or 0) / 2, top + (height or 0) / 2


def _first_number(data: dict, *keys: str) -> float | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _window_origin(
    data: dict,
    fallback: tuple[float, float] | None = None,
) -> tuple[float, float] | None:
    bounds = (
        data.get("bounds")
        or data.get("frame")
        or data.get("rect")
        or data.get("bbox")
        or data.get("window_bounds")
        or data.get("windowBounds")
        or data
    )
    if not isinstance(bounds, dict):
        return fallback
    x = _first_number(bounds, "screen_x", "window_x", "x", "left", "min_x")
    y = _first_number(bounds, "screen_y", "window_y", "y", "top", "min_y")
    if x is None or y is None:
        return fallback
    return x, y


def _parse_launch_windows(result: Dict) -> List[Dict]:
    """Extract windows returned by launch_app."""
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured.get("windows", [])
    if result.get("data"):
        try:
            parsed = json.loads(result["data"])
            if isinstance(parsed, dict):
                return parsed.get("windows", [])
        except (json.JSONDecodeError, AttributeError):
            pass
    return []


def _window_app(window: Dict) -> str:
    return str(window.get("app") or window.get("app_name") or window.get("name") or "")


def _window_id(window: Dict) -> Optional[int]:
    return window.get("window_id") or window.get("windowId")


def _valid_window_target(window: Dict) -> bool:
    return window.get("pid") is not None and _window_id(window) is not None


def _normalize_app_query(app: str) -> str:
    app = app.strip()
    if app.lower().endswith(".app"):
        app = app[:-4]
    return app.strip()


def _app_match_score(window: Dict, app: str) -> Optional[tuple[int, int]]:
    query = _normalize_app_query(app).lower()
    name = _normalize_app_query(_window_app(window)).lower()
    if not query or not name:
        return None
    if name == query:
        return (0, len(name))
    if name.startswith(query):
        return (1, len(name))
    if query in name:
        return (2, len(name))
    return None


def _parse_key_combo(keys: str) -> List[str]:
    aliases = {
        "command": "cmd",
        "control": "ctrl",
        "alt": "option",
        "enter": "return",
    }
    parts = [
        aliases.get(part.strip().lower(), part.strip().lower())
        for part in keys.replace("+", " ").split()
        if part.strip()
    ]
    return parts or [keys.strip().lower()]


def _parse_elements_from_markdown(markdown: str) -> List[Dict[str, Any]]:
    import re

    elements = []
    for match in re.finditer(r"\[(?:element_index\s+)?(\d+)\]\s*(.+)", markdown):
        elements.append({"index": int(match.group(1)), "description": match.group(2).strip()})
    return elements


def _select_window(windows: List[Dict], app: str) -> Optional[Dict]:
    """Return the best-matching window for *app*.

    Matches by case-insensitive substring.  Among matches, prefers the
    window with the lowest z-index (frontmost on macOS).
    """
    matches = []
    for w in windows:
        score = _app_match_score(w, app)
        if score is not None and _valid_window_target(w):
            matches.append((score, w))
    if not matches:
        return None
    # Prefer exact app-name matches before prefix/substrings, then lower z-index.
    matches.sort(key=lambda item: (*item[0], item[1].get("zIndex", item[1].get("z_index", 9999))))
    return matches[0][1]
