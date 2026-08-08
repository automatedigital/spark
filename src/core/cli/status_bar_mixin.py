"""Status-bar and TUI-chrome rendering for SparkCLI (mixin).

Extracted from core/cli/__init__.py (Phase 3). Builds the bottom status bar,
context meter, and TUI layout geometry. Combined into SparkCLI via inheritance.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from typing import Any

from agent.usage_pricing import format_duration_compact, format_token_count_compact
from spark_cli.banner import _format_context_length


class _StatusBarMixin:
    def _invalidate(self, min_interval: float = 0.25) -> None:
        """Throttled UI repaint - prevents terminal blinking on slow/SSH connections."""
        import time as _time

        now = _time.monotonic()
        if (
            hasattr(self, "_app")
            and self._app
            and (now - self._last_invalidate) >= min_interval
        ):
            self._last_invalidate = now
            self._app.invalidate()

    def _thinking_level_label(self) -> str:
        """Short reasoning-effort label for the status bar (set via /think|/reasoning)."""
        rc = getattr(self, "reasoning_config", None)
        if not rc:
            return "med"
        if rc.get("enabled") is False:
            return "off"
        effort = str(rc.get("effort", "medium"))
        return {"medium": "med", "minimal": "min"}.get(effort, effort)

    def _status_bar_context_style(self, percent_used: int | None) -> str:
        if percent_used is None:
            return "class:status-bar-dim"
        if percent_used >= 95:
            return "class:status-bar-critical"
        if percent_used > 80:
            return "class:status-bar-bad"
        if percent_used >= 50:
            return "class:status-bar-warn"
        return "class:status-bar-good"

    def _build_context_bar(self, percent_used: int | None, width: int = 10) -> str:
        safe_percent = max(0, min(100, percent_used or 0))
        filled = round((safe_percent / 100) * width)
        return f"[{('#' * filled) + ('-' * max(0, width - filled))}]"

    def _get_status_bar_snapshot(self) -> dict[str, Any]:
        # Prefer the agent's model name - it updates on fallback.
        # self.model reflects the originally configured model and never
        # changes mid-session, so the TUI would show a stale name after
        # _try_activate_fallback() switches provider/model.
        agent = getattr(self, "agent", None)
        model_name = getattr(agent, "model", None) or self.model or "unknown"
        model_short = model_name.split("/")[-1] if "/" in model_name else model_name
        if model_short.endswith(".gguf"):
            model_short = model_short[:-5]
        if len(model_short) > 26:
            model_short = f"{model_short[:23]}..."

        elapsed_seconds = max(
            0.0, (datetime.now() - self.session_start).total_seconds()
        )
        snapshot = {
            "model_name": model_name,
            "model_short": model_short,
            "duration": format_duration_compact(elapsed_seconds),
            "context_tokens": 0,
            "context_length": None,
            "context_percent": None,
            "session_input_tokens": 0,
            "session_output_tokens": 0,
            "session_cache_read_tokens": 0,
            "session_cache_write_tokens": 0,
            "session_prompt_tokens": 0,
            "session_completion_tokens": 0,
            "session_total_tokens": 0,
            "session_api_calls": 0,
            "compressions": 0,
            "estimated_cost_usd": 0.0,
        }

        if not agent:
            return snapshot

        snapshot["session_input_tokens"] = (
            getattr(agent, "session_input_tokens", 0) or 0
        )
        snapshot["session_output_tokens"] = (
            getattr(agent, "session_output_tokens", 0) or 0
        )
        snapshot["session_cache_read_tokens"] = (
            getattr(agent, "session_cache_read_tokens", 0) or 0
        )
        snapshot["session_cache_write_tokens"] = (
            getattr(agent, "session_cache_write_tokens", 0) or 0
        )
        snapshot["session_prompt_tokens"] = (
            getattr(agent, "session_prompt_tokens", 0) or 0
        )
        snapshot["session_completion_tokens"] = (
            getattr(agent, "session_completion_tokens", 0) or 0
        )
        snapshot["session_total_tokens"] = (
            getattr(agent, "session_total_tokens", 0) or 0
        )
        snapshot["session_api_calls"] = getattr(agent, "session_api_calls", 0) or 0
        snapshot["estimated_cost_usd"] = (
            getattr(agent, "session_estimated_cost_usd", 0.0) or 0.0
        )

        compressor = getattr(agent, "context_compressor", None)
        if compressor:
            context_tokens = getattr(compressor, "last_prompt_tokens", 0) or 0
            context_length = getattr(compressor, "context_length", 0) or 0
            snapshot["context_tokens"] = context_tokens
            snapshot["context_length"] = context_length or None
            snapshot["compressions"] = getattr(compressor, "compression_count", 0) or 0
            if context_length:
                snapshot["context_percent"] = max(
                    0, min(100, round((context_tokens / context_length) * 100))
                )

        return snapshot

    @staticmethod
    def _status_bar_display_width(text: str) -> int:
        """Return terminal cell width for status-bar text.

        len() is not enough for prompt_toolkit layout decisions because some
        glyphs can render wider than one Python codepoint. Keeping the status
        bar within the real display width prevents it from wrapping onto a
        second line and leaving behind duplicate rows.
        """
        try:
            from prompt_toolkit.utils import get_cwidth

            return get_cwidth(text or "")
        except Exception:
            return len(text or "")

    @classmethod
    def _trim_status_bar_text(cls, text: str, max_width: int) -> str:
        """Trim status-bar text to a single terminal row."""
        if max_width <= 0:
            return ""
        try:
            from prompt_toolkit.utils import get_cwidth
        except Exception:
            get_cwidth = None

        if cls._status_bar_display_width(text) <= max_width:
            return text

        ellipsis = "..."
        ellipsis_width = cls._status_bar_display_width(ellipsis)
        if max_width <= ellipsis_width:
            return ellipsis[:max_width]

        out = []
        width = 0
        for ch in text:
            ch_width = get_cwidth(ch) if get_cwidth else len(ch)
            if width + ch_width + ellipsis_width > max_width:
                break
            out.append(ch)
            width += ch_width
        return "".join(out).rstrip() + ellipsis

    @staticmethod
    def _get_tui_terminal_width(default: tuple[int, int] = (80, 24)) -> int:
        """Return the live prompt_toolkit width, falling back to ``shutil``.

        The TUI layout can be narrower than ``shutil.get_terminal_size()`` reports,
        especially on Termux/mobile shells, so prefer prompt_toolkit's width whenever
        an app is active.
        """
        try:
            from prompt_toolkit.application import get_app

            return get_app().output.get_size().columns
        except Exception:
            return shutil.get_terminal_size(default).columns

    def _use_minimal_tui_chrome(self, width: int | None = None) -> bool:
        """Hide low-value chrome on narrow/mobile terminals to preserve rows."""
        if width is None:
            width = self._get_tui_terminal_width()
        return width < 64

    def _tui_input_rule_height(self, position: str, width: int | None = None) -> int:
        """Return the visible height for the top/bottom input separator rules."""
        if position not in {"top", "bottom"}:
            raise ValueError(f"Unknown input rule position: {position}")
        if position == "top":
            return 1
        return 0 if self._use_minimal_tui_chrome(width=width) else 1

    def _agent_spacer_height(self, width: int | None = None) -> int:
        """Return the spacer height shown above the status bar while the agent runs."""
        if not getattr(self, "_agent_running", False):
            return 0
        return 0 if self._use_minimal_tui_chrome(width=width) else 1

    def _spinner_widget_height(self, width: int | None = None) -> int:
        """Return the visible height for the spinner/status text line above the status bar."""
        if not getattr(self, "_spinner_text", ""):
            return 0
        return 0 if self._use_minimal_tui_chrome(width=width) else 1

    def _get_voice_status_fragments(self, width: int | None = None):
        """Return the voice status bar fragments for the interactive TUI."""
        width = width or self._get_tui_terminal_width()
        compact = self._use_minimal_tui_chrome(width=width)
        if self._voice_recording:
            if compact:
                return [("class:voice-status-recording", " REC ")]
            return [("class:voice-status-recording", " REC  Ctrl+B to stop ")]
        if self._voice_processing:
            if compact:
                return [("class:voice-status", " STT ")]
            return [("class:voice-status", " Transcribing... ")]
        if compact:
            return [("class:voice-status", " Voice Ctrl+B ")]
        tts = " | TTS on" if self._voice_tts else ""
        cont = " | Continuous" if self._voice_continuous else ""
        return [("class:voice-status", f" Voice mode{tts}{cont}  -  Ctrl+B to record ")]

    def _build_status_bar_text(self, width: int | None = None) -> str:
        """Return a compact one-line session status string for the TUI footer."""
        try:
            snapshot = self._get_status_bar_snapshot()
            if width is None:
                width = self._get_tui_terminal_width()
            percent = snapshot["context_percent"]
            percent_label = f"{percent}%" if percent is not None else "--"
            duration_label = snapshot["duration"]

            if width < 52:
                text = f"S {snapshot['model_short']} - {duration_label}"
                return self._trim_status_bar_text(text, width)
            if width < 76:
                parts = [f"S {snapshot['model_short']}", percent_label]
                parts.append(duration_label)
                return self._trim_status_bar_text(" - ".join(parts), width)

            if snapshot["context_length"]:
                ctx_total = _format_context_length(snapshot["context_length"])
                ctx_used = format_token_count_compact(snapshot["context_tokens"])
                context_label = f"{ctx_used}/{ctx_total}"
            else:
                context_label = "ctx --"

            parts = [f"S {snapshot['model_short']}", context_label, percent_label]
            parts.append(duration_label)
            return self._trim_status_bar_text(" | ".join(parts), width)
        except Exception:
            return f"S {self.model if getattr(self, 'model', None) else 'Spark'}"

    def _get_status_bar_fragments(self):
        if not self._status_bar_visible or getattr(self, "_model_picker_state", None):
            return []
        try:
            snapshot = self._get_status_bar_snapshot()
            # Use prompt_toolkit's own terminal width when running inside the
            # TUI - shutil.get_terminal_size() can return stale or fallback
            # values (especially on SSH) that differ from what prompt_toolkit
            # actually renders, causing the fragments to overflow to a second
            # line and produce duplicated status bar rows over long sessions.
            width = self._get_tui_terminal_width()
            duration_label = snapshot["duration"]

            if width < 52:
                frags = [
                    ("class:status-bar", " S "),
                    ("class:status-bar-strong", snapshot["model_short"]),
                    ("class:status-bar-dim", " - "),
                    ("class:status-bar-dim", duration_label),
                    ("class:status-bar", " "),
                ]
            else:
                percent = snapshot["context_percent"]
                percent_label = f"{percent}%" if percent is not None else "--"
                if width < 76:
                    frags = [
                        ("class:status-bar", " S "),
                        ("class:status-bar-strong", snapshot["model_short"]),
                        ("class:status-bar-dim", " - "),
                        (self._status_bar_context_style(percent), percent_label),
                        ("class:status-bar-dim", " - "),
                        ("class:status-bar-dim", duration_label),
                        ("class:status-bar", " "),
                    ]
                else:
                    if snapshot["context_length"]:
                        ctx_total = _format_context_length(snapshot["context_length"])
                        ctx_used = format_token_count_compact(
                            snapshot["context_tokens"]
                        )
                        context_label = f"{ctx_used}/{ctx_total}"
                    else:
                        context_label = "ctx --"

                    bar_style = self._status_bar_context_style(percent)
                    frags = [
                        ("class:status-bar", " S "),
                        ("class:status-bar-strong", snapshot["model_short"]),
                        ("class:status-bar-dim", " | "),
                        ("class:status-bar-dim", context_label),
                        ("class:status-bar-dim", " | "),
                        (bar_style, self._build_context_bar(percent)),
                        ("class:status-bar-dim", " "),
                        (bar_style, percent_label),
                        ("class:status-bar-dim", " | "),
                        ("class:status-bar-dim", duration_label),
                    ]
                    # Wider terminals also get thinking level + token/cost totals.
                    if width >= 96:
                        total_tokens = snapshot["session_total_tokens"]
                        cost = snapshot["estimated_cost_usd"]
                        frags += [
                            ("class:status-bar-dim", " | "),
                            ("class:status-bar-dim", f"⚲{self._thinking_level_label()}"),
                            ("class:status-bar-dim", " | "),
                            ("class:status-bar-dim", format_token_count_compact(total_tokens)),
                        ]
                        if cost and cost > 0:
                            frags += [
                                ("class:status-bar-dim", " "),
                                ("class:status-bar-dim", f"${cost:.2f}"),
                            ]
                    frags.append(("class:status-bar", " "))

            total_width = sum(self._status_bar_display_width(text) for _, text in frags)
            if total_width > width:
                plain_text = "".join(text for _, text in frags)
                trimmed = self._trim_status_bar_text(plain_text, width)
                return [("class:status-bar", trimmed)]
            return frags
        except Exception:
            return [("class:status-bar", f" {self._build_status_bar_text()} ")]

