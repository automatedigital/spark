"""Banner, session resume, and session-op methods for SparkCLI (mixin).

Extracted from core/cli/__init__.py (Phase 3). show_banner, resume preload/display,
save/retry/undo, and gateway-status display. Combined into SparkCLI via inheritance.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime

from core.cli import _build_compact_banner  # defined before this import; no cycle
from core.cli.render import _accent_hex
from core.model_tools import get_tool_definitions
from core.spark_constants import display_spark_home, get_spark_home
from spark_cli.banner import build_welcome_banner


class _SessionOpsMixin:
    def _handle_export_command(self, cmd: str):
        """Handle /export [session_id] [--publish] - write a redacted session export.

        With --publish, opt-in to upload the redacted file to a public GitHub Gist.
        """
        from core.cli.render import _DIM, _RST, _cprint
        from spark_cli.session_export import export_session_redacted, publish_export

        tokens = cmd.strip().split()[1:]  # drop "/export"
        publish = "--publish" in tokens
        positional = [t for t in tokens if not t.startswith("--")]
        session_id = positional[0] if positional else getattr(self, "session_id", None)
        if not session_id:
            _cprint(f"  {_DIM}No active session to export.{_RST}")
            return
        result = export_session_redacted(session_id, db=getattr(self, "_session_db", None))
        if result.get("error"):
            _cprint(f"  {_DIM}{result['error']}{_RST}")
            return
        _cprint(
            f"  Exported {result['messages']} messages (secrets redacted) to:\n"
            f"  {_DIM}{result['path']}{_RST}"
        )
        if publish:
            _cprint(f"  {_DIM}Publishing to a public Gist…{_RST}")
            pub = publish_export(result["path"])
            if pub.get("ok"):
                _cprint(f"  Published: {_DIM}{pub['url']}{_RST}")
            else:
                _cprint(f"  {_DIM}{pub.get('error', 'publish failed')}{_RST}")

    def show_banner(self):
        """Display the welcome banner in Claude Code style."""
        self.console.clear()

        # Get context length for display before branching so it remains
        # available to the low-context warning logic in compact mode too.
        ctx_len = None
        if (
            hasattr(self, "agent")
            and self.agent
            and hasattr(self.agent, "context_compressor")
        ):
            ctx_len = self.agent.context_compressor.context_length

        # Auto-compact for narrow terminals - the full banner with caduceus
        # + tool list needs ~80 columns minimum to render without wrapping.
        term_width = shutil.get_terminal_size().columns
        use_compact = self.compact or term_width < 80

        if use_compact:
            self.console.print(_build_compact_banner())
            self._show_status()
        else:
            # Get tools for display
            tools = get_tool_definitions(
                enabled_toolsets=self.enabled_toolsets, quiet_mode=True
            )

            # Get terminal working directory (where commands will execute)
            cwd = os.getenv("TERMINAL_CWD", os.getcwd())

            # Build and display the banner
            build_welcome_banner(
                console=self.console,
                model=self.model,
                cwd=cwd,
                tools=tools,
                enabled_toolsets=self.enabled_toolsets,
                session_id=self.session_id,
                context_length=ctx_len,
            )

        # Show tool availability warnings if any tools are disabled
        self._show_tool_availability_warnings()

        # Warn about very low context lengths (common with local servers)
        if ctx_len and ctx_len <= 8192:
            self.console.print()
            self.console.print(
                f"[yellow]WARN  Context length is only {ctx_len:,} tokens - "
                f"this is likely too low for agent use with tools.[/]"
            )
            self.console.print(
                "[dim]   Spark needs 16k–32k minimum. Tool schemas + system prompt alone use ~4k–8k.[/]"
            )
            base_url = getattr(self, "base_url", "") or ""
            if "11434" in base_url or "ollama" in base_url.lower():
                self.console.print(
                    "[dim]   Ollama fix: OLLAMA_CONTEXT_LENGTH=32768 ollama serve[/]"
                )
            elif "1234" in base_url:
                self.console.print(
                    "[dim]   LM Studio fix: Set context length in model settings → reload model[/]"
                )
            else:
                self.console.print(
                    "[dim]   Fix: Set model.context_length in config.yaml, or increase your server's context setting[/]"
                )

        self.console.print()

    def _preload_resumed_session(self) -> bool:
        """Load a resumed session's history from the DB early (before first chat).

        Called from run() so the conversation history is available for display
        before the user sends their first message.  Sets
        ``self.conversation_history`` and prints the one-liner status.  Returns
        True if history was loaded, False otherwise.

        The corresponding block in ``_init_agent()`` checks whether history is
        already populated and skips the DB round-trip.
        """
        if not self._resumed or not self._session_db:
            return False

        session_meta = self._session_db.get_session(self.session_id)
        if not session_meta:
            self.console.print(f"[bold red]Session not found: {self.session_id}[/]")
            self.console.print(
                "[dim]Use a session ID from a previous CLI run "
                "(spark sessions list).[/]"
            )
            return False

        restored = self._session_db.get_messages_as_conversation(self.session_id)
        if restored:
            restored = [m for m in restored if m.get("role") != "session_meta"]
            self.conversation_history = restored
            msg_count = len([m for m in restored if m.get("role") == "user"])
            title_part = ""
            if session_meta.get("title"):
                title_part = f' "{session_meta["title"]}"'
            accent_color = _accent_hex()
            self.console.print(
                f"[{accent_color}]↻ Resumed session [bold]{self.session_id}[/bold]"
                f"{title_part} "
                f"({msg_count} user message{'s' if msg_count != 1 else ''}, "
                f"{len(restored)} total messages)[/]"
            )
        else:
            accent_color = _accent_hex()
            self.console.print(
                f"[{accent_color}]Session {self.session_id} found but has no "
                f"messages. Starting fresh.[/]"
            )
            return False

        # Re-open the session (clear ended_at so it's active again)
        try:
            self._session_db._conn.execute(
                "UPDATE sessions SET ended_at = NULL, end_reason = NULL WHERE id = ?",
                (self.session_id,),
            )
            self._session_db._conn.commit()
        except Exception:
            pass

        return True

    def _display_resumed_history(self):
        """Render a compact recap of previous conversation messages.

        Uses Rich markup with dim/muted styling so the recap is visually
        distinct from the active conversation.  Caps the display at the
        last ``MAX_DISPLAY_EXCHANGES`` user/assistant exchanges and shows
        an indicator for earlier hidden messages.
        """
        if not self.conversation_history:
            return

        # Check config: resume_display setting
        if self.resume_display == "minimal":
            return

        MAX_DISPLAY_EXCHANGES = 10  # max user+assistant pairs to show
        MAX_USER_LEN = 300  # truncate user messages
        MAX_ASST_LEN = 200  # truncate assistant text
        MAX_ASST_LINES = 3  # max lines of assistant text

        def _strip_reasoning(text: str) -> str:
            """Remove <REASONING_SCRATCHPAD>...</REASONING_SCRATCHPAD> blocks
            from displayed text (reasoning model internal thoughts)."""
            import re

            cleaned = re.sub(
                r"<REASONING_SCRATCHPAD>.*?</REASONING_SCRATCHPAD>\s*",
                "",
                text,
                flags=re.DOTALL,
            )
            # Also strip unclosed reasoning tags at the end
            cleaned = re.sub(
                r"<REASONING_SCRATCHPAD>.*$",
                "",
                cleaned,
                flags=re.DOTALL,
            )
            return cleaned.strip()

        # Collect displayable entries (skip system, tool-result messages)
        entries = []  # list of (role, display_text)
        _last_asst_idx = None  # index of last assistant entry
        _last_asst_full = None  # un-truncated display text for last assistant
        for msg in self.conversation_history:
            role = msg.get("role", "")
            content = msg.get("content")
            tool_calls = msg.get("tool_calls") or []

            if role == "system":
                continue
            if role == "tool":
                continue

            if role == "user":
                text = "" if content is None else str(content)
                # Handle multimodal content (list of dicts)
                if isinstance(content, list):
                    parts = []
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            parts.append(part.get("text", ""))
                        elif isinstance(part, dict) and part.get("type") == "image_url":
                            parts.append("[image]")
                    text = " ".join(parts)
                if len(text) > MAX_USER_LEN:
                    text = text[:MAX_USER_LEN] + "..."
                entries.append(("user", text))

            elif role == "assistant":
                text = "" if content is None else str(content)
                text = _strip_reasoning(text)
                parts = []
                full_parts = []  # un-truncated version
                if text:
                    full_parts.append(text)
                    lines = text.splitlines()
                    if len(lines) > MAX_ASST_LINES:
                        text = "\n".join(lines[:MAX_ASST_LINES]) + " ..."
                    if len(text) > MAX_ASST_LEN:
                        text = text[:MAX_ASST_LEN] + "..."
                    parts.append(text)
                if tool_calls:
                    tc_count = len(tool_calls)
                    # Extract tool names
                    names = []
                    for tc in tool_calls:
                        fn = tc.get("function", {})
                        name = (
                            fn.get("name", "unknown")
                            if isinstance(fn, dict)
                            else "unknown"
                        )
                        if name not in names:
                            names.append(name)
                    names_str = ", ".join(names[:4])
                    if len(names) > 4:
                        names_str += ", ..."
                    noun = "call" if tc_count == 1 else "calls"
                    tc_summary = f"[{tc_count} tool {noun}: {names_str}]"
                    parts.append(tc_summary)
                    full_parts.append(tc_summary)
                if not parts:
                    # Skip pure-reasoning messages that have no visible output
                    continue
                entries.append(("assistant", " ".join(parts)))
                _last_asst_idx = len(entries) - 1
                _last_asst_full = " ".join(full_parts)

        if not entries:
            return

        # Determine if we need to truncate
        skipped = 0
        if len(entries) > MAX_DISPLAY_EXCHANGES * 2:
            skipped = len(entries) - MAX_DISPLAY_EXCHANGES * 2
            entries = entries[skipped:]

        # Replace last assistant entry with full (un-truncated) text
        # so the user can see where they left off without wasting tokens.
        if _last_asst_idx is not None and _last_asst_full:
            adj_idx = _last_asst_idx - skipped
            if 0 <= adj_idx < len(entries):
                entries[adj_idx] = ("assistant_last", _last_asst_full)

        # Build the display using Rich
        from rich.panel import Panel
        from rich.text import Text

        try:
            from spark_cli.skin_engine import get_active_skin

            _skin = get_active_skin()
            _history_text_c = _skin.get_color("banner_text", "#FFF8DC")
            _session_label_c = _skin.get_color("session_label", "#DAA520")
            _session_border_c = _skin.get_color("session_border", "#8B8682")
            _assistant_label_c = _skin.get_color("ui_ok", "#8FBC8F")
        except Exception:
            _history_text_c = "#FFF8DC"
            _session_label_c = "#DAA520"
            _session_border_c = "#8B8682"
            _assistant_label_c = "#8FBC8F"

        lines = Text()
        if skipped:
            lines.append(
                f"  ... {skipped} earlier messages ...\n\n",
                style="dim italic",
            )

        for i, (role, text) in enumerate(entries):
            if role == "user":
                lines.append("  ● You: ", style=f"dim bold {_session_label_c}")
                # Show first line inline, indent rest
                msg_lines = text.splitlines()
                lines.append(msg_lines[0] + "\n", style="dim")
                for ml in msg_lines[1:]:
                    lines.append(f"         {ml}\n", style="dim")
            elif role == "assistant_last":
                # Last assistant response shown in full, non-dim
                lines.append("  ◆ Spark: ", style=f"bold {_assistant_label_c}")
                msg_lines = text.splitlines()
                lines.append(msg_lines[0] + "\n", style="")
                for ml in msg_lines[1:]:
                    lines.append(f"            {ml}\n", style="")
            else:
                lines.append("  ◆ Spark: ", style=f"dim bold {_assistant_label_c}")
                msg_lines = text.splitlines()
                lines.append(msg_lines[0] + "\n", style="dim")
                for ml in msg_lines[1:]:
                    lines.append(f"            {ml}\n", style="dim")
            if i < len(entries) - 1:
                lines.append("")  # small gap

        panel = Panel(
            lines,
            title=f"[dim {_session_label_c}]Previous Conversation[/]",
            border_style=f"dim {_session_border_c}",
            padding=(0, 1),
            style=_history_text_c,
        )
        self.console.print(panel)

    def _try_attach_clipboard_image(self) -> bool:
        """Check clipboard for an image and attach it if found.

        Saves the image to ~/"spark/images/ and appends the path to
        ``_attached_images``.  Returns True if an image was attached.
        """
        from spark_cli.clipboard import save_clipboard_image

        img_dir = get_spark_home() / "images"
        self._image_counter += 1
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        img_path = img_dir / f"clip_{ts}_{self._image_counter}.png"

        if save_clipboard_image(img_path):
            self._attached_images.append(img_path)
            return True
        self._image_counter -= 1
        return False

    def save_conversation(self):
        """Save the current conversation to a file."""
        if not self.conversation_history:
            print("(;_;) No conversation to save.")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"spark_conversation_{timestamp}.json"

        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "model": self.model,
                        "session_start": self.session_start.isoformat(),
                        "messages": self.conversation_history,
                    },
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
            print(f"Conversation saved to: {filename}")
        except Exception as e:
            print(f"Failed to save: {e}")

    def retry_last(self):
        """Retry the last user message by removing the last exchange and re-sending.

        Removes the last assistant response (and any tool-call messages) and
        the last user message, then re-sends that user message to the agent.
        Returns the message to re-send, or None if there's nothing to retry.
        """
        if not self.conversation_history:
            print("(._.) No messages to retry.")
            return None

        # Walk backwards to find the last user message
        last_user_idx = None
        for i in range(len(self.conversation_history) - 1, -1, -1):
            if self.conversation_history[i].get("role") == "user":
                last_user_idx = i
                break

        if last_user_idx is None:
            print("(._.) No user message found to retry.")
            return None

        # Extract the message text and remove everything from that point forward
        last_message = self.conversation_history[last_user_idx].get("content", "")
        self.conversation_history = self.conversation_history[:last_user_idx]

        print(
            f'Retrying: "{last_message[:60]}{"..." if len(last_message) > 60 else ""}"'
        )
        return last_message

    def undo_last(self):
        """Remove the last user/assistant exchange from conversation history.

        Walks backwards and removes all messages from the last user message
        onward (including assistant responses, tool calls, etc.).
        """
        if not self.conversation_history:
            print("(._.) No messages to undo.")
            return

        # Walk backwards to find the last user message
        last_user_idx = None
        for i in range(len(self.conversation_history) - 1, -1, -1):
            if self.conversation_history[i].get("role") == "user":
                last_user_idx = i
                break

        if last_user_idx is None:
            print("(._.) No user message found to undo.")
            return

        # Count how many messages we're removing
        removed_count = len(self.conversation_history) - last_user_idx
        removed_msg = self.conversation_history[last_user_idx].get("content", "")

        # Truncate history to before the last user message
        self.conversation_history = self.conversation_history[:last_user_idx]

        print(
            f'Undid {removed_count} message(s). Removed: "{removed_msg[:60]}{"..." if len(removed_msg) > 60 else ""}"'
        )
        remaining = len(self.conversation_history)
        print(f"  {remaining} message(s) remaining in history.")

    @staticmethod
    def _resolve_personality_prompt(value) -> str:
        """Accept string or dict personality value; return system prompt string."""
        if isinstance(value, dict):
            parts = [value.get("system_prompt", "")]
            if value.get("tone"):
                parts.append(f"Tone: {value['tone']}")
            if value.get("style"):
                parts.append(f"Style: {value['style']}")
            return "\n".join(p for p in parts if p)
        return str(value)

    def _show_gateway_status(self):
        """Show status of the gateway and connected messaging platforms."""
        from gateway.config import Platform, load_gateway_config

        print()
        print("+" + "-" * 60 + "+")
        print("|" + " " * 15 + "(✿◠‿◠) Gateway Status" + " " * 17 + "|")
        print("+" + "-" * 60 + "+")
        print()

        try:
            config = load_gateway_config()

            print("  Messaging Platform Configuration:")
            print("  " + "-" * 55)

            platform_status = {
                Platform.TELEGRAM: ("Telegram", "TELEGRAM_BOT_TOKEN"),
                Platform.DISCORD: ("Discord", "DISCORD_BOT_TOKEN"),
                Platform.WHATSAPP: ("WhatsApp", "WHATSAPP_ENABLED"),
            }

            for platform, (name, env_var) in platform_status.items():
                pconfig = config.platforms.get(platform)
                if pconfig and pconfig.enabled:
                    home = config.get_home_channel(platform)
                    home_str = f" → {home.name}" if home else ""
                    print(f"    OK: {name:<12} Enabled{home_str}")
                else:
                    print(f"    ○ {name:<12} Not configured ({env_var})")

            print()
            print("  Session Reset Policy:")
            print("  " + "-" * 55)
            policy = config.default_reset_policy
            print(f"    Mode: {policy.mode}")
            print(f"    Daily reset at: {policy.at_hour}:00")
            print(f"    Idle timeout: {policy.idle_minutes} minutes")

            print()
            print("  To start the gateway:")
            print("    python cli.py --gateway")
            print()
            print(f"  Configuration file: {display_spark_home()}/config.yaml")
            print()

        except Exception as e:
            print(f"  Error loading gateway config: {e}")
            print()
            print("  To configure the gateway:")
            print("    1. Set environment variables:")
            print("       TELEGRAM_BOT_TOKEN=your_token")
            print("       DISCORD_BOT_TOKEN=your_token")
            print(f"    2. Or configure settings in {display_spark_home()}/config.yaml")
            print()

