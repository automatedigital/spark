"""TUI prompt, welcome splash, and layout building for SparkCLI (mixin).

Extracted from core/cli/__init__.py (Phase 3). Prompt symbols/fragments, the
welcome logo/splash, and prompt_toolkit layout/keybinding assembly. Combined into
SparkCLI via inheritance.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from prompt_toolkit.filters import Condition
from prompt_toolkit.layout import (
    ConditionalContainer,
    FormattedTextControl,
    Window,
)
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.styles import Style as PTStyle

from core.cli.render import _PT_ANSI


class _TuiMixin:
    def _get_tui_prompt_symbols(self) -> tuple[str, str]:
        """Return ``(normal_prompt, state_suffix)`` for the active skin.

        ``normal_prompt`` is the full ``branding.prompt_symbol``.
        ``state_suffix`` is what special states (sudo/secret/approval/agent)
        should render after their leading icon.

        When a profile is active (not "default"), the profile name is
        prepended to the prompt symbol: ``coder ❯`` instead of ``❯``.
        """
        try:
            from spark_cli.skin_engine import get_active_prompt_symbol

            symbol = get_active_prompt_symbol("❯ ")
        except Exception:
            symbol = "❯ "

        symbol = (symbol or "❯ ").rstrip() + " "

        # Prepend profile name when not default
        try:
            from spark_cli.profiles import get_active_profile_name

            profile = get_active_profile_name()
            if profile not in ("default", "custom"):
                symbol = f"{profile} {symbol}"
        except Exception:
            pass
        stripped = symbol.rstrip()
        if not stripped:
            return "❯ ", "❯ "

        parts = stripped.split()
        candidate = parts[-1] if parts else ""
        arrow_chars = ("❯", ">", "$", "#", "›", "»", "→")
        if any(ch in candidate for ch in arrow_chars):
            return symbol, candidate.rstrip() + " "

        # Icon-only custom prompts should still remain visible in special states.
        return symbol, symbol

    def _audio_level_bar(self) -> str:
        """Return a visual audio level indicator based on current RMS."""
        _LEVEL_BARS = " ▁▂▃▄▅▆▇"
        rec = getattr(self, "_voice_recorder", None)
        if rec is None:
            return ""
        rms = rec.current_rms
        # Normalize RMS (0-32767) to 0-7 index, with log-ish scaling
        # Typical speech RMS is 500-5000, we cap display at ~8000
        level = min(rms, 8000) * 7 // 8000
        return _LEVEL_BARS[level]

    def _get_tui_prompt_fragments(self):
        """Return the prompt_toolkit fragments for the current interactive state."""
        symbol, state_suffix = self._get_tui_prompt_symbols()
        compact = self._use_minimal_tui_chrome(width=self._get_tui_terminal_width())

        def _state_fragment(style: str, icon: str, extra: str = ""):
            if compact:
                text = icon
                if extra:
                    text = f"{text} {extra.strip()}".rstrip()
                return [(style, text + " ")]
            if extra:
                return [(style, f"{icon} {extra} {state_suffix}")]
            return [(style, f"{icon} {state_suffix}")]

        if self._voice_recording:
            bar = self._audio_level_bar()
            return _state_fragment("class:voice-recording", "●", bar)
        if self._voice_processing:
            return _state_fragment("class:voice-processing", "◉")
        if self._sudo_state:
            return _state_fragment("class:sudo-prompt", "🔐")
        if self._secret_state:
            return _state_fragment("class:sudo-prompt", "🔑")
        if self._approval_state:
            return _state_fragment("class:prompt-working", "WARN")
        if self._clarify_freetext:
            return _state_fragment("class:clarify-selected", "✎")
        if self._clarify_state:
            return _state_fragment("class:prompt-working", "?")
        if self._command_running:
            return _state_fragment(
                "class:prompt-working", self._command_spinner_frame()
            )
        if self._voice_mode:
            return _state_fragment("class:voice-prompt", "🎤")
        return [("class:prompt", symbol)]

    def _get_tui_prompt_text(self) -> str:
        """Return the visible prompt text for width calculations."""
        return "".join(text for _, text in self._get_tui_prompt_fragments())

    def _build_tui_style_dict(self) -> dict[str, str]:
        """Layer the active skin's prompt_toolkit colors over the base TUI style."""
        style_dict = dict(getattr(self, "_tui_style_base", {}) or {})
        try:
            from spark_cli.skin_engine import get_prompt_toolkit_style_overrides

            style_dict.update(get_prompt_toolkit_style_overrides())
        except Exception:
            pass
        # Keep hint/runtime helper text muted for readability.
        style_dict["hint"] = "#8B8682 italic"
        style_dict["status-bar-dim"] = "bg:#1a1a2e #8B8682"
        style_dict["status-bar-strong"] = "bg:#1a1a2e #f66914 bold"
        style_dict["status-bar-warn"] = "bg:#1a1a2e #8B8682 bold"
        return style_dict

    def _apply_tui_skin_style(self) -> bool:
        """Refresh prompt_toolkit styling for a running interactive TUI."""
        if not getattr(self, "_app", None) or not getattr(
            self, "_tui_style_base", None
        ):
            return False
        self._app.style = PTStyle.from_dict(self._build_tui_style_dict())
        self._invalidate(min_interval=0.0)
        return True

    def _resolve_welcome_logo_path(self) -> Path:
        """Return the bundled TUI logo image path."""
        return Path(__file__).resolve().parent.parent.parent / "assets" / "icon_small.png"

    def _welcome_logo_size_arg(self) -> str:
        """Return a chafa --size argument for a compact startup logo."""
        try:
            term_cols = max(40, int(shutil.get_terminal_size((120, 40)).columns))
        except Exception:
            term_cols = 120
        return f"{max(4, int(term_cols // 20 * 1.5))}x"

    def _get_welcome_logo_ansi(self) -> str:
        """Render the startup logo via chafa and cache ANSI output."""
        if self._welcome_logo_loaded:
            return self._welcome_logo_ansi or ""

        self._welcome_logo_loaded = True
        self._welcome_logo_ansi = ""

        logo_path = self._resolve_welcome_logo_path()
        if not logo_path.is_file():
            return ""

        try:
            import subprocess
            import re

            result = subprocess.run(
                [
                    "chafa",
                    "--bg=black",
                    "--format=symbols",
                    "--polite=on",
                    f"--size={self._welcome_logo_size_arg()}",
                    str(logo_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                return ""
            rendered = result.stdout or ""
            rendered = re.sub(r"\x1b\[\?25[hl]", "", rendered)
            self._welcome_logo_ansi = rendered.rstrip("\n")
        except Exception:
            return ""

        return self._welcome_logo_ansi or ""

    def _dismiss_welcome_logo(self) -> None:
        """Hide the startup logo after the first submitted prompt."""
        if self._show_welcome_logo:
            try:
                # Clear the splash from the visible terminal before switching to
                # the normal bottom-pinned chat layout. Without this, the prior
                # splash frame can remain in scrollback and visually interfere
                # with the first turn.
                print("\x1b[2J\x1b[H", end="", flush=True)
                _term_lines = shutil.get_terminal_size().lines
                if _term_lines > 2:
                    print("\n" * (_term_lines - 1), end="", flush=True)
            except Exception:
                pass
        self._show_welcome_logo = False

    def _get_welcome_splash_fragments(self):
        """Return startup welcome/tip text fragments for centered splash mode."""
        lines = []
        welcome = (self._welcome_splash_text or "").strip()
        tip = (self._welcome_splash_tip or "").strip()
        skills = (self._welcome_splash_skills or "").strip()
        welcome_style = self._welcome_splash_color or "#FFF8DC"
        tip_style = f"{self._welcome_splash_tip_color or '#B8860B'} italic"
        if welcome:
            lines.append((welcome_style, welcome + "\n"))
        if tip:
            lines.append((tip_style, f"✦ Tip: {tip}\n"))
        if skills:
            lines.append(("#FFD700 bold", f"Activated skills: {skills}\n"))
        return lines

    def _welcome_splash_line_count(self) -> int:
        """Return visible line count for splash text block."""
        return max(1, len(self._get_welcome_splash_fragments()))

    def _welcome_logo_line_count(self) -> int:
        """Return visible line count for rendered logo block."""
        logo = self._get_welcome_logo_ansi()
        if not logo:
            return 0
        return logo.count("\n") + 1

    def _should_show_welcome_splash(self) -> bool:
        """Return whether splash widgets should currently be visible."""
        if not self._show_welcome_logo:
            return False
        if getattr(self, "conversation_history", None):
            return False
        return True

    # --- Protected TUI extension hooks for wrapper CLIs ---

    def _get_extra_tui_widgets(self) -> list:
        """Return extra prompt_toolkit widgets to insert into the TUI layout.

        Wrapper CLIs can override this to inject widgets (e.g. a mini-player,
        overlay menu) into the layout without overriding ``run()``.  Widgets
        are inserted between the spacer and the status bar.
        """
        if not self._should_show_welcome_splash():
            return []

        top_fill = ConditionalContainer(
            Window(content=FormattedTextControl(""), height=Dimension(weight=1)),
            filter=Condition(lambda: self._should_show_welcome_splash()),
        )

        logo_ansi = self._get_welcome_logo_ansi()
        widgets = [top_fill]
        if logo_ansi:
            widgets.append(
                ConditionalContainer(
                    Window(
                        content=FormattedTextControl(lambda: _PT_ANSI(logo_ansi)),
                        height=lambda: max(1, self._welcome_logo_line_count()),
                        wrap_lines=False,
                        dont_extend_height=True,
                    ),
                    filter=Condition(lambda: self._should_show_welcome_splash()),
                )
            )
            widgets.append(
                ConditionalContainer(
                    Window(content=FormattedTextControl(""), height=1),
                    filter=Condition(lambda: self._should_show_welcome_splash()),
                )
            )

        widgets.append(
            ConditionalContainer(
                Window(
                    content=FormattedTextControl(self._get_welcome_splash_fragments),
                    height=lambda: self._welcome_splash_line_count(),
                    wrap_lines=True,
                    dont_extend_height=True,
                ),
                filter=Condition(lambda: self._should_show_welcome_splash()),
            )
        )
        return widgets

    def _register_extra_tui_keybindings(self, kb, *, input_area) -> None:
        """Register extra keybindings on the TUI ``KeyBindings`` object.

        Wrapper CLIs can override this to add keybindings (e.g. transport
        controls, modal shortcuts) without overriding ``run()``.

        Parameters
        ----------
        kb : KeyBindings
            The active keybinding registry for the prompt_toolkit application.
        input_area : TextArea
            The main input widget, for wrappers that need to inspect or
            manipulate user input from a keybinding handler.
        """

    def _build_tui_layout_children(
        self,
        *,
        sudo_widget,
        secret_widget,
        approval_widget,
        clarify_widget,
        model_picker_widget=None,
        spinner_widget=None,
        spacer,
        status_bar,
        input_rule_top,
        image_bar,
        input_area,
        input_rule_bot,
        voice_status_bar,
        completions_menu,
    ) -> list:
        """Assemble the ordered list of children for the root ``HSplit``.

        Wrapper CLIs typically override ``_get_extra_tui_widgets`` instead of
        this method.  Override this only when you need full control over widget
        ordering.
        """
        splash_bottom_fill = ConditionalContainer(
            Window(content=FormattedTextControl(""), height=Dimension(weight=1)),
            filter=Condition(lambda: self._should_show_welcome_splash()),
        )
        splash_input_gap = ConditionalContainer(
            Window(content=FormattedTextControl(""), height=1),
            filter=Condition(lambda: self._should_show_welcome_splash()),
        )

        return [
            item
            for item in [
                Window(height=0),
                sudo_widget,
                secret_widget,
                approval_widget,
                clarify_widget,
                model_picker_widget,
                spinner_widget,
                spacer,
                *self._get_extra_tui_widgets(),
                splash_input_gap,
                status_bar,
                input_rule_top,
                image_bar,
                input_area,
                input_rule_bot,
                voice_status_bar,
                completions_menu,
                splash_bottom_fill,
            ]
            if item is not None
        ]

