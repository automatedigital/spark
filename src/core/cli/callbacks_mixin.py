"""Interactive callbacks for SparkCLI (mixin).

Extracted from core/cli/__init__.py (Phase 3). Tool-progress, clarify, sudo,
approval, and secret-capture callbacks driving the TUI's interactive prompts.
Combined into SparkCLI via inheritance.
"""

from __future__ import annotations

import logging
import queue
import shutil
import textwrap
import threading

from core.cli.config_state import CLI_CONFIG
from core.cli.render import _ACCENT, _DIM, _RST, _cprint
from spark_cli.callbacks import prompt_for_secret

logger = logging.getLogger(__name__)


class _CallbacksMixin:
    def _on_tool_gen_start(self, tool_name: str) -> None:
        """Called when the model begins generating tool-call arguments.

        Closes any open streaming boxes (reasoning / response) exactly once,
        then prints a short status line so the user sees activity instead of
        a frozen screen while a large payload (e.g. 45 KB write_file) streams.
        """
        if getattr(self, "_stream_box_opened", False):
            self._flush_stream()
            self._stream_box_opened = False
        self._close_reasoning_box()

        from agent.display import get_tool_emoji

        emoji = get_tool_emoji(tool_name, default="⚡")
        _cprint(f"  ┊ {emoji} preparing {tool_name}…")

    # ====================================================================
    # Tool progress callback (audio cues for voice mode)
    # ====================================================================

    def _on_tool_progress(
        self,
        event_type: str,
        function_name: str = None,
        preview: str = None,
        function_args: dict = None,
        **kwargs,
    ):
        """Called on tool lifecycle events (tool.started, tool.completed, reasoning.available, etc.).

        Updates the TUI spinner widget so the user can see what the agent
        is doing during tool execution (fills the gap between thinking
        spinner and next response).  Also plays audio cue in voice mode.

        On tool.started, records a monotonic timestamp so get_spinner_text()
        can show a live elapsed timer (the TUI poll loop already invalidates
        every ~0.15s, so the counter updates automatically).

        When tool_progress_mode is "all" or "new", also prints a persistent
        stacked line to scrollback on tool.completed so users can see the
        full history of tool calls (not just the current one in the spinner).
        """
        if event_type == "tool.completed":
            import time as _time

            self._tool_start_time = 0.0
            # Print stacked scrollback line for "all" / "new" modes
            if function_name and self.tool_progress_mode in ("all", "new"):
                duration = kwargs.get("duration", 0.0)
                is_error = kwargs.get("is_error", False)
                # Pop stored args from tool.started for this function
                stored = self._pending_tool_info.get(function_name)
                stored_args = stored.pop(0) if stored else {}
                if stored is not None and not stored:
                    del self._pending_tool_info[function_name]
                # "new" mode: skip consecutive repeats of the same tool
                if (
                    self.tool_progress_mode == "new"
                    and function_name == self._last_scrollback_tool
                ):
                    self._invalidate()
                    return
                self._last_scrollback_tool = function_name
                try:
                    from agent.display import get_cute_tool_message

                    line = get_cute_tool_message(function_name, stored_args, duration)
                    if is_error:
                        line = f"{line} [error]"
                    _cprint(f"  {line}")
                except Exception:
                    pass
            self._invalidate()
            return
        if event_type != "tool.started":
            return
        if function_name and not function_name.startswith("_"):
            import time as _time
            from agent.display import get_tool_emoji

            emoji = get_tool_emoji(function_name)
            label = preview or function_name
            from agent.display import get_tool_preview_max_len

            _pl = get_tool_preview_max_len()
            if _pl > 0 and len(label) > _pl:
                label = label[: _pl - 3] + "..."
            self._spinner_text = f"{emoji} {label}"
            self._tool_start_time = _time.monotonic()
            # Store args for stacked scrollback line on completion
            self._pending_tool_info.setdefault(function_name, []).append(
                function_args if function_args is not None else {}
            )
            self._invalidate()

        if not self._voice_mode:
            return
        if not function_name or function_name.startswith("_"):
            return
        try:
            from tools.voice_mode import play_beep

            threading.Thread(
                target=play_beep,
                kwargs={"frequency": 1200, "duration": 0.06, "count": 1},
                daemon=True,
            ).start()
        except Exception:
            pass

    def _on_tool_start(
        self, tool_call_id: str, function_name: str, function_args: dict
    ):
        """Capture local before-state for write-capable tools."""
        try:
            from agent.display import capture_local_edit_snapshot

            snapshot = capture_local_edit_snapshot(function_name, function_args)
            if snapshot is not None:
                self._pending_edit_snapshots[tool_call_id] = snapshot
        except Exception:
            logger.debug(
                "Edit snapshot capture failed for %s", function_name, exc_info=True
            )

    def _on_tool_complete(
        self,
        tool_call_id: str,
        function_name: str,
        function_args: dict,
        function_result: str,
    ):
        """Render file edits with inline diff after write-capable tools complete."""
        snapshot = self._pending_edit_snapshots.pop(tool_call_id, None)
        try:
            from agent.display import render_edit_diff_with_delta

            render_edit_diff_with_delta(
                function_name,
                function_result,
                function_args=function_args,
                snapshot=snapshot,
                print_fn=_cprint,
            )
        except Exception:
            logger.debug(
                "Edit diff preview failed for %s", function_name, exc_info=True
            )

    # ====================================================================
    # Voice mode methods
    # ====================================================================

    def _clarify_callback(self, question, choices):
        """
        Platform callback for the clarify tool. Called from the agent thread.

        Sets up the interactive selection UI (or freetext prompt for open-ended
        questions), then blocks until the user responds via the prompt_toolkit
        key bindings.  If no response arrives within the configured timeout the
        question is dismissed and the agent is told to decide on its own.
        """
        import time as _time

        timeout = CLI_CONFIG.get("clarify", {}).get("timeout", 120)
        response_queue = queue.Queue()
        is_open_ended = not choices

        self._clarify_state = {
            "question": question,
            "choices": choices if not is_open_ended else [],
            "selected": 0,
            "response_queue": response_queue,
        }
        self._clarify_deadline = _time.monotonic() + timeout
        # Open-ended questions skip straight to freetext input
        self._clarify_freetext = is_open_ended

        # Trigger prompt_toolkit repaint from this (non-main) thread
        self._invalidate()

        # Poll for the user's response.  The countdown in the hint line
        # updates on each invalidate - but frequent repaints cause visible
        # flicker in some terminals (Kitty, ghostty).  We only refresh the
        # countdown every 5 s; selection changes (↑/↓) trigger instant
        # Poll for the user's response.  The countdown in the hint line
        # updates on each invalidate - but frequent repaints cause visible
        # flicker in some terminals (Kitty, ghostty).  We only refresh the
        # countdown every 5 s; selection changes (↑/↓) trigger instant
        # repaints via the key bindings.
        _last_countdown_refresh = _time.monotonic()
        while True:
            try:
                result = response_queue.get(timeout=1)
                self._clarify_deadline = 0
                return result
            except queue.Empty:
                remaining = self._clarify_deadline - _time.monotonic()
                if remaining <= 0:
                    break
                # Only repaint every 5 s for the countdown - avoids flicker
                now = _time.monotonic()
                if now - _last_countdown_refresh >= 5.0:
                    _last_countdown_refresh = now
                    self._invalidate()
                if now - _last_countdown_refresh >= 5.0:
                    _last_countdown_refresh = now
                    self._invalidate()

        # Timed out - tear down the UI and let the agent decide
        self._clarify_state = None
        self._clarify_freetext = False
        self._clarify_deadline = 0
        self._invalidate()
        _cprint(
            f"\n{_DIM}(clarify timed out after {timeout}s - agent will decide){_RST}"
        )
        return (
            "The user did not provide a response within the time limit. "
            "Use your best judgement to make the choice and proceed."
        )

    def _sudo_password_callback(self) -> str:
        """
        Prompt for sudo password through the prompt_toolkit UI.

        Called from the agent thread when a sudo command is encountered.
        Uses the same clarify-style mechanism: sets UI state, waits on a
        queue for the user's response via the Enter key binding.
        """
        import time as _time

        timeout = 45
        response_queue = queue.Queue()

        self._capture_modal_input_snapshot()
        self._sudo_state = {
            "response_queue": response_queue,
        }
        self._sudo_deadline = _time.monotonic() + timeout

        self._invalidate()

        while True:
            try:
                result = response_queue.get(timeout=1)
                self._sudo_state = None
                self._sudo_deadline = 0
                self._restore_modal_input_snapshot()
                self._invalidate()
                if result:
                    _cprint(
                        f"\n{_DIM}  OK: Password received (cached for session){_RST}"
                    )
                else:
                    _cprint(f"\n{_DIM}  ⏭ Skipped{_RST}")
                return result
            except queue.Empty:
                remaining = self._sudo_deadline - _time.monotonic()
                if remaining <= 0:
                    break
                self._invalidate()

        self._sudo_state = None
        self._sudo_deadline = 0
        self._restore_modal_input_snapshot()
        self._invalidate()
        _cprint(f"\n{_DIM}  ⏱ Timeout - continuing without sudo{_RST}")
        return ""

    def _approval_callback(
        self, command: str, description: str, *, allow_permanent: bool = True
    ) -> str:
        """
        Prompt for dangerous command approval through the prompt_toolkit UI.

        Called from the agent thread. Shows a selection UI similar to clarify
        with choices: once / session / always / deny. When allow_permanent
        is False (tirith warnings present), the 'always' option is hidden.
        Long commands also get a 'view' option so the full command can be
        expanded before deciding.

        Uses _approval_lock to serialize concurrent requests (e.g. from
        parallel delegation subtasks) so each prompt gets its own turn
        and the shared _approval_state / _approval_deadline aren't clobbered.
        """
        import time as _time

        with self._approval_lock:
            timeout = 60
            response_queue = queue.Queue()

            self._approval_state = {
                "command": command,
                "description": description,
                "choices": self._approval_choices(
                    command, allow_permanent=allow_permanent
                ),
                "selected": 0,
                "response_queue": response_queue,
            }
            self._approval_deadline = _time.monotonic() + timeout

            self._invalidate()

            _last_countdown_refresh = _time.monotonic()
            while True:
                try:
                    result = response_queue.get(timeout=1)
                    self._approval_state = None
                    self._approval_deadline = 0
                    self._invalidate()
                    return result
                except queue.Empty:
                    remaining = self._approval_deadline - _time.monotonic()
                    if remaining <= 0:
                        break
                    now = _time.monotonic()
                    if now - _last_countdown_refresh >= 5.0:
                        _last_countdown_refresh = now
                        self._invalidate()

            self._approval_state = None
            self._approval_deadline = 0
            self._invalidate()
            _cprint(f"\n{_DIM}  ⏱ Timeout - denying command{_RST}")
            return "deny"

    def _approval_choices(
        self, command: str, *, allow_permanent: bool = True
    ) -> list[str]:
        """Return approval choices for a dangerous command prompt."""
        choices = (
            ["once", "session", "always", "deny"]
            if allow_permanent
            else ["once", "session", "deny"]
        )
        if len(command) > 70:
            choices.append("view")
        return choices

    def _handle_approval_selection(self) -> None:
        """Process the currently selected dangerous-command approval choice."""
        state = self._approval_state
        if not state:
            return

        selected = state.get("selected", 0)
        choices = state.get("choices") or []
        if not (0 <= selected < len(choices)):
            return

        chosen = choices[selected]
        if chosen == "view":
            state["show_full"] = True
            state["choices"] = [choice for choice in choices if choice != "view"]
            if state["selected"] >= len(state["choices"]):
                state["selected"] = max(0, len(state["choices"]) - 1)
            self._invalidate()
            return

        state["response_queue"].put(chosen)
        self._approval_state = None
        self._invalidate()

    def _get_approval_display_fragments(self):
        """Render the dangerous-command approval panel for the prompt_toolkit UI."""
        state = self._approval_state
        if not state:
            return []

        def _panel_box_width(
            title_text: str,
            content_lines: list[str],
            min_width: int = 46,
            max_width: int = 76,
        ) -> int:
            term_cols = shutil.get_terminal_size((100, 20)).columns
            longest = max(
                [len(title_text)]
                + [len(line) for line in content_lines]
                + [min_width - 4]
            )
            inner = min(
                max(longest + 4, min_width - 2), max_width - 2, max(24, term_cols - 6)
            )
            return inner + 2

        def _wrap_panel_text(
            text: str, width: int, subsequent_indent: str = ""
        ) -> list[str]:
            wrapped = textwrap.wrap(
                text,
                width=max(8, width),
                replace_whitespace=False,
                drop_whitespace=False,
                subsequent_indent=subsequent_indent,
            )
            return wrapped or [""]

        def _append_panel_line(
            lines, border_style: str, content_style: str, text: str, box_width: int
        ) -> None:
            inner_width = max(0, box_width - 2)
            lines.append((border_style, "| "))
            lines.append((content_style, text.ljust(inner_width)))
            lines.append((border_style, " |\n"))

        def _append_blank_panel_line(lines, border_style: str, box_width: int) -> None:
            lines.append((border_style, "|" + (" " * box_width) + "|\n"))

        command = state["command"]
        description = state["description"]
        choices = state["choices"]
        selected = state.get("selected", 0)
        show_full = state.get("show_full", False)

        title = "WARN  Dangerous Command"
        cmd_display = (
            command if show_full or len(command) <= 70 else command[:70] + "..."
        )
        choice_labels = {
            "once": "Allow once",
            "session": "Allow for this session",
            "always": "Add to permanent allowlist",
            "deny": "Deny",
            "view": "Show full command",
        }

        preview_lines = _wrap_panel_text(description, 60)
        preview_lines.extend(_wrap_panel_text(cmd_display, 60))
        for i, choice in enumerate(choices):
            prefix = "❯ " if i == selected else "  "
            preview_lines.extend(
                _wrap_panel_text(
                    f"{prefix}{choice_labels.get(choice, choice)}",
                    60,
                    subsequent_indent="  ",
                )
            )

        box_width = _panel_box_width(title, preview_lines)
        inner_text_width = max(8, box_width - 2)

        lines = []
        lines.append(("class:approval-border", "+" + ("-" * box_width) + "+\n"))
        _append_panel_line(
            lines, "class:approval-border", "class:approval-title", title, box_width
        )
        _append_blank_panel_line(lines, "class:approval-border", box_width)
        for wrapped in _wrap_panel_text(description, inner_text_width):
            _append_panel_line(
                lines,
                "class:approval-border",
                "class:approval-desc",
                wrapped,
                box_width,
            )
        for wrapped in _wrap_panel_text(cmd_display, inner_text_width):
            _append_panel_line(
                lines, "class:approval-border", "class:approval-cmd", wrapped, box_width
            )
        _append_blank_panel_line(lines, "class:approval-border", box_width)
        for i, choice in enumerate(choices):
            label = choice_labels.get(choice, choice)
            style = (
                "class:approval-selected" if i == selected else "class:approval-choice"
            )
            prefix = "❯ " if i == selected else "  "
            for wrapped in _wrap_panel_text(
                f"{prefix}{label}", inner_text_width, subsequent_indent="  "
            ):
                _append_panel_line(
                    lines, "class:approval-border", style, wrapped, box_width
                )
        _append_blank_panel_line(lines, "class:approval-border", box_width)
        lines.append(("class:approval-border", "+" + ("-" * box_width) + "+\n"))
        return lines

    def _secret_capture_callback(
        self, var_name: str, prompt: str, metadata=None
    ) -> dict:
        return prompt_for_secret(self, var_name, prompt, metadata)

    def _capture_modal_input_snapshot(self) -> None:
        """Temporarily clear the input buffer and save the user's in-progress draft."""
        if self._modal_input_snapshot is not None or not getattr(self, "_app", None):
            return
        try:
            buf = self._app.current_buffer
            self._modal_input_snapshot = {
                "text": buf.text,
                "cursor_position": buf.cursor_position,
            }
            buf.reset()
        except Exception:
            self._modal_input_snapshot = None

    def _restore_modal_input_snapshot(self) -> None:
        """Restore any draft text that was present before a modal prompt opened."""
        snapshot = self._modal_input_snapshot
        self._modal_input_snapshot = None
        if not snapshot or not getattr(self, "_app", None):
            return
        try:
            buf = self._app.current_buffer
            buf.text = snapshot.get("text", "")
            buf.cursor_position = min(snapshot.get("cursor_position", 0), len(buf.text))
        except Exception:
            pass

    def _submit_secret_response(self, value: str) -> None:
        if not self._secret_state:
            return
        self._secret_state["response_queue"].put(value)
        self._secret_state = None
        self._secret_deadline = 0
        self._invalidate()

    def _cancel_secret_capture(self) -> None:
        self._submit_secret_response("")

    def _clear_secret_input_buffer(self) -> None:
        if getattr(self, "_app", None):
            try:
                self._app.current_buffer.reset()
            except Exception:
                pass

