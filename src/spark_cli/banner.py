"""Welcome banner, ASCII art, skills summary, and update check for the CLI.

Pure display functions with no SparkCLI state dependency.
"""

import json
import logging
import subprocess
import threading
import time
from pathlib import Path
from core.spark_constants import get_spark_home
from typing import Dict, List, Optional

from rich.console import Console

from prompt_toolkit import print_formatted_text as _pt_print
from prompt_toolkit.formatted_text import ANSI as _PT_ANSI

logger = logging.getLogger(__name__)


# =========================================================================
# ANSI building blocks for conversation display
# =========================================================================

_GOLD = "\033[1;38;2;255;215;0m"  # True-color #FFD700 bold
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RST = "\033[0m"


def cprint(text: str):
    """Print ANSI-colored text through prompt_toolkit's renderer."""
    _pt_print(_PT_ANSI(text))


# =========================================================================
# Skin-aware color helpers
# =========================================================================


def _skin_color(key: str, fallback: str) -> str:
    """Get a color from the active skin, or return fallback."""
    try:
        from spark_cli.skin_engine import get_active_skin

        return get_active_skin().get_color(key, fallback)
    except Exception:
        return fallback


def _skin_branding(key: str, fallback: str) -> str:
    """Get a branding string from the active skin, or return fallback."""
    try:
        from spark_cli.skin_engine import get_active_skin

        return get_active_skin().get_branding(key, fallback)
    except Exception:
        return fallback


# =========================================================================
# ASCII Art & Branding
# =========================================================================

from spark_cli import __version__ as VERSION, __release_date__ as RELEASE_DATE

SPARK_AGENT_LOGO = """[bold #FFD700]███████╗██████╗  █████╗ ██████╗ ██╗  ██╗        █████╗  ██████╗ ███████╗███╗   ██╗████████╗[/]
[bold #FFD700]██╔════╝██╔══██╗██╔══██╗██╔══██╗██║ ██╔╝       ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝[/]
[#FFBF00]███████╗██████╔╝███████║██████╔╝█████╔╝        ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║   [/]
[#FFBF00]╚════██║██╔═══╝ ██╔══██║██╔══██╗██╔═██╗        ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║   [/]
[#CD7F32]███████║██║     ██║  ██║██║  ██║██║  ██╗       ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║   [/]
[#CD7F32]╚══════╝╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝       ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝   [/]"""

SPARK_CADUCEUS = """[#CD7F32]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⣤⣴⡾⠿⠿⠶⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
[#CD7F32]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣠⣾⡿⠛⠋⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
[#FFBF00]⠀⠀⠀⠀⠀⠀⠀⠀⠀⣤⣾⠟⠋⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
[#FFBF00]⠀⠀⠀⠀⠀⠀⢀⣴⡿⠛⠁⠀⠀⢀⣤⣶⣿⣿⣿⣷⣦⡀⠀⠀⠀⠀⠀⠀⠀⠀[/]
[#FFD700]⠀⠀⠀⠀⢀⣴⡿⠋⠀⠀⠀⠀⣴⡿⠋⠀⠀⠀⠈⠙⢿⣷⡀⠀⠀⠀⠀⠀⠀⠀[/]
[#FFD700]⠀⠀⠀⣴⡿⠋⠀⠀⠀⠀⢀⣾⠏⠀⠀⠀⠀⠀⠀⠀⠀⠹⣿⣄⠀⠀⠀⠀⠀⠀[/]
[#FFBF00]⠀⢀⣾⠟⠀⠀⠀⠀⠀⣠⡿⠃⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘⢿⣦⠀⠀⠀⠀⠀[/]
[#FFBF00]⠀⠸⠋⠀⠀⠀⠀⠀⣼⡟⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠻⠄⠀⠀⠀⠀[/]
[#CD7F32]⠀⠀⠀⠀⠀⠀⠀⠀⠙⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
[#CD7F32]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
[#B8860B]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
[#B8860B]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢸⣿⣿⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
[#B8860B]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢸⣿⣿⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
[#B8860B]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘⠿⠿⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]
[#B8860B]⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀[/]"""

SPARK_WORDMARK = r"""[bold #FFD700]  ____                  _   [/]
[bold #FFBF00] / ___| _ __   __ _ _ __| | __[/]
[bold #FFBF00] \___ \| '_ \ / _` | '__| |/ /[/]
[#CD7F32]  ___) | |_) | (_| | |  |   < [/]
[#CD7F32] |____/| .__/ \__,_|_|  |_|\_\[/]
[#B8860B]       |_|[/]"""


# =========================================================================
# Skills scanning
# =========================================================================


def get_available_skills() -> dict[str, list[str]]:
    """Return skills grouped by category, filtered by platform and disabled state.

    Delegates to ``_find_all_skills()`` from ``tools/skills_tool`` which already
    handles platform gating (``platforms:`` frontmatter) and respects the
    user's ``skills.disabled`` config list.
    """
    try:
        from tools.skills_tool import _find_all_skills

        all_skills = _find_all_skills()  # already filtered
    except Exception:
        return {}

    skills_by_category: dict[str, list[str]] = {}
    for skill in all_skills:
        category = skill.get("category") or "general"
        skills_by_category.setdefault(category, []).append(skill["name"])
    return skills_by_category


# =========================================================================
# Update check
# =========================================================================

# Cache update check results for 6 hours to avoid repeated git fetches
_UPDATE_CHECK_CACHE_SECONDS = 6 * 3600


def check_for_updates() -> int | None:
    """Check how many commits behind origin/main the local repo is.

    Does a ``git fetch`` at most once every 6 hours (cached to
    ``~/.spark/.update_check``).  Returns the number of commits behind,
    or ``None`` if the check fails or isn't applicable.
    """
    spark_home = get_spark_home()
    repo_dir = spark_home / "spark-agent"
    cache_file = spark_home / ".update_check"

    # Must be a git repo — fall back to project root for dev installs
    if not (repo_dir / ".git").exists():
        repo_dir = Path(__file__).parent.parent.resolve()
    if not (repo_dir / ".git").exists():
        return None

    # Read cache
    now = time.time()
    try:
        if cache_file.exists():
            cached = json.loads(cache_file.read_text())
            if now - cached.get("ts", 0) < _UPDATE_CHECK_CACHE_SECONDS:
                return cached.get("behind")
    except Exception:
        pass

    # Fetch latest refs (fast — only downloads ref metadata, no files)
    try:
        subprocess.run(
            ["git", "fetch", "origin", "--quiet"],
            capture_output=True,
            timeout=10,
            cwd=str(repo_dir),
        )
    except Exception:
        pass  # Offline or timeout — use stale refs, that's fine

    # Count commits behind
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD..origin/main"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(repo_dir),
        )
        if result.returncode == 0:
            behind = int(result.stdout.strip())
        else:
            behind = None
    except Exception:
        behind = None

    # Write cache
    try:
        cache_file.write_text(json.dumps({"ts": now, "behind": behind}))
    except Exception:
        pass

    return behind


def _resolve_repo_dir() -> Path | None:
    """Return the active Spark git checkout, or None if this isn't a git install."""
    spark_home = get_spark_home()
    repo_dir = spark_home / "spark-agent"
    if not (repo_dir / ".git").exists():
        repo_dir = Path(__file__).parent.parent.resolve()
    return repo_dir if (repo_dir / ".git").exists() else None


def _git_short_hash(repo_dir: Path, rev: str) -> str | None:
    """Resolve a git revision to an 8-character short hash."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=8", rev],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(repo_dir),
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    value = (result.stdout or "").strip()
    return value or None


def get_git_banner_state(repo_dir: Path | None = None) -> dict | None:
    """Return upstream/local git hashes for the startup banner."""
    repo_dir = repo_dir or _resolve_repo_dir()
    if repo_dir is None:
        return None

    upstream = _git_short_hash(repo_dir, "origin/main")
    local = _git_short_hash(repo_dir, "HEAD")
    if not upstream or not local:
        return None

    ahead = 0
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "origin/main..HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(repo_dir),
        )
        if result.returncode == 0:
            ahead = int((result.stdout or "0").strip() or "0")
    except Exception:
        ahead = 0

    return {"upstream": upstream, "local": local, "ahead": max(ahead, 0)}


def format_banner_version_label() -> str:
    """Return the version label shown in the startup banner title."""
    base = f"Spark Agent v{VERSION} ({RELEASE_DATE})"
    state = get_git_banner_state()
    if not state:
        return base

    upstream = state["upstream"]
    local = state["local"]
    ahead = int(state.get("ahead") or 0)

    if ahead <= 0 or upstream == local:
        return f"{base} · upstream {upstream}"

    carried_word = "commit" if ahead == 1 else "commits"
    return f"{base} · upstream {upstream} · local {local} (+{ahead} carried {carried_word})"


# =========================================================================
# Non-blocking update check
# =========================================================================

_update_result: int | None = None
_update_check_done = threading.Event()


def prefetch_update_check():
    """Kick off update check in a background daemon thread."""

    def _run():
        global _update_result
        _update_result = check_for_updates()
        _update_check_done.set()

    t = threading.Thread(target=_run, daemon=True)
    t.start()


def get_update_result(timeout: float = 0.5) -> int | None:
    """Get result of prefetched check. Returns None if not ready."""
    _update_check_done.wait(timeout=timeout)
    return _update_result


# =========================================================================
# Welcome banner
# =========================================================================


def _format_context_length(tokens: int) -> str:
    """Format a token count for display (e.g. 128000 → '128K', 1048576 → '1M')."""
    if tokens >= 1_000_000:
        val = tokens / 1_000_000
        rounded = round(val)
        if abs(val - rounded) < 0.05:
            return f"{rounded}M"
        return f"{val:.1f}M"
    elif tokens >= 1_000:
        val = tokens / 1_000
        rounded = round(val)
        if abs(val - rounded) < 0.05:
            return f"{rounded}K"
        return f"{val:.1f}K"
    return str(tokens)


def _display_toolset_name(toolset_name: str) -> str:
    """Normalize internal/legacy toolset identifiers for banner display."""
    if not toolset_name:
        return "unknown"
    return toolset_name[:-6] if toolset_name.endswith("_tools") else toolset_name


def build_welcome_banner(
    console: Console,
    model: str,
    cwd: str,
    tools: list[dict] = None,
    enabled_toolsets: list[str] = None,
    session_id: str = None,
    get_toolset_for_tool=None,
    context_length: int = None,
):
    """Build and print a minimal startup banner.

    Args:
        console: Rich Console instance.
        model: Current model name.
        cwd: Current working directory.
        tools: List of tool definitions.
        enabled_toolsets: List of enabled toolset names.
        session_id: Session identifier.
        get_toolset_for_tool: Callable to map tool name -> toolset name.
        context_length: Model's context window size in tokens.
    """
    console.print()
