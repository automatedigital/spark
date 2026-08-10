#!/usr/bin/env python3
"""
Spark Agent CLI - Interactive Terminal Interface

A beautiful command-line interface for the Spark Agent, inspired by Claude Code.
Features ASCII art branding, interactive REPL, toolset selection, and rich formatting.

Usage:
    python cli.py                          # Start interactive mode with all tools
    python cli.py --toolsets web,terminal  # Start with specific toolsets
    python cli.py --skills spark-agent-dev,github-auth
    python cli.py -q "your question"       # Single query mode
    python cli.py --list-tools             # List available tools and exit
"""

import atexit
import logging
import os
import shutil
import sys
import textwrap
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Suppress startup messages for clean CLI experience
os.environ["SPARK_QUIET"] = "1"  # Our own modules


# prompt_toolkit for fixed input area TUI
from prompt_toolkit.application import Application
from prompt_toolkit.filters import Condition
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import (
    ConditionalContainer,
    FormattedTextControl,
    HSplit,
    Layout,
    Window,
)
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.layout.processors import (
    ConditionalProcessor,
    PasswordProcessor,
    Processor,
    Transformation,
)
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style as PTStyle
from prompt_toolkit.widgets import TextArea

try:
    from prompt_toolkit.cursor_shapes import CursorShape

    _STEADY_CURSOR = CursorShape.BLOCK  # Non-blinking block cursor
except (ImportError, AttributeError):
    _STEADY_CURSOR = None
import queue
import threading

from agent.usage_pricing import (
    CanonicalUsage,
    estimate_usage_cost,
    format_duration_compact,
    format_token_count_compact,
)
from spark_cli.banner import _format_context_length, format_banner_version_label

_COMMAND_SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


class _SessionScopedFileHistory(FileHistory):
    """FileHistory whose ↑/↓ recall is scoped to the current session.

    New inputs are still persisted to the shared history file, but prior-session
    entries are not preloaded into the navigable history — so arrow-up cycles
    only through what was typed this session instead of surfacing unrelated
    commands from past runs.
    """

    def load_history_strings(self):  # type: ignore[override]
        return iter([])

# Status verbs shown while the agent is working — rotate every 2 seconds.
_AGENT_STATUS_VERBS = (
    "Browsing...",
    "Thinking...",
    "Coalescing...",
    "Combobulating...",
    "Flibbertigibbeting...",
    "Reticulating...",
    "Synthesizing...",
    "Marinating...",
    "Cerebrating...",
    "Percolating...",
    "Noodling...",
    "Ruminating...",
    "Concocting...",
    "Machinating...",
    "Cogitating...",
    "Vibing...",
    "Pondering...",
    "Discombobulating...",
    "Schmoozing...",
    "Mulling...",
    "Stewing...",
    "Brewing...",
    "Calibrating...",
    "Calibrating vibes...",
    "Gently panicking (internally)...",
    "Indexing reality...",
    "Plotting revenge (on variance)...",
    "Querying the void...",
    "Reconciling vibes...",
    "Refactoring thought...",
    "Rehydrating facts...",
    "Sharpening pencils...",
    "Sifting sand...",
    "Simmering...",
    "Spinning plates...",
    "Stress-testing patience...",
    "Tasting significance...",
    "Threading needles...",
    "Untangling timing...",
    "Warming caches...",
    "Wrestling pandas...",
)
_AGENT_VERB_INTERVAL = 2.0  # seconds between verb rotations


# Load .env from ~/.spark/.env first, then project root as dev fallback.
# User-managed env files should override stale shell exports on restart.
from core.spark_constants import display_spark_home, get_spark_home
from spark_cli.env_loader import load_spark_dotenv

_spark_home = get_spark_home()
_project_env = Path(__file__).parent / ".env"
load_spark_dotenv(spark_home=_spark_home, project_env=_project_env)


# =============================================================================
# Configuration Loading
# =============================================================================


from core.cli.config_state import (  # noqa: E402  (extracted Phase 3)
    CLI_CONFIG,
    load_cli_config,
    save_config_value,
)
from core.cli.parsing import (  # noqa: E402  (extracted Phase 3)
    _get_chrome_debug_candidates,
    _load_prefill_messages,
    _parse_reasoning_config,
    _parse_service_tier_config,
)

# Initialize centralized logging early - agent.log + errors.log in ~/"spark/logs/.
# This ensures CLI sessions produce a log trail even before AIAgent is instantiated.
try:
    from core.spark_logging import setup_logging

    setup_logging(mode="cli")
except Exception:
    # Logging setup is best-effort - don't crash the CLI
    logger.debug("Ignored exception in module setup", exc_info=True)

# Validate config structure early - print warnings before user hits cryptic errors
try:
    from spark_cli.config import print_config_warnings

    print_config_warnings()
except Exception:
    logger.debug("Ignoring error in __init__()", exc_info=True)

# Initialize the skin engine from config
try:
    from spark_cli.skin_engine import init_skin_from_config

    init_skin_from_config(CLI_CONFIG)
except Exception:
    # Skin engine is optional - default skin used if unavailable
    logger.debug("Ignored exception in module setup", exc_info=True)

# Initialize tool preview length from config
try:
    from agent.display import set_tool_preview_max_len

    _tpl = CLI_CONFIG.get("display", {}).get("tool_preview_length", 0)
    set_tool_preview_max_len(int(_tpl) if _tpl else 0)
except Exception:
    logger.debug("Ignoring error in __init__()", exc_info=True)

# Neuter AsyncHttpxClientWrapper.__del__ before any AsyncOpenAI clients are
# created.  The SDK's __del__ schedules aclose() on asyncio.get_running_loop()
# which, during CLI idle time, finds prompt_toolkit's event loop and tries to
# close TCP transports bound to dead worker loops - producing
# "Event loop is closed" / "Press ENTER to continue..." errors.
try:
    from agent.auxiliary_client import neuter_async_httpx_del

    neuter_async_httpx_del()
except Exception:
    logger.debug("Ignoring error in __init__()", exc_info=True)

import fire
from rich import box as rich_box
from rich.console import Console
from rich.markup import escape as _escape
from rich.panel import Panel

from core.model_tools import get_tool_definitions, get_toolset_for_tool

# Import the agent and tool systems
from core.run_agent import AIAgent
from core.toolsets import get_all_toolsets, get_toolset_info, validate_toolset

# Cron job system for scheduled tasks (execution is handled by the gateway)
from cron import get_job

# Extracted CLI modules (Phase 3)
from spark_cli.banner import build_welcome_banner
from spark_cli.callbacks import prompt_for_secret
from spark_cli.commands import SlashCommandAutoSuggest, SlashCommandCompleter
from tools.browser_tool import _emergency_cleanup_all_sessions as _cleanup_all_browsers
from tools.skills_tool import set_secret_capture_callback

# Resource cleanup imports for safe shutdown (terminal VMs, browser sessions)
from tools.terminal_tool import cleanup_all_environments as _cleanup_all_terminals
from tools.terminal_tool import set_approval_callback, set_sudo_password_callback

# Guard to prevent cleanup from running multiple times on exit
_cleanup_done = False
# Weak reference to the active AIAgent for memory provider shutdown at exit
_active_agent_ref = None


def _run_cleanup():
    """Run resource cleanup exactly once."""
    global _cleanup_done
    if _cleanup_done:
        return
    _cleanup_done = True
    try:
        _cleanup_all_terminals()
    except Exception:
        logger.debug("Ignoring error in _run_cleanup()", exc_info=True)
    try:
        _cleanup_all_browsers()
    except Exception:
        logger.debug("Ignoring error in _run_cleanup()", exc_info=True)
    try:
        from tools.mcp_tool import shutdown_mcp_servers

        shutdown_mcp_servers()
    except Exception:
        logger.debug("Ignoring error in _run_cleanup()", exc_info=True)
    # Close cached auxiliary LLM clients (sync + async) so that
    # AsyncHttpxClientWrapper.__del__ doesn't fire on a closed event loop
    # and trigger prompt_toolkit's "Press ENTER to continue..." handler.
    try:
        from agent.auxiliary_client import shutdown_cached_clients

        shutdown_cached_clients()
    except Exception:
        logger.debug("Ignoring error in _run_cleanup()", exc_info=True)
    # Shut down memory provider (on_session_end + shutdown_all) at actual
    # session boundary - NOT per-turn inside run_conversation().
    try:
        from spark_cli.plugins import invoke_hook as _invoke_hook

        _invoke_hook(
            "on_session_finalize",
            session_id=_active_agent_ref.session_id if _active_agent_ref else None,
            platform="cli",
        )
    except Exception:
        logger.debug("Ignoring error in _run_cleanup()", exc_info=True)
    try:
        if _active_agent_ref and hasattr(_active_agent_ref, "shutdown_memory_provider"):
            _active_agent_ref.shutdown_memory_provider(
                getattr(_active_agent_ref, "conversation_history", None) or []
            )
    except Exception:
        logger.debug("Ignoring error in _run_cleanup()", exc_info=True)


# =============================================================================
# Git Worktree Isolation (#652)
# =============================================================================

from core.cli.attachments import (  # noqa: E402  (extracted Phase 3)
    _IMAGE_EXTENSIONS,
    _collect_query_images,
    _detect_file_drop,
    _format_image_attachment_badges,
    _format_process_notification,
    _resolve_attachment_path,
    _should_auto_attach_clipboard_image_on_paste,
    _split_path_input,
    _termux_example_image_path,
)

# ============================================================================
# ASCII Art & Branding
# ============================================================================
# Color palette (hex colors for Rich markup):
# - Gold: #FFD700 (headers, highlights)
# - Amber: #FFBF00 (secondary highlights)
# - Bronze: #CD7F32 (tertiary elements)
# - Light: #FFF8DC (text)
# - Dim: #B8860B (muted text)
# ANSI building blocks for conversation display
from core.cli.render import (  # noqa: E402  (extracted Phase 3)
    _ACCENT,
    _ACCENT_ANSI_DEFAULT,
    _BOLD,
    _DIM,
    _RST,
    _accent_hex,
    _cprint,
    _hex_to_ansi,
    _rich_text_from_ansi,
    _SkinAwareAnsi,
)
from core.cli.worktree import (  # noqa: E402  (extracted Phase 3)
    _cleanup_worktree,
    _git_repo_root,
    _path_is_within_root,
    _prune_orphaned_branches,
    _prune_stale_worktrees,
    _setup_worktree,
    set_active_worktree,
)

# ---------------------------------------------------------------------------
# File-drop / local attachment detection - extracted as pure helpers for tests.
# ---------------------------------------------------------------------------
from core.spark_constants import is_termux as _is_termux_environment


class ChatConsole:
    """Rich Console adapter for prompt_toolkit's patch_stdout context.

    Captures Rich's rendered ANSI output and routes it through _cprint
    so colors and markup render correctly inside the interactive chat loop.
    Drop-in replacement for Rich Console - just pass this to any function
    that expects a console.print() interface.
    """

    def __init__(self):
        from io import StringIO

        self._buffer = StringIO()
        self._inner = Console(
            file=self._buffer,
            force_terminal=True,
            color_system="truecolor",
            highlight=False,
        )

    def print(self, *args, **kwargs):
        self._buffer.seek(0)
        self._buffer.truncate()
        # Read terminal width at render time so panels adapt to current size
        self._inner.width = shutil.get_terminal_size((80, 24)).columns
        self._inner.print(*args, **kwargs)
        output = self._buffer.getvalue()
        for line in output.rstrip("\n").split("\n"):
            _cprint(line)

    @contextmanager
    def status(self, *_args, **_kwargs):
        """Provide a no-op Rich-compatible status context.

        Some slash command helpers use ``console.status(...)`` when running in
        the standalone CLI. Interactive chat routes those helpers through
        ``ChatConsole()``, which historically only implemented ``print()``.
        Returning a silent context manager keeps slash commands compatible
        without duplicating the higher-level busy indicator already shown by
        ``SparkCLI._busy_command()``.
        """
        yield self


# ASCII Art - SPARK-AGENT logo (full width, single line - requires ~95 char terminal)
SPARK_AGENT_LOGO = """[bold #FFD700]██+  ██+███████+██████+ ███+   ███+███████+███████+       █████+  ██████+ ███████+███+   ██+████████+[/]
[bold #FFD700]██|  ██|██+====+██+==██+████+ ████|██+====+██+====+      ██+==██+██+====+ ██+====+████+  ██|+==██+==+[/]
[#FFBF00]███████|█████+  ██████++██+████+██|█████+  ███████+█████+███████|██|  ███+█████+  ██+██+ ██|   ██|[/]
[#FFBF00]██+==██|██+==+  ██+==██+██|+██++██|██+==+  +====██|+====+██+==██|██|   ██|██+==+  ██|+██+██|   ██|[/]
[#CD7F32]██|  ██|███████+██|  ██|██| +=+ ██|███████+███████|      ██|  ██|+██████++███████+██| +████|   ██|[/]
[#CD7F32]+=+  +=++======++=+  +=++=+     +=++======++======+      +=+  +=+ +=====+ +======++=+  +===+   +=+[/]"""

# ASCII Art - Spark Caduceus (compact, fits in left panel)
SPARK_CADUCEUS = """[#CD7F32]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⡀⠀⣀⣀⠀⢀⣀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
[#CD7F32]⠀⠀⠀⠀⠀⠀⢀⣠⣴⣾⣿⣿⣇⠸⣿⣿⠇⣸⣿⣿⣷⣦⣄⡀⠀⠀⠀⠀⠀⠀[/]
[#FFBF00]⠀⢀⣠⣴⣶⠿⠋⣩⡿⣿⡿⠻⣿⡇⢠⡄⢸⣿⠟⢿⣿⢿⣍⠙⠿⣶⣦⣄⡀⠀[/]
[#FFBF00]⠀⠀⠉⠉⠁⠶⠟⠋⠀⠉⠀⢀⣈⣁⡈⢁⣈⣁⡀⠀⠉⠀⠙⠻⠶⠈⠉⠉⠀⠀[/]
[#FFD700]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣴⣿⡿⠛⢁⡈⠛⢿⣿⣦⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
[#FFD700]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠿⣿⣦⣤⣈⠁⢠⣴⣿⠿⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
[#FFBF00]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠉⠻⢿⣿⣦⡉⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
[#FFBF00]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘⢷⣦⣈⠛⠃⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
[#CD7F32]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢠⣴⠦⠈⠙⠿⣦⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
[#CD7F32]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠸⣿⣤⡈⠁⢤⣿⠇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
[#B8860B]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠉⠛⠷⠄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
[#B8860B]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⠑⢶⣄⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
[#B8860B]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣿⠁⢰⡆⠈⡿⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
[#B8860B]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠳⠈⣡⠞⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
[#B8860B]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]"""


def _build_compact_banner() -> str:
    """Build a compact banner that fits the current terminal width."""
    try:
        from spark_cli.skin_engine import get_active_skin

        _skin = get_active_skin()
    except Exception:
        _skin = None

    skin_name = getattr(_skin, "name", "default") if _skin else "default"
    border_color = _skin.get_color("banner_border", "#555555") if _skin else "#555555"
    title_color = _skin.get_color("banner_title", "#FFBF00") if _skin else "#FFBF00"
    dim_color = _skin.get_color("banner_dim", "#B8860B") if _skin else "#B8860B"

    if skin_name == "default":
        line1 = "S Spark - AI Agent Framework"
        tiny_line = "S Spark Agent"
    else:
        agent_name = (
            _skin.get_branding("agent_name", "Spark Agent") if _skin else "Spark Agent"
        )
        line1 = f"{agent_name} - AI Agent Framework"
        tiny_line = agent_name

    version_line = format_banner_version_label()

    w = min(shutil.get_terminal_size().columns - 2, 88)
    if w < 30:
        return (
            f"\n[{title_color}]{tiny_line}[/] [dim {dim_color}]- Automate Digital[/]\n"
        )

    inner = w - 2  # inside the box border
    bar = "=" * w
    content_width = inner - 2

    # Truncate and pad to fit
    line1 = line1[:content_width].ljust(content_width)
    line2 = version_line[:content_width].ljust(content_width)

    return (
        f"\n[bold {border_color}]+{bar}+[/]\n"
        f"[bold {border_color}]|[/] [{title_color}]{line1}[/] [bold {border_color}]|[/]\n"
        f"[bold {border_color}]|[/] [dim {dim_color}]{line2}[/] [bold {border_color}]|[/]\n"
        f"[bold {border_color}]+{bar}+[/]\n"
    )


# ============================================================================
# Slash-command detection helper
# ============================================================================


def _looks_like_slash_command(text: str) -> bool:
    """Return True if *text* looks like a slash command, not a file path.

    Slash commands are ``/help``, ``/model gpt-4``, ``/q``, etc.
    File paths like ``/Users/ironin/file.md:45-46 can you fix this?``
    also start with ``/`` but contain additional ``/`` characters in
    the first whitespace-delimited word.  This helper distinguishes
    the two so that pasted paths are sent to the agent instead of
    triggering "Unknown command".
    """
    if not text or not text.startswith("/"):
        return False
    first_word = text.split()[0]
    # After stripping the leading /, a command name has no slashes.
    # A path like /Users/foo/bar.md always does.
    return "/" not in first_word[1:]


# ============================================================================
# Skill Slash Commands - dynamic commands generated from installed skills
# ============================================================================

from agent.skill_commands import (
    build_plan_path,
    build_preloaded_skills_prompt,
    build_skill_invocation_message,
    scan_skill_commands,
)

_skill_commands = scan_skill_commands()


def _get_plugin_cmd_handler_names() -> set:
    """Return plugin command names (without slash prefix) for dispatch matching."""
    try:
        from spark_cli.plugins import get_plugin_manager

        return set(get_plugin_manager()._plugin_commands.keys())
    except Exception:
        return set()


def _parse_skills_argument(
    skills: str | list[str] | tuple[str, ...] | None,
) -> list[str]:
    """Normalize a CLI skills flag into a deduplicated list of skill identifiers."""
    if not skills:
        return []

    if isinstance(skills, str):
        raw_values = [skills]
    elif isinstance(skills, (list, tuple)):
        raw_values = [str(item) for item in skills if item is not None]
    else:
        raw_values = [str(skills)]

    parsed: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        for part in raw.split(","):
            normalized = part.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            parsed.append(normalized)
    return parsed




# ============================================================================
# SparkCLI Class
# ============================================================================


from core.cli.agent_setup_mixin import _AgentSetupMixin  # noqa: E402  (Phase 3)
from core.cli.callbacks_mixin import _CallbacksMixin  # noqa: E402  (Phase 3)
from core.cli.commands_mixin import _CommandHandlersMixin
from core.cli.display_mixin import _DisplayCommandsMixin  # noqa: E402  (Phase 3)
from core.cli.info_mixin import _InfoCommandsMixin  # noqa: E402  (Phase 3)
from core.cli.main_loop import _MainLoopMixin  # noqa: E402  (Phase 3)
from core.cli.model_mixin import _ModelMixin  # noqa: E402  (Phase 3)
from core.cli.session_ops_mixin import _SessionOpsMixin  # noqa: E402  (Phase 3)
from core.cli.status_bar_mixin import _StatusBarMixin  # noqa: E402  (Phase 3)
from core.cli.streaming_mixin import _StreamingMixin  # noqa: E402  (Phase 3)
from core.cli.tui_mixin import _TuiMixin  # noqa: E402  (Phase 3)
from core.cli.voice_mixin import _VoiceMixin  # noqa: E402  (Phase 3)


class SparkCLI(_MainLoopMixin, _CommandHandlersMixin, _DisplayCommandsMixin, _StreamingMixin, _StatusBarMixin, _VoiceMixin, _CallbacksMixin, _TuiMixin, _ModelMixin, _AgentSetupMixin, _InfoCommandsMixin, _SessionOpsMixin):
    """
    Interactive CLI for the Spark Agent.

    Provides a REPL interface with rich formatting, command history,
    and tool execution capabilities.
    """

    def __init__(
        self,
        model: str = None,
        toolsets: list[str] = None,
        provider: str = None,
        api_key: str = None,
        base_url: str = None,
        max_turns: int = None,
        verbose: bool = False,
        compact: bool = False,
        resume: str = None,
        checkpoints: bool = False,
        pass_session_id: bool = False,
    ):
        """
        Initialize the Spark CLI.

        Args:
            model: Model to use (default: from env or claude-sonnet)
            toolsets: List of toolsets to enable (default: all)
            provider: Inference provider ("auto", "openrouter", "openai-codex", "zai", "kimi-coding", "minimax", "minimax-cn")
            api_key: API key (default: from environment)
            base_url: API base URL (default: OpenRouter)
            max_turns: Maximum tool-calling iterations shared with subagents (default: 90)
            verbose: Enable verbose logging
            compact: Use compact display mode
            resume: Session ID to resume (restores conversation history from SQLite)
            pass_session_id: Include the session ID in the agent's system prompt
        """
        # Initialize Rich console
        self.console = Console()
        self.config = CLI_CONFIG
        self.compact = (
            compact
            if compact is not None
            else CLI_CONFIG["display"].get("compact", False)
        )
        # tool_progress: "off", "new", "all", "verbose" (from config.yaml display section)
        # YAML 1.1 parses bare `off` as boolean False - normalise to string.
        _raw_tp = CLI_CONFIG["display"].get("tool_progress", "all")
        self.tool_progress_mode = "off" if _raw_tp is False else str(_raw_tp)
        # resume_display: "full" (show history) | "minimal" (one-liner only)
        self.resume_display = CLI_CONFIG["display"].get("resume_display", "full")
        # bell_on_complete: play terminal bell (\a) when agent finishes a response
        self.bell_on_complete = CLI_CONFIG["display"].get("bell_on_complete", False)
        # show_reasoning: display model thinking/reasoning before the response
        self.show_reasoning = CLI_CONFIG["display"].get("show_reasoning", False)
        # busy_input_mode: "interrupt" (Enter interrupts current run) or "queue" (Enter queues for next turn)
        _bim = CLI_CONFIG["display"].get("busy_input_mode", "interrupt")
        self.busy_input_mode = (
            "queue" if str(_bim).strip().lower() == "queue" else "interrupt"
        )

        self.verbose = (
            verbose if verbose is not None else (self.tool_progress_mode == "verbose")
        )

        # streaming: stream tokens to the terminal as they arrive (display.streaming in config.yaml)
        self.streaming_enabled = CLI_CONFIG["display"].get("streaming", True)

        # Inline diff previews for write actions (display.inline_diffs in config.yaml)
        self._inline_diffs_enabled = CLI_CONFIG["display"].get("inline_diffs", True)

        # Streaming display state
        self._stream_buf = ""  # Partial line buffer for line-buffered rendering
        self._stream_started = False  # True once first delta arrives
        self._stream_box_opened = False  # True once the response box header is printed
        self._reasoning_preview_buf = (
            ""  # Coalesce tiny reasoning chunks for [thinking] output
        )
        self._pending_edit_snapshots = {}

        # Configuration - priority: CLI args > env vars > config file
        # Model comes from: CLI arg or config.yaml (single source of truth).
        # LLM_MODEL/OPENAI_MODEL env vars are NOT checked - config.yaml is
        # authoritative.  This avoids conflicts in multi-agent setups where
        # env vars would stomp each other.
        _model_config = CLI_CONFIG.get("model", {})
        _config_model = (
            (_model_config.get("default") or _model_config.get("model") or "")
            if isinstance(_model_config, dict)
            else (_model_config or "")
        )
        _DEFAULT_CONFIG_MODEL = ""
        self.model = model or _config_model or _DEFAULT_CONFIG_MODEL
        # Auto-detect model from local server if still on default
        if self.model == _DEFAULT_CONFIG_MODEL:
            _base_url = (
                (_model_config.get("base_url") or "")
                if isinstance(_model_config, dict)
                else ""
            )
            if "localhost" in _base_url or "127.0.0.1" in _base_url:
                from spark_cli.runtime_provider import _auto_detect_local_model

                _detected = _auto_detect_local_model(_base_url)
                if _detected:
                    self.model = _detected
        # Track whether model was explicitly chosen by the user or fell back
        # to the global default.  Provider-specific normalisation may override
        # the default silently but should warn when overriding an explicit choice.
        # A config model that matches the global fallback is NOT considered an
        # explicit choice - the user just never changed it.  But a config model
        # like "gpt-5.3-codex" IS explicit and must be preserved.
        self._model_is_default = not model and (
            not _config_model or _config_model == _DEFAULT_CONFIG_MODEL
        )

        self._explicit_api_key = api_key
        self._explicit_base_url = base_url

        # Provider selection is resolved lazily at use-time via _ensure_runtime_credentials().
        self.requested_provider = (
            provider
            or CLI_CONFIG["model"].get("provider")
            or os.getenv("SPARK_INFERENCE_PROVIDER")
            or "auto"
        )
        self._provider_source: str | None = None
        self.provider = self.requested_provider
        self.api_mode = "chat_completions"
        self.acp_command: str | None = None
        self.acp_args: list[str] = []
        self.base_url = (
            base_url
            or CLI_CONFIG["model"].get("base_url", "")
            or os.getenv("OPENROUTER_BASE_URL", "")
        ) or None
        # Match key to resolved base_url: OpenRouter URL → prefer OPENROUTER_API_KEY,
        # custom endpoint → prefer OPENAI_API_KEY (issue #560).
        # Note: _ensure_runtime_credentials() re-resolves this before first use.
        if self.base_url and "openrouter.ai" in self.base_url:
            self.api_key = (
                api_key
                or os.getenv("OPENROUTER_API_KEY")
                or os.getenv("OPENAI_API_KEY")
            )
        else:
            self.api_key = (
                api_key
                or os.getenv("OPENAI_API_KEY")
                or os.getenv("OPENROUTER_API_KEY")
            )
        # Max turns priority: CLI arg > config file > env var > default
        if max_turns is not None:  # CLI arg was explicitly set
            self.max_turns = max_turns
        elif CLI_CONFIG["agent"].get("max_turns"):
            self.max_turns = CLI_CONFIG["agent"]["max_turns"]
        elif CLI_CONFIG.get("max_turns"):  # Backwards compat: root-level max_turns
            self.max_turns = CLI_CONFIG["max_turns"]
        elif os.getenv("SPARK_MAX_ITERATIONS"):
            self.max_turns = int(os.getenv("SPARK_MAX_ITERATIONS"))
        else:
            self.max_turns = 90

        # Parse and validate toolsets
        self.enabled_toolsets = toolsets
        if toolsets and "all" not in toolsets and "*" not in toolsets:
            # Validate each toolset - MCP server names are added by
            # _get_platform_tools() but aren't registered in TOOLSETS yet
            # (that happens later in _sync_mcp_toolsets), so exclude them.
            mcp_names = set((CLI_CONFIG.get("mcp_servers") or {}).keys())
            invalid = [
                t for t in toolsets if not validate_toolset(t) and t not in mcp_names
            ]
            if invalid:
                self.console.print(
                    f"[bold red]Warning: Unknown toolsets: {', '.join(invalid)}[/]"
                )

        # Filesystem checkpoints: CLI flag > config
        cp_cfg = CLI_CONFIG.get("checkpoints", {})
        if isinstance(cp_cfg, bool):
            cp_cfg = {"enabled": cp_cfg}
        self.checkpoints_enabled = checkpoints or cp_cfg.get("enabled", False)
        self.checkpoint_max_snapshots = cp_cfg.get("max_snapshots", 50)
        self.pass_session_id = pass_session_id

        # Ephemeral system prompt: env var takes precedence, then config
        self.system_prompt = os.getenv(
            "SPARK_EPHEMERAL_SYSTEM_PROMPT", ""
        ) or CLI_CONFIG["agent"].get("system_prompt", "")
        self.personalities = CLI_CONFIG["agent"].get("personalities", {})

        # Ephemeral prefill messages (few-shot priming, never persisted)
        self.prefill_messages = _load_prefill_messages(
            CLI_CONFIG["agent"].get("prefill_messages_file", "")
        )

        # Reasoning config (OpenRouter reasoning effort level)
        self.reasoning_config = _parse_reasoning_config(
            CLI_CONFIG["agent"].get("reasoning_effort", "")
        )
        self.service_tier = _parse_service_tier_config(
            CLI_CONFIG["agent"].get("service_tier", "")
        )

        # OpenRouter provider routing preferences
        pr = CLI_CONFIG.get("provider_routing", {}) or {}
        self._provider_sort = pr.get("sort")
        self._providers_only = pr.get("only")
        self._providers_ignore = pr.get("ignore")
        self._providers_order = pr.get("order")
        self._provider_require_params = pr.get("require_parameters", False)
        self._provider_data_collection = pr.get("data_collection")

        # Fallback provider chain - tried in order when primary fails after retries.
        # Supports new list format (fallback_providers) and legacy single-dict (fallback_model).
        fb = (
            CLI_CONFIG.get("fallback_providers")
            or CLI_CONFIG.get("fallback_model")
            or []
        )
        # Normalize legacy single-dict to a one-element list
        if isinstance(fb, dict):
            fb = [fb] if fb.get("provider") and fb.get("model") else []
        self._fallback_model = fb

        # Optional cheap-vs-strong routing for simple turns
        self._smart_model_routing = CLI_CONFIG.get("smart_model_routing", {}) or {}
        self._response_budget_config = CLI_CONFIG.get("response_budget", {}) or {}
        self._active_agent_route_signature = None

        # Agent will be initialized on first use
        self.agent: AIAgent | None = None
        self._app = None  # prompt_toolkit Application (set in run())

        # Conversation state
        self.conversation_history: list[dict[str, Any]] = []
        self.session_start = datetime.now()
        self._resumed = False
        # Initialize SQLite session store early so /title works before first message
        self._session_db = None
        try:
            from core.spark_state import SessionDB

            self._session_db = SessionDB()
        except Exception as e:
            logger.warning(
                "Failed to initialize SessionDB - session will NOT be indexed for search: %s",
                e,
            )

        # Deferred title: stored in memory until the session is created in the DB
        self._pending_title: str | None = None

        # Session ID: reuse existing one when resuming, otherwise generate fresh
        if resume:
            self.session_id = resume
            self._resumed = True
        else:
            timestamp_str = self.session_start.strftime("%Y%m%d_%H%M%S")
            short_uuid = uuid.uuid4().hex[:6]
            self.session_id = f"{timestamp_str}_{short_uuid}"

        # History file for persistent input recall across sessions
        self._history_file = _spark_home / ".spark_history"
        self._last_invalidate: float = 0.0  # throttle UI repaints
        self._app = None

        # State shared by interactive run() and single-query chat mode.
        # These must exist before any direct chat() call because single-query
        # mode does not go through run().
        self._agent_running = False
        self._pending_input = queue.Queue()
        self._interrupt_queue = queue.Queue()
        self._should_exit = False
        self._last_ctrl_c_time = 0
        self._clarify_state = None
        self._clarify_freetext = False
        self._clarify_deadline = 0
        self._sudo_state = None
        self._sudo_deadline = 0
        self._modal_input_snapshot = None
        self._approval_state = None
        self._approval_deadline = 0
        self._approval_lock = threading.Lock()
        self._model_picker_state = None
        self._secret_state = None
        self._secret_deadline = 0
        self._spinner_text: str = ""  # thinking spinner text for TUI
        self._tool_start_time: float = (
            0.0  # monotonic timestamp when current tool started (for live elapsed)
        )
        self._pending_tool_info: dict = {}  # function_name -> list of (preview, args) for stacked scrollback
        self._last_scrollback_tool: str = (
            ""  # last tool name printed to scrollback (for "new" dedup)
        )
        self._command_running = False
        self._command_status = ""
        self._attached_images: list[Path] = []
        self._image_counter = 0
        self.preloaded_skills: list[str] = []
        self._startup_skills_line_shown = False
        self._show_welcome_logo = False
        self._welcome_logo_ansi: str | None = None
        self._welcome_logo_loaded = False
        self._welcome_splash_text = (
            "Welcome to Spark! Type your message or /help for commands."
        )
        self._welcome_splash_tip = ""
        self._welcome_splash_skills = ""
        self._welcome_splash_color = "#FFF8DC"
        self._welcome_splash_tip_color = "#f66914"

        # Voice mode state (also reinitialized inside run() for interactive TUI).
        self._voice_lock = threading.Lock()
        self._voice_mode = False
        self._voice_tts = False
        self._voice_recorder = None
        self._voice_recording = False
        self._voice_processing = False
        self._voice_continuous = False
        self._voice_tts_done = threading.Event()
        self._voice_tts_done.set()

        # Status bar visibility (toggled via /statusbar)
        self._status_bar_visible = True

        # Background task tracking: {task_id: threading.Thread}
        self._background_tasks: dict[str, threading.Thread] = {}
        self._background_task_counter = 0






# ============================================================================
# Main Entry Point
# ============================================================================


def main(
    query: str = None,
    q: str = None,
    image: str = None,
    toolsets: str = None,
    skills: str | list[str] | tuple[str, ...] = None,
    model: str = None,
    provider: str = None,
    api_key: str = None,
    base_url: str = None,
    max_turns: int = None,
    verbose: bool = False,
    quiet: bool = False,
    compact: bool = False,
    list_tools: bool = False,
    list_toolsets: bool = False,
    gateway: bool = False,
    resume: str = None,
    worktree: bool = False,
    w: bool = False,
    checkpoints: bool = False,
    pass_session_id: bool = False,
):
    """
    Spark Agent CLI - Interactive AI Assistant

    Args:
        query: Single query to execute (then exit). Alias: -q
        q: Shorthand for --query
        image: Optional local image path to attach to a single query
        toolsets: Comma-separated list of toolsets to enable (e.g., "web,terminal")
        skills: Comma-separated or repeated list of skills to preload for the session
        model: Model to use (default: anthropic/claude-opus-4-20250514)
        provider: Inference provider ("auto", "openrouter", "openai-codex", "zai", "kimi-coding", "minimax", "minimax-cn")
        api_key: API key for authentication
        base_url: Base URL for the API
        max_turns: Maximum tool-calling iterations (default: 60)
        verbose: Enable verbose logging
        compact: Use compact display mode
        list_tools: List available tools and exit
        list_toolsets: List available toolsets and exit
        resume: Resume a previous session by its ID (e.g., 20260225_143052_a1b2c3)
        worktree: Run in an isolated git worktree (for parallel agents). Alias: -w
        w: Shorthand for --worktree

    Examples:
        python cli.py                            # Start interactive mode
        python cli.py --toolsets web,terminal    # Use specific toolsets
        python cli.py --skills spark-agent-dev,github-auth
        python cli.py -q "What is Python?"       # Single query mode
        python cli.py -q "Describe this" --image ~/storage/shared/Pictures/cat.png
        python cli.py --list-tools               # List tools and exit
        python cli.py --resume 20260225_143052_a1b2c3  # Resume session
        python cli.py -w                         # Start in isolated git worktree
        python cli.py -w -q "Fix issue #123"     # Single query in worktree
    """

    # Signal to terminal_tool that we're in interactive mode
    # This enables interactive sudo password prompts with timeout
    os.environ["SPARK_INTERACTIVE"] = "1"

    # Handle gateway mode (messaging + cron)
    if gateway:
        import asyncio

        from gateway.run import start_gateway

        print("Starting Spark Gateway (messaging platforms)...")
        asyncio.run(start_gateway())
        return

    # Skip worktree for list commands (they exit immediately)
    if not list_tools and not list_toolsets:
        # -- Git worktree isolation (#652) --
        # Create an isolated worktree so this agent instance doesn't collide
        # with other agents working on the same repo.
        use_worktree = worktree or w or CLI_CONFIG.get("worktree", False)
        wt_info = None
        if use_worktree:
            # Prune stale worktrees from crashed/killed sessions
            _repo = _git_repo_root()
            if _repo:
                _prune_stale_worktrees(_repo)
            wt_info = _setup_worktree()
            if wt_info:
                set_active_worktree(wt_info)
                os.environ["TERMINAL_CWD"] = wt_info["path"]
                atexit.register(_cleanup_worktree, wt_info)
            else:
                # Worktree was explicitly requested but setup failed -
                # don't silently run without isolation.
                return
    else:
        wt_info = None

    # Handle query shorthand
    query = query or q

    # Parse toolsets - handle both string and tuple/list inputs
    # Default to spark-cli toolset which includes cronjob management tools
    toolsets_list = None
    if toolsets:
        if isinstance(toolsets, str):
            toolsets_list = [t.strip() for t in toolsets.split(",")]
        elif isinstance(toolsets, (list, tuple)):
            # Fire may pass multiple --toolsets as a tuple
            toolsets_list = []
            for t in toolsets:
                if isinstance(t, str):
                    toolsets_list.extend([x.strip() for x in t.split(",")])
                else:
                    toolsets_list.append(str(t))
    else:
        # Use the shared resolver so MCP servers are included at runtime
        from spark_cli.tools_config import _get_platform_tools

        toolsets_list = sorted(_get_platform_tools(CLI_CONFIG, "cli"))

    parsed_skills = _parse_skills_argument(skills)

    # Create CLI instance
    cli = SparkCLI(
        model=model,
        toolsets=toolsets_list,
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        max_turns=max_turns,
        verbose=verbose,
        compact=compact,
        resume=resume,
        checkpoints=checkpoints,
        pass_session_id=pass_session_id,
    )

    if parsed_skills:
        skills_prompt, loaded_skills, missing_skills = build_preloaded_skills_prompt(
            parsed_skills,
            task_id=cli.session_id,
        )
        if missing_skills:
            missing_display = ", ".join(missing_skills)
            raise ValueError(f"Unknown skill(s): {missing_display}")
        if skills_prompt:
            cli.system_prompt = "\n\n".join(
                part for part in (cli.system_prompt, skills_prompt) if part
            ).strip()
            cli.preloaded_skills = loaded_skills

    # Inject worktree context into agent's system prompt
    if wt_info:
        wt_note = (
            f"\n\n[System note: You are working in an isolated git worktree at "
            f"{wt_info['path']}. Your branch is `{wt_info['branch']}`. "
            f"Changes here do not affect the main working tree or other agents. "
            f"Remember to commit and push your changes, and create a PR if appropriate. "
            f"The original repo is at {wt_info['repo_root']}.]"
        )
        cli.system_prompt = (cli.system_prompt or "") + wt_note

    # Handle list commands (don't init agent for these)
    if list_tools:
        cli.show_banner()
        cli.show_tools()
        sys.exit(0)

    if list_toolsets:
        cli.show_banner()
        cli.show_toolsets()
        sys.exit(0)

    # Register cleanup for single-query mode (interactive mode registers in run())
    atexit.register(_run_cleanup)

    # Handle single query mode
    if query or image:
        query, single_query_images = _collect_query_images(query, image)
        if quiet:
            # Quiet mode: suppress banner, spinner, tool previews.
            # Only print the final response and parseable session info.
            cli.tool_progress_mode = "off"
            if cli._ensure_runtime_credentials():
                effective_query = query
                if single_query_images:
                    effective_query = cli._preprocess_images_with_vision(
                        query,
                        single_query_images,
                        announce=False,
                    )
                turn_route = cli._resolve_turn_agent_config(effective_query)
                if turn_route["signature"] != cli._active_agent_route_signature:
                    cli.agent = None
                if cli._init_agent(
                    model_override=turn_route["model"],
                    runtime_override=turn_route["runtime"],
                    route_label=turn_route["label"],
                    request_overrides=turn_route.get("request_overrides"),
                ):
                    cli.agent.quiet_mode = True
                    cli.agent.suppress_status_output = True
                    result = cli.agent.run_conversation(
                        user_message=effective_query,
                        conversation_history=cli.conversation_history,
                    )
                    response = (
                        result.get("final_response", "")
                        if isinstance(result, dict)
                        else str(result)
                    )
                    if response:
                        print(response)
                    print(f"\nsession_id: {cli.session_id}")

                    # Ensure proper exit code for automation wrappers
                    sys.exit(
                        1 if isinstance(result, dict) and result.get("failed") else 0
                    )

            # Exit with error code if credentials or agent init fails
            sys.exit(1)
        else:
            cli.show_banner()
            _query_label = query or ("[image attached]" if single_query_images else "")
            if _query_label:
                cli.console.print(f"[bold blue]Query:[/] {_query_label}")
            cli.chat(query, images=single_query_images or None)
            cli._print_exit_summary()
        return

    # Run interactive mode
    cli.run()


if __name__ == "__main__":
    fire.Fire(main)
