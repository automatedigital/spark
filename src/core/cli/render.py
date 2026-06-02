"""ANSI/skin rendering helpers for the Spark CLI.

Extracted from core/cli/__init__.py (Phase 3). Low-level colored-output helpers
that route ANSI through prompt_toolkit's renderer. ``get_active_skin`` is imported
lazily inside functions so these stay free of config-global coupling.
"""

from __future__ import annotations

import logging

from prompt_toolkit import print_formatted_text as _pt_print
from prompt_toolkit.formatted_text import ANSI as _PT_ANSI
from rich.text import Text as _RichText

logger = logging.getLogger(__name__)

_ACCENT_ANSI_DEFAULT = "\033[1;38;2;255;215;0m"  # True-color #FFD700 bold - fallback
_BOLD = "\033[1m"
_RST = "\033[0m"


def _hex_to_ansi(hex_color: str, *, bold: bool = False) -> str:
    """Convert a hex color like '#268bd2' to a true-color ANSI escape."""
    try:
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        prefix = "1;" if bold else ""
        return f"\033[{prefix}38;2;{r};{g};{b}m"
    except (ValueError, IndexError):
        return _ACCENT_ANSI_DEFAULT if bold else "\033[38;2;246;105;20m"


class _SkinAwareAnsi:
    """Lazy ANSI escape that resolves from the skin engine on first use.

    Acts as a string in f-strings and concatenation.  Call ``.reset()`` to
    force re-resolution after a ``/skin`` switch.
    """

    def __init__(
        self, skin_key: str, fallback_hex: str = "#FFD700", *, bold: bool = False
    ):
        self._skin_key = skin_key
        self._fallback_hex = fallback_hex
        self._bold = bold
        self._cached: str | None = None

    def __str__(self) -> str:
        if self._cached is None:
            try:
                from spark_cli.skin_engine import get_active_skin

                self._cached = _hex_to_ansi(
                    get_active_skin().get_color(self._skin_key, self._fallback_hex),
                    bold=self._bold,
                )
            except Exception:
                self._cached = _hex_to_ansi(self._fallback_hex, bold=self._bold)
        return self._cached

    def __add__(self, other: str) -> str:
        return str(self) + other

    def __radd__(self, other: str) -> str:
        return other + str(self)

    def reset(self) -> None:
        """Clear cache so the next access re-reads the skin."""
        self._cached = None


_ACCENT = _SkinAwareAnsi("response_border", "#FFD700", bold=True)
_DIM = _SkinAwareAnsi("banner_dim", "#8B8682")


def _accent_hex() -> str:
    """Return the active skin accent color for legacy CLI output lines."""
    try:
        from spark_cli.skin_engine import get_active_skin

        return get_active_skin().get_color("ui_accent", "#555555")
    except Exception:
        return "#555555"


def _rich_text_from_ansi(text: str) -> _RichText:
    """Safely render assistant/tool output that may contain ANSI escapes.

    Using Rich Text.from_ansi preserves literal bracketed text like
    ``[not markup]`` while still interpreting real ANSI color codes.
    """
    return _RichText.from_ansi(text or "")


def _cprint(text: str):
    """Print ANSI-colored text through prompt_toolkit's native renderer.

    Raw ANSI escapes written via print() are swallowed by patch_stdout's
    StdoutProxy.  Routing through print_formatted_text(ANSI(...)) lets
    prompt_toolkit parse the escapes and render real colors.
    """
    _pt_print(_PT_ANSI(text))
