"""The interactive prompt_toolkit run loop and chat turn for SparkCLI.

Extracted from core/cli/__init__.py. Mixed into SparkCLI; the methods use
instance state resolved through the MRO, so this is a pure relocation.
"""

from __future__ import annotations

import atexit
import logging
import os
import queue
import shutil
import sys
import textwrap
import threading
import time
from datetime import datetime
from pathlib import Path

from prompt_toolkit.application import Application
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import ConditionalContainer, FormattedTextControl, HSplit, Layout, Window
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
from rich import box as rich_box
from rich.markup import escape as _escape
from rich.panel import Panel

from agent.skill_commands import build_skill_invocation_message
from core.cli.attachments import (
    _detect_file_drop,
    _format_image_attachment_badges,
    _format_process_notification,
    _should_auto_attach_clipboard_image_on_paste,
)
from core.cli.render import _ACCENT, _DIM, _RST, _accent_hex, _cprint, _rich_text_from_ansi
from core.model_tools import get_tool_definitions
from core.spark_constants import display_spark_home
from spark_cli.banner import build_welcome_banner
from spark_cli.commands import SlashCommandAutoSuggest, SlashCommandCompleter
from tools.skills_tool import set_secret_capture_callback
from tools.terminal_tool import set_approval_callback, set_sudo_password_callback


def _pkg():
    """Resolve module-level names through the package.

    core.cli imports this module, so a top-level import back would be a cycle.
    Going through the package also keeps the names patchable: several tests
    monkeypatch core.cli._build_compact_banner, _skill_commands and _spark_home.
    """
    import core.cli

    return core.cli


logger = logging.getLogger(__name__)


class _MainLoopMixin:
    def process_command(self, command: str) -> bool:
        """
        Process a slash command.

        Args:
            command: The command string (starting with /)

        Returns:
            bool: True to continue, False to exit
        """
        # Lowercase only for dispatch matching; preserve original case for arguments
        cmd_lower = command.lower().strip()
        cmd_original = command.strip()

        # Resolve aliases via central registry so adding an alias is a one-line
        # change in spark_cli/commands.py instead of touching every dispatch site.
        from spark_cli.commands import resolve_command as _resolve_cmd

        _base_word = cmd_lower.split()[0].lstrip("/")
        _cmd_def = _resolve_cmd(_base_word)
        canonical = _cmd_def.name if _cmd_def else _base_word

        if canonical in ("quit", "exit", "q"):
            return False
        elif canonical == "help":
            self.show_help()
        elif canonical == "profile":
            self._handle_profile_command()
        elif canonical == "tools":
            self._handle_tools_command(cmd_original)
        elif canonical == "toolsets":
            self.show_toolsets()
        elif canonical == "connectors":
            self._handle_connectors_command(cmd_original)
        elif canonical == "config":
            self.show_config()
        elif canonical == "clear":
            self.new_session(silent=True)
            # Clear terminal screen.  Inside the TUI, Rich's console.clear()
            # goes through patch_stdout's StdoutProxy which swallows the
            # screen-clear escape sequences.  Use prompt_toolkit's output
            # object directly to actually clear the terminal.
            if self._app:
                out = self._app.output
                out.erase_screen()
                out.cursor_goto(0, 0)
                out.flush()
            else:
                self.console.clear()
            # Show fresh banner.  Inside the TUI we must route Rich output
            # through ChatConsole (which uses prompt_toolkit's native ANSI
            # renderer) instead of self.console (which writes raw to stdout
            # and gets mangled by patch_stdout).
            if self._app:
                cc = _pkg().ChatConsole()
                term_w = shutil.get_terminal_size().columns
                if self.compact or term_w < 80:
                    cc.print(_pkg()._build_compact_banner())
                else:
                    tools = get_tool_definitions(
                        enabled_toolsets=self.enabled_toolsets, quiet_mode=True
                    )
                    cwd = os.getenv("TERMINAL_CWD", os.getcwd())
                    ctx_len = None
                    if (
                        hasattr(self, "agent")
                        and self.agent
                        and hasattr(self.agent, "context_compressor")
                    ):
                        ctx_len = self.agent.context_compressor.context_length
                    build_welcome_banner(
                        console=cc,
                        model=self.model,
                        cwd=cwd,
                        tools=tools,
                        enabled_toolsets=self.enabled_toolsets,
                        session_id=self.session_id,
                        context_length=ctx_len,
                    )
                _cprint("  Fresh start! Screen cleared and conversation reset.\n")
                # Show a random tip on new session
                try:
                    from spark_cli.tips import get_random_tip

                    _tip = get_random_tip()
                    try:
                        from spark_cli.skin_engine import get_active_skin

                        _tip_color = get_active_skin().get_color(
                            "banner_dim", "#B8860B"
                        )
                    except Exception:
                        _tip_color = "#B8860B"
                    cc.print(f"[dim {_tip_color}]✦ Tip: {_tip}[/]")
                except Exception:
                    logger.debug("Ignoring error in process_command()", exc_info=True)
            else:
                self.show_banner()
                print("  Fresh start! Screen cleared and conversation reset.\n")
                # Show a random tip on new session
                try:
                    from spark_cli.tips import get_random_tip

                    _tip = get_random_tip()
                    try:
                        from spark_cli.skin_engine import get_active_skin

                        _tip_color = get_active_skin().get_color(
                            "banner_dim", "#B8860B"
                        )
                    except Exception:
                        _tip_color = "#B8860B"
                    self.console.print(f"[dim {_tip_color}]✦ Tip: {_tip}[/]")
                except Exception:
                    logger.debug("Ignoring error in process_command()", exc_info=True)
        elif canonical == "history":
            self.show_history()
        elif canonical == "title":
            parts = cmd_original.split(maxsplit=1)
            if len(parts) > 1:
                raw_title = parts[1].strip()
                if raw_title:
                    if self._session_db:
                        # Sanitize the title early so feedback matches what gets stored
                        try:
                            from core.spark_state import SessionDB

                            new_title = SessionDB.sanitize_title(raw_title)
                        except ValueError as e:
                            _cprint(f"  {e}")
                            new_title = None
                        if not new_title:
                            _cprint(
                                "  Title is empty after cleanup. Please use printable characters."
                            )
                        elif self._session_db.get_session(self.session_id):
                            # Session exists in DB - set title directly
                            try:
                                if self._session_db.set_session_title(
                                    self.session_id, new_title
                                ):
                                    _cprint(f"  Session title set: {new_title}")
                                else:
                                    _cprint("  Session not found in database.")
                            except ValueError as e:
                                _cprint(f"  {e}")
                        else:
                            # Session not created yet - defer the title
                            # Check uniqueness proactively with the sanitized title
                            existing = self._session_db.get_session_by_title(new_title)
                            if existing:
                                _cprint(
                                    f"  Title '{new_title}' is already in use by session {existing['id']}"
                                )
                            else:
                                self._pending_title = new_title
                                _cprint(
                                    f"  Session title queued: {new_title} (will be saved on first message)"
                                )
                    else:
                        _cprint("  Session database not available.")
                else:
                    _cprint("  Usage: /title <your session title>")
            else:
                # Show current title and session ID if no argument given
                if self._session_db:
                    _cprint(f"  Session ID: {self.session_id}")
                    session = self._session_db.get_session(self.session_id)
                    if session and session.get("title"):
                        _cprint(f"  Title: {session['title']}")
                    elif self._pending_title:
                        _cprint(f"  Title (pending): {self._pending_title}")
                    else:
                        _cprint("  No title set. Usage: /title <your session title>")
                else:
                    _cprint("  Session database not available.")
        elif canonical == "new":
            self.new_session()
        elif canonical == "resume":
            self._handle_resume_command(cmd_original)
        elif canonical == "model":
            self._handle_model_switch(cmd_original)
        elif canonical == "provider":
            self._show_model_and_providers()

        elif canonical == "personality":
            # Use original case (handler lowercases the personality name itself)
            self._handle_personality_command(cmd_original)
        elif canonical == "plan":
            self._handle_plan_command(cmd_original)
        elif canonical == "retry":
            retry_msg = self.retry_last()
            if retry_msg and hasattr(self, "_pending_input"):
                # Re-queue the message so process_loop sends it to the agent
                self._pending_input.put(retry_msg)
        elif canonical == "undo":
            self.undo_last()
        elif canonical == "branch":
            self._handle_branch_command(cmd_original)
        elif canonical == "save":
            self.save_conversation()
        elif canonical == "cron":
            self._handle_cron_command(cmd_original)
        elif canonical == "dream":
            self._handle_dream_command(cmd_original)
        elif canonical == "learnings":
            self._handle_learnings_command(cmd_original)
        elif canonical == "curator":
            self._handle_curator_command(cmd_original)
        elif canonical == "goal":
            self._handle_goal_command(cmd_original)
        elif canonical == "skills":
            with self._busy_command(self._slow_command_status(cmd_original)):
                self._handle_skills_command(cmd_original)
        elif canonical == "reset-skills":
            self._handle_reset_skills_command()
        elif canonical == "platforms":
            self._show_gateway_status()
        elif canonical == "status":
            self._show_session_status()
        elif canonical == "statusbar":
            self._status_bar_visible = not self._status_bar_visible
            state = "visible" if self._status_bar_visible else "hidden"
            self.console.print(f"  Status bar {state}")
        elif canonical == "verbose":
            self._toggle_verbose()
        elif canonical == "yolo":
            self._toggle_yolo()
        elif canonical == "reasoning":
            self._handle_reasoning_command(cmd_original)
        elif canonical == "think":
            self._handle_think_command(cmd_original)
        elif canonical == "backend":
            self._handle_backend_command(cmd_original)
        elif canonical == "fast":
            self._handle_fast_command(cmd_original)
        elif canonical == "compress":
            self._manual_compress(cmd_original)
        elif canonical == "usage":
            self._show_usage()
        elif canonical == "insights":
            self._show_insights(cmd_original)
        elif canonical == "kanban":
            self._handle_kanban_slash(cmd_original)
        elif canonical == "debug":
            self._handle_debug_command()
        elif canonical == "feedback":
            self._handle_feedback_command()
        elif canonical == "paste":
            self._handle_paste_command()
        elif canonical == "image":
            self._handle_image_command(cmd_original)
        elif canonical == "reload":
            from spark_cli.config import reload_env

            count = reload_env()
            print(f"  Reloaded .env ({count} var(s) updated)")
        elif canonical == "reload-mcp":
            with self._busy_command(self._slow_command_status(cmd_original)):
                self._reload_mcp()
        elif canonical == "browser":
            self._handle_browser_command(cmd_original)
        elif canonical == "computer-use":
            self._handle_computer_use_command(cmd_original)
        elif canonical == "plugins":
            try:
                from spark_cli.plugins import get_plugin_manager

                mgr = get_plugin_manager()
                plugins = mgr.list_plugins()
                if not plugins:
                    print("No plugins installed.")
                    print(
                        f"Drop plugin directories into {display_spark_home()}/plugins/ to get started."
                    )
                else:
                    print(f"Plugins ({len(plugins)}):")
                    for p in plugins:
                        status = "✓" if p["enabled"] else "✗"
                        version = f" v{p['version']}" if p["version"] else ""
                        tools = f"{p['tools']} tools" if p["tools"] else ""
                        hooks = f"{p['hooks']} hooks" if p["hooks"] else ""
                        parts = [x for x in [tools, hooks] if x]
                        detail = f" ({', '.join(parts)})" if parts else ""
                        error = f" - {p['error']}" if p["error"] else ""
                        print(f"  {status} {p['name']}{version}{detail}{error}")
            except Exception as e:
                print(f"Plugin system error: {e}")
        elif canonical == "rollback":
            self._handle_rollback_command(cmd_original)
        elif canonical == "snapshot":
            self._handle_snapshot_command(cmd_original)
        elif canonical == "stop":
            self._handle_stop_command()
        elif canonical == "background":
            self._handle_background_command(cmd_original)
        elif canonical == "btw":
            self._handle_btw_command(cmd_original)
        elif canonical == "queue":
            # Extract prompt after "/queue " or "/q "
            parts = cmd_original.split(None, 1)
            payload = parts[1].strip() if len(parts) > 1 else ""
            if not payload:
                _cprint("  Usage: /queue <prompt>")
            else:
                self._pending_input.put(payload)
                if self._agent_running:
                    _cprint(
                        f"  Queued for the next turn: {payload[:80]}{'...' if len(payload) > 80 else ''}"
                    )
                else:
                    _cprint(
                        f"  Queued: {payload[:80]}{'...' if len(payload) > 80 else ''}"
                    )
        elif canonical == "sessions":
            self._handle_sessions_command()
        elif canonical == "export":
            self._handle_export_command(cmd_original)
        elif canonical == "files":
            self._handle_files_command()
        elif canonical == "memory":
            self._handle_memory_command()
        elif canonical == "keys":
            self._handle_keys_command()
        elif canonical == "skin":
            self._handle_skin_command(cmd_original)
        elif canonical == "voice":
            self._handle_voice_command(cmd_original)
        else:
            # Check for user-defined quick commands (bypass agent loop, no LLM call)
            base_cmd = cmd_lower.split()[0]
            quick_commands = self.config.get("quick_commands", {})
            if base_cmd.lstrip("/") in quick_commands:
                qcmd = quick_commands[base_cmd.lstrip("/")]
                if qcmd.get("type") == "exec":
                    import subprocess

                    exec_cmd = qcmd.get("command", "")
                    if exec_cmd:
                        try:
                            result = subprocess.run(
                                exec_cmd,
                                shell=True,
                                capture_output=True,
                                text=True,
                                timeout=30,
                            )
                            output = result.stdout.strip() or result.stderr.strip()
                            if output:
                                self.console.print(_rich_text_from_ansi(output))
                            else:
                                self.console.print("[dim]Command returned no output[/]")
                        except subprocess.TimeoutExpired:
                            self.console.print(
                                "[bold red]Quick command timed out (30s)[/]"
                            )
                        except Exception as e:
                            self.console.print(f"[bold red]Quick command error: {e}[/]")
                    else:
                        self.console.print(
                            f"[bold red]Quick command '{base_cmd}' has no command defined[/]"
                        )
                elif qcmd.get("type") == "alias":
                    target = qcmd.get("target", "").strip()
                    if target:
                        target = target if target.startswith("/") else f"/{target}"
                        user_args = cmd_original[len(base_cmd) :].strip()
                        aliased_command = f"{target} {user_args}".strip()
                        return self.process_command(aliased_command)
                    else:
                        self.console.print(
                            f"[bold red]Quick command '{base_cmd}' has no target defined[/]"
                        )
                else:
                    self.console.print(
                        f"[bold red]Quick command '{base_cmd}' has unsupported type (supported: 'exec', 'alias')[/]"
                    )
            # Check for plugin-registered slash commands
            elif base_cmd.lstrip("/") in _pkg()._get_plugin_cmd_handler_names():
                from spark_cli.plugins import get_plugin_command_handler

                plugin_handler = get_plugin_command_handler(base_cmd.lstrip("/"))
                if plugin_handler:
                    user_args = cmd_original[len(base_cmd) :].strip()
                    try:
                        result = plugin_handler(user_args)
                        if result:
                            _cprint(str(result))
                    except Exception as e:
                        _cprint(f"\033[1;31mPlugin command error: {e}{_RST}")
            # Check for skill slash commands (/gif-search, /axolotl, etc.)
            elif base_cmd in _pkg()._skill_commands:
                user_instruction = cmd_original[len(base_cmd) :].strip()
                msg = build_skill_invocation_message(
                    base_cmd, user_instruction, task_id=self.session_id
                )
                if msg:
                    skill_name = _pkg()._skill_commands[base_cmd]["name"]
                    print(f"\n⚡ Loading skill: {skill_name}")
                    if hasattr(self, "_pending_input"):
                        self._pending_input.put(msg)
                else:
                    _pkg().ChatConsole().print(
                        f"[bold red]Failed to load skill for {base_cmd}[/]"
                    )
            else:
                # Prefix matching: if input uniquely identifies one command, execute it.
                # Matches against both built-in COMMANDS and installed skill commands so
                # that execution-time resolution agrees with tab-completion.
                from spark_cli.commands import COMMANDS

                typed_base = cmd_lower.split()[0]
                all_known = set(COMMANDS) | set(_pkg()._skill_commands)
                matches = [c for c in all_known if c.startswith(typed_base)]
                if len(matches) > 1:
                    # Prefer an exact match (typed the full command name)
                    exact = [c for c in matches if c == typed_base]
                    if len(exact) == 1:
                        matches = exact
                    else:
                        # Prefer the unique shortest match:
                        # /qui → /quit (5) wins over /quint-pipeline (15)
                        min_len = min(len(c) for c in matches)
                        shortest = [c for c in matches if len(c) == min_len]
                        if len(shortest) == 1:
                            matches = shortest
                if len(matches) == 1:
                    # Expand the prefix to the full command name, preserving arguments.
                    # Guard against redispatching the same token to avoid infinite
                    # recursion when the expanded name still doesn't hit an exact branch
                    # (e.g. /config with extra args that are not yet handled above).
                    full_name = matches[0]
                    if full_name == typed_base:
                        # Already an exact token - no expansion possible; fall through
                        _cprint(f"\033[1;31mUnknown command: {cmd_lower}{_RST}")
                        _skill_name = typed_base.lstrip("/")
                        _cprint(
                            f"{_DIM}{_ACCENT}Type /help for available commands, "
                            f"or search for a skill: /skills search {_skill_name}{_RST}"
                        )
                    else:
                        remainder = cmd_original.strip()[len(typed_base) :]
                        full_cmd = full_name + remainder
                        return self.process_command(full_cmd)
                elif len(matches) > 1:
                    _cprint(f"{_ACCENT}Ambiguous command: {cmd_lower}{_RST}")
                    _cprint(f"{_DIM}Did you mean: {', '.join(sorted(matches))}?{_RST}")
                else:
                    _cprint(f"\033[1;31mUnknown command: {cmd_lower}{_RST}")
                    _skill_name = typed_base.lstrip("/")
                    _cprint(
                        f"{_DIM}{_ACCENT}Type /help for available commands, "
                        f"or search for a skill: /skills search {_skill_name}{_RST}"
                    )

        return True

    def chat(self, message, images: list = None) -> str | None:
        """
        Send a message to the agent and get a response.

        Handles streaming output, interrupt detection (user typing while agent
        is working), and re-queueing of interrupted messages.

        Uses a dedicated _interrupt_queue (separate from _pending_input) to avoid
        race conditions between the process_loop and interrupt monitoring. Messages
        typed while the agent is running go to _interrupt_queue; messages typed while
        idle go to _pending_input.

        Args:
            message: The user's message (str or multimodal content list)
            images: Optional list of Path objects for attached images

        Returns:
            The agent's response, or None on error
        """
        # Single-query and direct chat callers do not go through run(), so
        # register secure secret capture here as well.
        set_secret_capture_callback(self._secret_capture_callback)

        # Refresh provider credentials if needed (handles key rotation transparently)
        if not self._ensure_runtime_credentials():
            return None

        turn_route = self._resolve_turn_agent_config(message)
        if turn_route["signature"] != self._active_agent_route_signature:
            self.agent = None

        # Initialize agent if needed
        if self.agent is None:
            _cprint(f"{_DIM}Initializing agent...{_RST}")
        if not self._init_agent(
            model_override=turn_route["model"],
            runtime_override=turn_route["runtime"],
            route_label=turn_route["label"],
            request_overrides=turn_route.get("request_overrides"),
        ):
            return None

        # Pre-process images through the vision tool (Gemini Flash) so the
        # main model receives text descriptions instead of raw base64 image
        # content - works with any model, not just vision-capable ones.
        if images:
            message = self._preprocess_images_with_vision(
                message if isinstance(message, str) else "", images
            )

        # Expand @ context references (e.g. @file:main.py, @diff, @folder:src/)
        if isinstance(message, str) and "@" in message:
            try:
                from agent.context_references import preprocess_context_references
                from agent.model_metadata import get_model_context_length

                _ctx_len = get_model_context_length(
                    self.model, base_url=self.base_url or "", api_key=self.api_key or ""
                )
                _ctx_result = preprocess_context_references(
                    message, cwd=os.getcwd(), context_length=_ctx_len
                )
                if _ctx_result.expanded or _ctx_result.blocked:
                    if _ctx_result.references:
                        _cprint(
                            f"  {_DIM}[@ context: {len(_ctx_result.references)} ref(s), "
                            f"{_ctx_result.injected_tokens} tokens]{_RST}"
                        )
                    for w in _ctx_result.warnings:
                        _cprint(f"  {_DIM}WARN {w}{_RST}")
                    if _ctx_result.blocked:
                        return (
                            "\n".join(_ctx_result.warnings)
                            or "Context injection refused."
                        )
                    message = _ctx_result.message
            except Exception as e:
                logging.debug("@ context reference expansion failed: %s", e)

        # Sanitize surrogate characters that can arrive via clipboard paste from
        # rich-text editors (Google Docs, Word, etc.).  Lone surrogates are invalid
        # UTF-8 and crash JSON serialization in the OpenAI SDK.
        if isinstance(message, str):
            from core.run_agent import _sanitize_surrogates

            message = _sanitize_surrogates(message)

        # Ensure the startup splash is dismissed before first turn output.
        self._dismiss_welcome_logo()
        if hasattr(self, "_app") and self._app:
            self._app.invalidate()

        # Add user message to history
        self.conversation_history.append({"role": "user", "content": message})

        _pkg().ChatConsole().print(f"[{_accent_hex()}]{'─' * 40}[/]")
        print(flush=True)

        try:
            # Run the conversation with interrupt monitoring
            result = None

            # Reset streaming display state for this turn
            self._reset_stream_state()
            # Separate from _reset_stream_state because this must persist
            # across intermediate turn boundaries (tool-calling loops) - only
            # reset at the start of each user turn.
            self._reasoning_shown_this_turn = False

            # --- Streaming TTS setup ---
            # When ElevenLabs is the TTS provider and sounddevice is available,
            # we stream audio sentence-by-sentence as the agent generates tokens
            # instead of waiting for the full response.
            use_streaming_tts = False
            _streaming_box_opened = False
            text_queue = None
            tts_thread = None
            stream_callback = None
            stop_event = None

            if self._voice_tts:
                try:
                    from tools.tts_tool import (
                        _get_provider as _get_prov,
                    )
                    from tools.tts_tool import (
                        _import_elevenlabs,
                        _import_sounddevice,
                        stream_tts_to_speaker,
                    )
                    from tools.tts_tool import (
                        _load_tts_config as _load_tts_cfg,
                    )

                    _tts_cfg = _load_tts_cfg()
                    if _get_prov(_tts_cfg) == "elevenlabs":
                        # Verify both ElevenLabs SDK and audio output are available
                        _import_elevenlabs()
                        _import_sounddevice()
                        use_streaming_tts = True
                except (ImportError, OSError):
                    logger.debug("Ignoring error in chat()", exc_info=True)
                except Exception:
                    logger.debug("Ignoring error in chat()", exc_info=True)

            if use_streaming_tts:
                text_queue = queue.Queue()
                stop_event = threading.Event()

                def display_callback(sentence: str):
                    """Called by TTS consumer when a sentence is ready to display + speak."""
                    nonlocal _streaming_box_opened
                    if not _streaming_box_opened:
                        _streaming_box_opened = True
                        w = self.console.width
                        label = " S Spark "
                        fill = w - 2 - len(label)
                        _cprint(f"\n{_ACCENT}+-{label}{'-' * max(fill - 1, 0)}+{_RST}")
                    _cprint(sentence.rstrip())

                tts_thread = threading.Thread(
                    target=stream_tts_to_speaker,
                    args=(text_queue, stop_event, self._voice_tts_done),
                    kwargs={"display_callback": display_callback},
                    daemon=True,
                )
                tts_thread.start()

                def stream_callback(delta: str):
                    if text_queue is not None:
                        text_queue.put(delta)

            # When voice mode is active, prepend a brief instruction so the
            # model responds concisely. The prefix is API-call-local only -
            # run_conversation persists the original clean user message.
            _voice_prefix = ""
            if self._voice_mode and isinstance(message, str):
                _voice_prefix = (
                    "[Voice input - respond concisely and conversationally, "
                    "2-3 sentences max. No code blocks or markdown.] "
                )

            def run_agent():
                nonlocal result
                agent_message = _voice_prefix + message if _voice_prefix else message
                # Prepend pending model switch note so the model knows about the switch
                _msn = getattr(self, "_pending_model_switch_note", None)
                if _msn:
                    agent_message = _msn + "\n\n" + agent_message
                    self._pending_model_switch_note = None
                try:
                    result = self.agent.run_conversation(
                        user_message=agent_message,
                        conversation_history=self.conversation_history[
                            :-1
                        ],  # Exclude the message we just added
                        stream_callback=stream_callback,
                        task_id=self.session_id,
                        persist_user_message=message if _voice_prefix else None,
                    )
                except Exception as exc:
                    logging.error("run_conversation raised: %s", exc, exc_info=True)
                    _summary = getattr(
                        self.agent, "_summarize_api_error", lambda e: str(e)[:300]
                    )(exc)
                    result = {
                        "final_response": f"Error: {_summary}",
                        "messages": [],
                        "api_calls": 0,
                        "completed": False,
                        "failed": True,
                        "error": _summary,
                    }

            # Start agent in background thread (daemon so it cannot keep the
            # process alive when the user closes the terminal tab - SIGHUP
            # exits the main thread and daemon threads are reaped automatically).
            agent_thread = threading.Thread(target=run_agent, daemon=True)
            agent_thread.start()

            # Monitor the dedicated interrupt queue while the agent runs.
            # _interrupt_queue is separate from _pending_input, so process_loop
            # and chat() never compete for the same queue.
            # When a clarify question is active, user input is handled entirely
            # by the Enter key binding (routed to the clarify response queue),
            # so we skip interrupt processing to avoid stealing that input.
            interrupt_msg = None
            while agent_thread.is_alive():
                if hasattr(self, "_interrupt_queue"):
                    try:
                        interrupt_msg = self._interrupt_queue.get(timeout=0.1)
                        if interrupt_msg:
                            # If clarify is active, the Enter handler routes
                            # input directly; this queue shouldn't have anything.
                            # But if it does (race condition), don't interrupt.
                            if self._clarify_state or self._clarify_freetext:
                                continue
                            print("\n⚡ New message detected, interrupting...")
                            # Signal TTS to stop on interrupt
                            if stop_event is not None:
                                stop_event.set()
                            self.agent.interrupt(interrupt_msg)
                            # Debug: log to file (stdout may be devnull from redirect_stdout)
                            try:
                                _dbg = _pkg()._spark_home / "interrupt_debug.log"
                                with open(_dbg, "a") as _f:
                                    import time as _t

                                    _f.write(
                                        f"{_t.strftime('%H:%M:%S')} interrupt fired: msg={str(interrupt_msg)[:60]!r}, "
                                        f"children={len(self.agent._active_children)}, "
                                        f"parent._interrupt={self.agent._interrupt_requested}\n"
                                    )
                                    for _ci, _ch in enumerate(
                                        self.agent._active_children
                                    ):
                                        _f.write(
                                            f"  child[{_ci}]._interrupt={_ch._interrupt_requested}\n"
                                        )
                            except Exception:
                                logger.debug("Ignoring error in chat()", exc_info=True)
                            break
                    except queue.Empty:
                        # Force prompt_toolkit to flush any pending stdout
                        # output from the agent thread.  Without this, the
                        # StdoutProxy buffer only flushes on renderer passes
                        # triggered by input events - on macOS this causes
                        # the CLI to appear frozen until the user types. (#1624)
                        self._invalidate(min_interval=0.15)
                else:
                    # Fallback for non-interactive mode (e.g., single-query)
                    agent_thread.join(0.1)

            agent_thread.join()  # Ensure agent thread completes

            # Proactively clean up async clients whose event loop is dead.
            # The agent thread may have created AsyncOpenAI clients bound
            # to a per-thread event loop; if that loop is now closed, those
            # clients' __del__ would crash prompt_toolkit's loop on GC.
            try:
                from agent.auxiliary_client import cleanup_stale_async_clients

                cleanup_stale_async_clients()
            except Exception:
                logger.debug("Ignoring error in chat()", exc_info=True)

            # Flush any remaining streamed text and close the box
            self._flush_stream()

            # Signal end-of-text to TTS consumer and wait for it to finish
            if use_streaming_tts and text_queue is not None:
                text_queue.put(None)  # sentinel
                if tts_thread is not None:
                    tts_thread.join(timeout=120)

            # Drain any remaining agent output still in the StdoutProxy
            # buffer so tool/status lines render ABOVE our response box.
            # The flush pushes data into the renderer queue; the short
            # sleep lets the renderer actually paint it before we draw.
            import time as _time

            sys.stdout.flush()
            _time.sleep(0.15)

            # Update history with full conversation
            self.conversation_history = (
                result.get("messages", self.conversation_history)
                if result
                else self.conversation_history
            )

            # Get the final response
            response = result.get("final_response", "") if result else ""

            # Auto-generate session title after first exchange (non-blocking)
            if (
                response
                and result
                and not result.get("failed")
                and not result.get("partial")
            ):
                try:
                    from agent.title_generator import maybe_auto_title

                    maybe_auto_title(
                        self._session_db,
                        self.session_id,
                        message,
                        response,
                        self.conversation_history,
                    )
                except Exception:
                    logger.debug("Ignoring error in chat()", exc_info=True)

            # Handle failed or partial results (e.g., non-retryable errors, rate limits,
            # truncated output, invalid tool calls). Both "failed" and "partial" with
            # an empty final_response mean the agent couldn't produce a usable answer.
            if (
                result
                and (result.get("failed") or result.get("partial"))
                and not response
            ):
                error_detail = result.get("error", "Unknown error")
                response = f"Error: {error_detail}"
                # Stop continuous voice mode on persistent errors (e.g. 429 rate limit)
                # to avoid an infinite error → record → error loop
                if self._voice_continuous:
                    self._voice_continuous = False
                    _cprint(
                        f"\n{_DIM}Continuous voice mode stopped due to error.{_RST}"
                    )

            # Handle interrupt - check if we were interrupted
            pending_message = None
            if result and result.get("interrupted"):
                pending_message = result.get("interrupt_message") or interrupt_msg
                # Add indicator that we were interrupted
                if response and pending_message:
                    response = (
                        response + "\n\n---\n_[Interrupted - processing new message]_"
                    )

            response_previewed = (
                result.get("response_previewed", False) if result else False
            )

            # Display reasoning (thinking) box if enabled and available.
            # Skip when streaming already showed reasoning live.  Use the
            # turn-persistent flag (_reasoning_shown_this_turn) instead of
            # _reasoning_stream_started - the latter gets reset during
            # intermediate turn boundaries (tool-calling loops), which caused
            # the reasoning box to re-render after the final response.
            _reasoning_already_shown = getattr(
                self, "_reasoning_shown_this_turn", False
            )
            if self.show_reasoning and result and not _reasoning_already_shown:
                reasoning = result.get("last_reasoning")
                if reasoning:
                    w = shutil.get_terminal_size().columns
                    r_label = " Reasoning "
                    r_fill = w - 2 - len(r_label)
                    r_top = f"{_DIM}+-{r_label}{'-' * max(r_fill - 1, 0)}+{_RST}"
                    r_bot = f"{_DIM}+{'-' * (w - 2)}+{_RST}"
                    # Collapse long reasoning: show first 10 lines
                    lines = reasoning.strip().splitlines()
                    if len(lines) > 10:
                        display_reasoning = "\n".join(lines[:10])
                        display_reasoning += (
                            f"\n{_DIM}  ... ({len(lines) - 10} more lines){_RST}"
                        )
                    else:
                        display_reasoning = reasoning.strip()
                    _cprint(f"\n{r_top}\n{_DIM}{display_reasoning}{_RST}\n{r_bot}")

            if response and not response_previewed:
                # Use skin engine for label/color with fallback
                try:
                    from spark_cli.skin_engine import get_active_skin

                    _skin = get_active_skin()
                    label = _skin.get_branding("response_label", "S Spark")
                    _resp_color = _skin.get_color("response_border", "#555555")
                    _resp_text = _skin.get_color("banner_text", "#FFF8DC")
                except Exception:
                    label = "S Spark"
                    _resp_color = "#555555"
                    _resp_text = "#FFF8DC"

                is_error_response = result and (
                    result.get("failed") or result.get("partial")
                )
                already_streamed = (
                    self._stream_started
                    and self._stream_box_opened
                    and not is_error_response
                )
                if (
                    use_streaming_tts
                    and _streaming_box_opened
                    and not is_error_response
                ):
                    # Text was already printed sentence-by-sentence; just close the box
                    w = shutil.get_terminal_size().columns
                    _cprint(f"\n{_ACCENT}+{'-' * (w - 2)}+{_RST}")
                elif already_streamed:
                    # Response was already streamed token-by-token with box framing;
                    # _flush_stream() already closed the box. Skip Rich Panel.
                    pass
                else:
                    _chat_console = _pkg().ChatConsole()
                    _chat_console.print(
                        Panel(
                            _rich_text_from_ansi(response),
                            title=f"[{_resp_color} bold]{label}[/]",
                            title_align="left",
                            border_style=_resp_color,
                            style=_resp_text,
                            box=rich_box.HORIZONTALS,
                            padding=(1, 2),
                        )
                    )

            # Play terminal bell when agent finishes (if enabled).
            # Works over SSH - the bell propagates to the user's terminal.
            if self.bell_on_complete:
                sys.stdout.write("\a")
                sys.stdout.flush()

            # Notify when iteration budget was hit
            if result and not result.get("completed") and not result.get("interrupted"):
                _api_calls = result.get("api_calls", 0)
                if _api_calls >= getattr(self.agent, "max_iterations", 90):
                    _max_iter = getattr(self.agent, "max_iterations", 90)
                    _cprint(
                        f"\n{_DIM}WARN Iteration budget reached "
                        f"({_api_calls}/{_max_iter}) - "
                        f"response may be incomplete{_RST}"
                    )

            # Speak response aloud if voice TTS is enabled
            # Skip batch TTS when streaming TTS already handled it
            if self._voice_tts and response and not use_streaming_tts:
                threading.Thread(
                    target=self._voice_speak_response,
                    args=(response,),
                    daemon=True,
                ).start()

            # Re-queue the interrupt message (and any that arrived while we were
            # processing the first) as the next prompt for process_loop.
            # Only reached when busy_input_mode == "interrupt" (the default).
            # In "queue" mode Enter routes directly to _pending_input so this
            # block is never hit.
            if pending_message and hasattr(self, "_pending_input"):
                all_parts = [pending_message]
                while not self._interrupt_queue.empty():
                    try:
                        extra = self._interrupt_queue.get_nowait()
                        if extra:
                            all_parts.append(extra)
                    except queue.Empty:
                        break
                combined = "\n".join(all_parts)
                n = len(all_parts)
                preview = combined[:50] + ("..." if len(combined) > 50 else "")
                if n > 1:
                    print(f"\n⚡ Sending {n} messages after interrupt: '{preview}'")
                else:
                    print(f"\n⚡ Sending after interrupt: '{preview}'")
                self._pending_input.put(combined)

            return response

        except Exception as e:
            print(f"Error: {e}")
            return None
        finally:
            # Ensure streaming TTS resources are cleaned up even on error.
            # Normal path sends the sentinel at line ~3568; this is a safety
            # net for exception paths that skip it.  Duplicate sentinels are
            # harmless - stream_tts_to_speaker exits on the first None.
            if text_queue is not None:
                try:
                    text_queue.put_nowait(None)
                except Exception:
                    logger.debug("Ignoring error in chat()", exc_info=True)
            if stop_event is not None:
                stop_event.set()
            if tts_thread is not None and tts_thread.is_alive():
                tts_thread.join(timeout=5)

    def _print_exit_summary(self):
        """Print session resume info on exit, similar to Claude Code."""
        print()
        msg_count = len(self.conversation_history)
        if msg_count > 0:
            user_msgs = len(
                [m for m in self.conversation_history if m.get("role") == "user"]
            )
            tool_calls = len(
                [
                    m
                    for m in self.conversation_history
                    if m.get("role") == "tool" or m.get("tool_calls")
                ]
            )
            elapsed = datetime.now() - self.session_start
            hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
            minutes, seconds = divmod(remainder, 60)
            if hours > 0:
                duration_str = f"{hours}h {minutes}m {seconds}s"
            elif minutes > 0:
                duration_str = f"{minutes}m {seconds}s"
            else:
                duration_str = f"{seconds}s"

            # Look up session title for resume-by-name hint
            session_title = None
            if self._session_db:
                try:
                    session_title = self._session_db.get_session_title(self.session_id)
                except Exception:
                    logger.debug("Ignoring error in _print_exit_summary()", exc_info=True)

            print("Resume this session with:")
            print(f"  spark --resume {self.session_id}")
            if session_title:
                print(f'  spark -c "{session_title}"')
            print()
            print(f"Session:        {self.session_id}")
            if session_title:
                print(f"Title:          {session_title}")
            print(f"Duration:       {duration_str}")
            print(
                f"Messages:       {msg_count} ({user_msgs} user, {tool_calls} tool calls)"
            )
        else:
            try:
                from spark_cli.skin_engine import get_active_goodbye

                goodbye = get_active_goodbye("Goodbye! S")
            except Exception:
                goodbye = "Goodbye! S"
            print(goodbye)

    def run(self):
        """Run the interactive CLI loop with persistent input at bottom."""
        start_centered = not self._resumed

        # Push the entire TUI to the bottom of the terminal so the banner,
        # responses, and prompt all appear pinned to the bottom - empty
        # space stays above, not below.  This prints enough blank lines to
        # scroll the cursor to the last row before any content is rendered.
        if not start_centered:
            try:
                _term_lines = shutil.get_terminal_size().lines
                if _term_lines > 2:
                    print("\n" * (_term_lines - 1), end="", flush=True)
            except Exception:
                logger.debug("Ignoring error in run()", exc_info=True)

        # In centered splash mode we suppress the legacy scrollback banner,
        # otherwise it creates a large visual gap above the splash block.
        if not start_centered:
            self.show_banner()

        # One-line Honcho session indicator (TTY-only, not captured by agent).
        # Only show when the user explicitly configured Honcho for Spark
        # (not auto-enabled from a stray HONCHO_API_KEY env var).
        # If resuming a session, load history and display it immediately
        # so the user has context before typing their first message.
        if self._resumed:
            if self._preload_resumed_session():
                self._display_resumed_history()

        try:
            from spark_cli.skin_engine import get_active_skin

            _welcome_skin = get_active_skin()
            _welcome_text = _welcome_skin.get_branding(
                "welcome",
                "Welcome to Spark! Type your message or /help for commands.",
            )
            _welcome_color = _welcome_skin.get_color("banner_text", "#FFF8DC")
        except Exception:
            _welcome_text = (
                "Welcome to Spark! Type your message or /help for commands."
            )
            _welcome_color = "#FFF8DC"
        _tip = ""
        _tip_color = "#f66914"
        # Show a random tip to help users discover features
        try:
            from spark_cli.tips import get_random_tip

            _tip = get_random_tip()
            try:
                _tip_color = _welcome_skin.get_color("banner_tip", "#f66914")
            except Exception:
                _tip_color = "#f66914"
        except Exception:
            _tip = ""  # Tips are non-critical - never break startup

        self._show_welcome_logo = not self._resumed
        self._welcome_splash_text = _welcome_text
        self._welcome_splash_tip = _tip
        self._welcome_splash_skills = ", ".join(self.preloaded_skills or [])
        self._welcome_splash_color = _welcome_color
        self._welcome_splash_tip_color = _tip_color

        if not self._show_welcome_logo:
            self.console.print(f"[{_welcome_color}]{_welcome_text}[/]")
            if _tip:
                self.console.print(f"[dim {_tip_color}]✦ Tip: {_tip}[/]")

        if self.preloaded_skills and not self._startup_skills_line_shown:
            skills_label = ", ".join(self.preloaded_skills)
            if not self._show_welcome_logo:
                self.console.print(
                    f"[bold {_accent_hex()}]Activated skills:[/] {skills_label}"
                )
            self._startup_skills_line_shown = True
        if not self._show_welcome_logo:
            self.console.print()

        # Prime the logo cache up front so first render is immediate.
        if self._show_welcome_logo:
            self._get_welcome_logo_ansi()

        # State for async operation
        self._agent_running = False
        self._pending_input = queue.Queue()  # For normal input (commands + new queries)
        self._interrupt_queue = (
            queue.Queue()
        )  # For messages typed while agent is running
        self._should_exit = False
        self._last_ctrl_c_time = 0  # Track double Ctrl+C for force exit

        # Give plugin manager a CLI reference so plugins can inject messages
        from spark_cli.plugins import get_plugin_manager

        get_plugin_manager()._cli_ref = self

        # Config file watcher - detect mcp_servers changes and auto-reload
        from spark_cli.config import get_config_path as _get_config_path

        _cfg_path = _get_config_path()
        self._config_mtime: float = (
            _cfg_path.stat().st_mtime if _cfg_path.exists() else 0.0
        )
        self._config_mcp_servers: dict = self.config.get("mcp_servers") or {}
        self._last_config_check: float = 0.0  # monotonic time of last check

        # Clarify tool state: interactive question/answer with the user.
        # When the agent calls the clarify tool, _clarify_state is set and
        # the prompt_toolkit UI switches to a selection mode.
        self._clarify_state = (
            None  # dict with question, choices, selected, response_queue
        )
        self._clarify_freetext = False  # True when user chose "Other" and is typing
        self._clarify_deadline = 0  # monotonic timestamp when the clarify times out

        # Sudo password prompt state (similar mechanism to clarify)
        self._sudo_state = None  # dict with response_queue when active
        self._sudo_deadline = 0
        self._modal_input_snapshot = None

        # Dangerous command approval state (similar mechanism to clarify)
        self._approval_state = (
            None  # dict with command, description, choices, selected, response_queue
        )
        self._approval_deadline = 0
        self._approval_lock = (
            threading.Lock()
        )  # serialize concurrent approval prompts (delegation race fix)

        # Slash command loading state
        self._command_running = False
        self._command_status = ""

        # Secure secret capture state for skill setup
        self._secret_state = (
            None  # dict with var_name, prompt, metadata, response_queue
        )
        self._secret_deadline = 0

        # Clipboard image attachments (paste images into the CLI)
        self._attached_images: list[Path] = []
        self._image_counter = 0

        # Voice mode state (protected by _voice_lock for cross-thread access)
        self._voice_lock = threading.Lock()
        self._voice_mode = False  # Whether voice mode is enabled
        self._voice_tts = False  # Whether TTS output is enabled
        self._voice_recorder = None  # AudioRecorder instance (lazy init)
        self._voice_recording = False  # Whether currently recording
        self._voice_processing = False  # Whether STT is in progress
        self._voice_continuous = False  # Whether to auto-restart after agent responds
        self._voice_tts_done = threading.Event()  # Signals TTS playback finished
        self._voice_tts_done.set()  # Initially "done" (no TTS pending)

        # Register callbacks so terminal_tool prompts route through our UI
        set_sudo_password_callback(self._sudo_password_callback)
        set_approval_callback(self._approval_callback)
        set_secret_capture_callback(self._secret_capture_callback)

        # Ensure tirith security scanner is available (downloads if needed).
        # Warn the user if tirith is enabled in config but not available,
        # so they know command security scanning is degraded.
        try:
            from tools.tirith_security import ensure_installed

            tirith_path = ensure_installed(log_failures=False)
            if tirith_path is None:
                security_cfg = self.config.get("security", {}) or {}
                tirith_enabled = security_cfg.get("tirith_enabled", True)
                if tirith_enabled:
                    _cprint(
                        f"  {_DIM}WARN tirith security scanner enabled but not available "
                        f"- command scanning will use pattern matching only{_RST}"
                    )
        except Exception:
            # Non-fatal - fail-open at scan time if unavailable
            logger.debug("Ignored exception in run", exc_info=True)

        # Key bindings for the input area
        kb = KeyBindings()

        @kb.add("enter")
        def handle_enter(event):
            """Handle Enter key - submit input.

            Routes to the correct queue based on active UI state:
            - Sudo password prompt: password goes to sudo response queue
            - Approval selection: selected choice goes to approval response queue
            - Clarify freetext mode: answer goes to the clarify response queue
            - Clarify choice mode: selected choice goes to the clarify response queue
            - Agent running: goes to _interrupt_queue (chat() monitors this)
            - Agent idle: goes to _pending_input (process_loop monitors this)
            Commands (starting with /) always go to _pending_input so they're
            handled as commands, not sent as interrupt text to the agent.
            """
            # --- Sudo password prompt: submit the typed password ---
            if self._sudo_state:
                text = event.app.current_buffer.text
                self._sudo_state["response_queue"].put(text)
                self._sudo_state = None
                event.app.invalidate()
                return

            # --- Secret prompt: submit the typed secret ---
            if self._secret_state:
                text = event.app.current_buffer.text
                self._submit_secret_response(text)
                event.app.current_buffer.reset()
                event.app.invalidate()
                return

            # --- Approval selection: confirm the highlighted choice ---
            if self._approval_state:
                self._handle_approval_selection()
                event.app.invalidate()
                return

            # --- /model picker modal ---
            if self._model_picker_state:
                self._handle_model_picker_selection()
                event.app.invalidate()
                return

            # --- Clarify freetext mode: user typed their own answer ---
            if self._clarify_freetext and self._clarify_state:
                text = event.app.current_buffer.text.strip()
                if text:
                    self._clarify_state["response_queue"].put(text)
                    self._clarify_state = None
                    self._clarify_freetext = False
                    event.app.current_buffer.reset()
                    event.app.invalidate()
                return

            # --- Clarify choice mode: confirm the highlighted selection ---
            if self._clarify_state and not self._clarify_freetext:
                state = self._clarify_state
                selected = state["selected"]
                choices = state.get("choices") or []
                if selected < len(choices):
                    state["response_queue"].put(choices[selected])
                    self._clarify_state = None
                    event.app.invalidate()
                else:
                    # "Other" selected → switch to freetext
                    self._clarify_freetext = True
                    event.app.invalidate()
                return

            # --- Normal input routing ---
            text = event.app.current_buffer.text.strip()
            has_images = bool(self._attached_images)
            if text or has_images:
                self._dismiss_welcome_logo()
                event.app.invalidate()

                # Handle /model directly on the UI thread so interactive pickers
                # can safely use prompt_toolkit terminal handoff helpers.
                if self._should_handle_model_command_inline(
                    text, has_images=has_images
                ):
                    if not self.process_command(text):
                        self._should_exit = True
                        if event.app.is_running:
                            event.app.exit()
                    event.app.current_buffer.reset(append_to_history=True)
                    return

                # Snapshot and clear attached images
                images = list(self._attached_images)
                self._attached_images.clear()
                event.app.invalidate()
                # Bundle text + images as a tuple when images are present
                payload = (text, images) if images else text
                if self._agent_running and not (
                    text and _pkg()._looks_like_slash_command(text)
                ):
                    if self.busy_input_mode == "queue":
                        # Queue for the next turn instead of interrupting
                        self._pending_input.put(payload)
                        preview = (
                            text
                            if text
                            else f"[{len(images)} image{'s' if len(images) != 1 else ''} attached]"
                        )
                        _cprint(
                            f"  Queued for the next turn: {preview[:80]}{'...' if len(preview) > 80 else ''}"
                        )
                    else:
                        self._interrupt_queue.put(payload)
                        # Debug: log to file when message enters interrupt queue
                        try:
                            _dbg = _pkg()._spark_home / "interrupt_debug.log"
                            with open(_dbg, "a") as _f:
                                import time as _t

                                _f.write(
                                    f"{_t.strftime('%H:%M:%S')} ENTER: queued interrupt msg={str(payload)[:60]!r}, "
                                    f"agent_running={self._agent_running}\n"
                                )
                        except Exception:
                            logger.debug("Ignoring error in handle_enter()", exc_info=True)
                else:
                    self._pending_input.put(payload)
                event.app.current_buffer.reset(append_to_history=True)

        @kb.add("escape", "enter")
        def handle_alt_enter(event):
            """Alt+Enter inserts a newline for multi-line input."""
            event.current_buffer.insert_text("\n")

        @kb.add("c-j")
        def handle_ctrl_enter(event):
            """Ctrl+Enter (c-j) inserts a newline. Most terminals send c-j for Ctrl+Enter."""
            event.current_buffer.insert_text("\n")

        @kb.add("tab", eager=True)
        def handle_tab(event):
            """Tab: accept completion, auto-suggestion, or start completions.

            Priority:
            1. Completion menu open → accept selected completion
            2. Ghost text suggestion available → accept auto-suggestion
            3. Otherwise → start completion menu

            After accepting a provider like 'anthropic:', the completion menu
            closes and complete_while_typing doesn't fire (no keystroke).
            This binding re-triggers completions so stage-2 models appear
            immediately.
            """
            buf = event.current_buffer
            if buf.complete_state:
                # Completion menu is open - accept the selection
                completion = buf.complete_state.current_completion
                if completion is None:
                    # Menu open but nothing selected - select first then grab it
                    buf.go_to_completion(0)
                    completion = (
                        buf.complete_state and buf.complete_state.current_completion
                    )
                if completion is None:
                    return
                # Accept the selected completion
                buf.apply_completion(completion)
            elif buf.suggestion and buf.suggestion.text:
                # No completion menu, but there's a ghost text auto-suggestion - accept it
                buf.insert_text(buf.suggestion.text)
            else:
                # No menu and no suggestion - start completions from scratch
                buf.start_completion()

        # --- Clarify tool: arrow-key navigation for multiple-choice questions ---

        @kb.add(
            "up",
            filter=Condition(
                lambda: bool(self._clarify_state) and not self._clarify_freetext
            ),
        )
        def clarify_up(event):
            """Move selection up in clarify choices."""
            if self._clarify_state:
                self._clarify_state["selected"] = max(
                    0, self._clarify_state["selected"] - 1
                )
                event.app.invalidate()

        @kb.add(
            "down",
            filter=Condition(
                lambda: bool(self._clarify_state) and not self._clarify_freetext
            ),
        )
        def clarify_down(event):
            """Move selection down in clarify choices."""
            if self._clarify_state:
                choices = self._clarify_state.get("choices") or []
                max_idx = len(choices)  # last index is the "Other" option
                self._clarify_state["selected"] = min(
                    max_idx, self._clarify_state["selected"] + 1
                )
                event.app.invalidate()

        # --- Dangerous command approval: arrow-key navigation ---

        @kb.add("up", filter=Condition(lambda: bool(self._approval_state)))
        def approval_up(event):
            if self._approval_state:
                self._approval_state["selected"] = max(
                    0, self._approval_state["selected"] - 1
                )
                event.app.invalidate()

        @kb.add("down", filter=Condition(lambda: bool(self._approval_state)))
        def approval_down(event):
            if self._approval_state:
                max_idx = len(self._approval_state["choices"]) - 1
                self._approval_state["selected"] = min(
                    max_idx, self._approval_state["selected"] + 1
                )
                event.app.invalidate()

        # --- /model picker: arrow-key navigation ---
        @kb.add("up", filter=Condition(lambda: bool(self._model_picker_state)))
        def model_picker_up(event):
            if self._model_picker_state:
                self._model_picker_state["selected"] = max(
                    0, self._model_picker_state.get("selected", 0) - 1
                )
                event.app.invalidate()

        @kb.add("down", filter=Condition(lambda: bool(self._model_picker_state)))
        def model_picker_down(event):
            state = self._model_picker_state
            if not state:
                return
            if state.get("stage") == "provider":
                max_idx = len(state.get("providers") or [])
            else:
                max_idx = len(state.get("model_list") or []) + 1
            state["selected"] = min(max_idx, state.get("selected", 0) + 1)
            event.app.invalidate()

        # --- History navigation: up/down browse history in normal input mode ---
        # The TextArea is multiline, so by default up/down only move the cursor.
        # Buffer.auto_up/auto_down handle both: cursor movement when multi-line,
        # history browsing when on the first/last line (or single-line input).
        _normal_input = Condition(
            lambda: (
                not self._clarify_state
                and not self._approval_state
                and not self._sudo_state
                and not self._secret_state
                and not self._model_picker_state
            )
        )

        @kb.add("up", filter=_normal_input)
        def history_up(event):
            """Up arrow: browse history when on first line, else move cursor up."""
            event.app.current_buffer.auto_up(count=event.arg)

        @kb.add("down", filter=_normal_input)
        def history_down(event):
            """Down arrow: browse history when on last line, else move cursor down."""
            event.app.current_buffer.auto_down(count=event.arg)

        @kb.add("c-c")
        def handle_ctrl_c(event):
            """Handle Ctrl+C - cancel interactive prompts, interrupt agent, or exit.

            Priority:
            0. Cancel active voice recording
            1. Cancel active sudo/approval/clarify prompt
            2. Interrupt the running agent (first press)
            3. Force exit (second press within 2s, or when idle)
            """
            import time as _time

            now = _time.time()

            # Cancel active voice recording.
            # Run cancel() in a background thread to prevent blocking the
            # event loop if AudioRecorder._lock or CoreAudio takes time.
            _should_cancel_voice = False
            _recorder_ref = None
            with cli_ref._voice_lock:
                if cli_ref._voice_recording and cli_ref._voice_recorder:
                    _recorder_ref = cli_ref._voice_recorder
                    cli_ref._voice_recording = False
                    cli_ref._voice_continuous = False
                    _should_cancel_voice = True
            if _should_cancel_voice:
                _cprint(f"\n{_DIM}Recording cancelled.{_RST}")
                threading.Thread(target=_recorder_ref.cancel, daemon=True).start()
                event.app.invalidate()
                return

            # Cancel sudo prompt
            if self._sudo_state:
                self._sudo_state["response_queue"].put("")
                self._sudo_state = None
                event.app.invalidate()
                return

            # Cancel secret prompt
            if self._secret_state:
                self._cancel_secret_capture()
                event.app.current_buffer.reset()
                event.app.invalidate()
                return

            # Cancel approval prompt (deny)
            if self._approval_state:
                self._approval_state["response_queue"].put("deny")
                self._approval_state = None
                event.app.invalidate()
                return

            # Cancel /model picker
            if self._model_picker_state:
                self._close_model_picker()
                event.app.current_buffer.reset()
                event.app.invalidate()
                return

            # Cancel clarify prompt
            if self._clarify_state:
                self._clarify_state["response_queue"].put(
                    "The user cancelled. Use your best judgement to proceed."
                )
                self._clarify_state = None
                self._clarify_freetext = False
                event.app.current_buffer.reset()
                event.app.invalidate()
                return

            if self._agent_running and self.agent:
                if now - self._last_ctrl_c_time < 2.0:
                    print("\n⚡ Force exiting...")
                    self._should_exit = True
                    event.app.exit()
                    return

                self._last_ctrl_c_time = now
                print("\n⚡ Interrupting agent... (press Ctrl+C again to force exit)")
                self.agent.interrupt()
            else:
                # If there's text or images, clear them (like bash).
                # If everything is already empty, exit.
                if event.app.current_buffer.text or self._attached_images:
                    event.app.current_buffer.reset()
                    self._attached_images.clear()
                    event.app.invalidate()
                else:
                    self._should_exit = True
                    event.app.exit()

        @kb.add("escape", filter=Condition(lambda: self._agent_running), eager=False)
        def handle_escape_interrupt(event):
            """Esc: soft-interrupt the running agent, preserving the partial response.

            Filtered to only fire while the agent is running so it never
            interferes with escape-prefixed sequences (arrows, alt-combos) at
            the normal prompt. Unlike Ctrl+C it never escalates to force-exit;
            the partial response is kept and the user drops back to the prompt
            where typing + Enter redirects the agent.
            """

            if self._agent_running and self.agent:
                # Don't prime the double-Ctrl+C force-exit window.
                self._last_ctrl_c_time = 0
                print(
                    f"\n{_DIM}⏸ interrupted — type to redirect, Enter to resume{_RST}"
                )
                self.agent.interrupt()
                event.app.invalidate()

        @kb.add("c-d")
        def handle_ctrl_d(event):
            """Handle Ctrl+D - exit."""
            self._should_exit = True
            event.app.exit()

        @kb.add("c-z")
        def handle_ctrl_z(event):
            """Handle Ctrl+Z - suspend process to background (Unix only)."""
            import sys

            if sys.platform == "win32":
                _cprint(f"\n{_DIM}Suspend (Ctrl+Z) is not supported on Windows.{_RST}")
                event.app.invalidate()
                return
            import os
            import signal as _sig

            from prompt_toolkit.application import run_in_terminal

            from spark_cli.skin_engine import get_active_skin

            agent_name = get_active_skin().get_branding("agent_name", "Spark Agent")
            msg = f"\n{agent_name} has been suspended. Run `fg` to bring {agent_name} back."

            def _suspend():
                os.write(1, msg.encode())
                os.kill(0, _sig.SIGTSTP)

            run_in_terminal(_suspend)

        # Voice push-to-talk key: configurable via config.yaml (voice.record_key)
        # Default: Ctrl+B (avoids conflict with Ctrl+R readline reverse-search)
        # Config uses "ctrl+b" format; prompt_toolkit expects "c-b" format.
        try:
            from spark_cli.config import load_config

            _raw_key = load_config().get("voice", {}).get("record_key", "ctrl+b")
            _voice_key = _raw_key.lower().replace("ctrl+", "c-").replace("alt+", "a-")
        except Exception:
            _voice_key = "c-b"

        @kb.add(_voice_key)
        def handle_voice_record(event):
            """Toggle voice recording when voice mode is active.

            IMPORTANT: This handler runs in prompt_toolkit's event-loop thread.
            Any blocking call here (locks, sd.wait, disk I/O) freezes the
            entire UI.  All heavy work is dispatched to daemon threads.
            """
            if not cli_ref._voice_mode:
                return
            # Always allow STOPPING a recording (even when agent is running)
            if cli_ref._voice_recording:
                # Manual stop via push-to-talk key: stop continuous mode
                with cli_ref._voice_lock:
                    cli_ref._voice_continuous = False
                # Flag clearing is handled atomically inside _voice_stop_and_transcribe
                event.app.invalidate()
                threading.Thread(
                    target=cli_ref._voice_stop_and_transcribe,
                    daemon=True,
                ).start()
            else:
                # Guard: don't START recording during agent run or interactive prompts
                if cli_ref._agent_running:
                    return
                if (
                    cli_ref._clarify_state
                    or cli_ref._sudo_state
                    or cli_ref._approval_state
                ):
                    return
                # Guard: don't start while a previous stop/transcribe cycle is
                # still running - recorder.stop() holds AudioRecorder._lock and
                # start() would block the event-loop thread waiting for it.
                if cli_ref._voice_processing:
                    return

                # Interrupt TTS if playing, so user can start talking.
                # stop_playback() is fast (just terminates a subprocess).
                if not cli_ref._voice_tts_done.is_set():
                    try:
                        from tools.voice_mode import stop_playback

                        stop_playback()
                        cli_ref._voice_tts_done.set()
                    except Exception:
                        logger.debug("Ignoring error in handle_voice_record()", exc_info=True)

                with cli_ref._voice_lock:
                    cli_ref._voice_continuous = True

                # Dispatch to a daemon thread so play_beep(sd.wait),
                # AudioRecorder.start(lock acquire), and config I/O
                # never block the prompt_toolkit event loop.
                def _start_recording():
                    try:
                        cli_ref._voice_start_recording()
                        if hasattr(cli_ref, "_app") and cli_ref._app:
                            cli_ref._app.invalidate()
                    except Exception as e:
                        _cprint(f"\n{_DIM}Voice recording failed: {e}{_RST}")

                threading.Thread(target=_start_recording, daemon=True).start()
                event.app.invalidate()

        from prompt_toolkit.keys import Keys

        @kb.add(Keys.BracketedPaste, eager=True)
        def handle_paste(event):
            """Handle terminal paste - detect clipboard images.

            When the terminal supports bracketed paste, Ctrl+V / Cmd+V
            triggers this with the pasted text. We only auto-attach a
            clipboard image for image-only/empty paste gestures so text
            pastes and dictation do not accidentally attach stale images.

            Large pastes (5+ lines) are collapsed to a file reference
            placeholder while preserving any existing user text in the
            buffer.
            """
            pasted_text = event.data or ""
            # Normalise line endings - Windows \r\n and old Mac \r both become \n
            # so the 5-line collapse threshold and display are consistent.
            pasted_text = pasted_text.replace("\r\n", "\n").replace("\r", "\n")
            if (
                _should_auto_attach_clipboard_image_on_paste(pasted_text)
                and self._try_attach_clipboard_image()
            ):
                event.app.invalidate()
            if pasted_text:
                # Sanitize surrogate characters (e.g. from Word/Google Docs paste) before writing
                from core.run_agent import _sanitize_surrogates

                pasted_text = _sanitize_surrogates(pasted_text)
                line_count = pasted_text.count("\n")
                buf = event.current_buffer
                if line_count >= 5 and not buf.text.strip().startswith("/"):
                    _paste_counter[0] += 1
                    paste_dir = _pkg()._spark_home / "pastes"
                    paste_dir.mkdir(parents=True, exist_ok=True)
                    paste_file = (
                        paste_dir
                        / f"paste_{_paste_counter[0]}_{datetime.now().strftime('%H%M%S')}.txt"
                    )
                    paste_file.write_text(pasted_text, encoding="utf-8")
                    placeholder = f"[Pasted text #{_paste_counter[0]}: {line_count + 1} lines \u2192 {paste_file}]"
                    prefix = ""
                    if (
                        buf.cursor_position > 0
                        and buf.text[buf.cursor_position - 1] != "\n"
                    ):
                        prefix = "\n"
                    _paste_just_collapsed[0] = True
                    buf.insert_text(prefix + placeholder)
                else:
                    buf.insert_text(pasted_text)

        @kb.add("c-v")
        def handle_ctrl_v(event):
            """Fallback image paste for terminals without bracketed paste.

            On Linux terminals (GNOME Terminal, Konsole, etc.), Ctrl+V
            sends raw byte 0x16 instead of triggering a paste.  This
            binding catches that and checks the clipboard for images.
            On terminals that DO intercept Ctrl+V for paste (macOS
            Terminal, iTerm2, VSCode, Windows Terminal), the bracketed
            paste handler fires instead and this binding never triggers.
            """
            if self._try_attach_clipboard_image():
                event.app.invalidate()

        @kb.add("escape", "v")
        def handle_alt_v(event):
            """Alt+V - paste image from clipboard.

            Alt key combos pass through all terminal emulators (sent as
            ESC + key), unlike Ctrl+V which terminals intercept for text
            paste.  This is the reliable way to attach clipboard images
            on WSL2, VSCode, and any terminal over SSH where Ctrl+V
            can't reach the application for image-only clipboard.
            """
            if self._try_attach_clipboard_image():
                event.app.invalidate()
            else:
                # No image found - show a hint
                pass  # silent when no image (avoid noise on accidental press)

        # Dynamic prompt: shows Spark symbol when agent is working,
        # or answer prompt when clarify freetext mode is active.
        cli_ref = self

        def get_prompt():
            return cli_ref._get_tui_prompt_fragments()

        # Create the input area with multiline (shift+enter), autocomplete, and paste handling
        from prompt_toolkit.auto_suggest import AutoSuggestFromHistory

        _completer = SlashCommandCompleter(
            skill_commands_provider=lambda: _pkg()._skill_commands,
            command_filter=cli_ref._command_available,
        )
        input_area = TextArea(
            height=Dimension(min=1, max=8, preferred=1),
            prompt=get_prompt,
            style="class:input-area",
            multiline=True,
            wrap_lines=True,
            read_only=Condition(lambda: bool(cli_ref._command_running)),
            history=_pkg()._SessionScopedFileHistory(str(self._history_file)),
            completer=_completer,
            complete_while_typing=True,
            auto_suggest=SlashCommandAutoSuggest(
                history_suggest=AutoSuggestFromHistory(),
                completer=_completer,
            ),
        )

        # Dynamic height: accounts for both explicit newlines AND visual
        # wrapping of long lines so the input area always fits its content.
        def _input_height():
            try:
                from prompt_toolkit.application import get_app
                from prompt_toolkit.utils import get_cwidth

                doc = input_area.buffer.document
                prompt_width = max(2, get_cwidth(self._get_tui_prompt_text()))
                try:
                    available_width = get_app().output.get_size().columns - prompt_width
                except Exception:
                    available_width = (
                        shutil.get_terminal_size((80, 24)).columns - prompt_width
                    )
                if available_width < 10:
                    available_width = 40
                visual_lines = 0
                for line in doc.lines:
                    # Each logical line takes at least 1 visual row; long lines wrap.
                    # Use prompt_toolkit's cell width so CJK wide characters count as 2.
                    line_width = get_cwidth(line)
                    if line_width <= 0:
                        visual_lines += 1
                    else:
                        visual_lines += max(
                            1, -(-line_width // available_width)
                        )  # ceil division
                return min(max(visual_lines, 1), 8)
            except Exception:
                return 1

        input_area.window.height = _input_height

        # Paste collapsing: detect large pastes and save to temp file
        _paste_counter = [0]
        _prev_text_len = [0]
        _prev_newline_count = [0]
        _paste_just_collapsed = [False]

        def _on_text_changed(buf):
            """Detect large pastes and collapse them to a file reference.

            When bracketed paste is available, handle_paste collapses
            large pastes directly.  This handler is a fallback for
            terminals without bracketed paste support.

            Two heuristics (either triggers collapse):
            1. Many characters added at once (chars_added > 1) - works
               when the terminal delivers the paste in one event-loop tick.
            2. Newline count jumped by 4+ in a single text-change event -
               catches terminals that feed characters individually but
               still batch newlines.  Alt+Enter only adds 1 newline per
               event so it never triggers this.
            """
            text = buf.text
            chars_added = len(text) - _prev_text_len[0]
            _prev_text_len[0] = len(text)
            if _paste_just_collapsed[0]:
                _paste_just_collapsed[0] = False
                _prev_newline_count[0] = text.count("\n")
                return
            line_count = text.count("\n")
            newlines_added = line_count - _prev_newline_count[0]
            _prev_newline_count[0] = line_count
            is_paste = chars_added > 1 or newlines_added >= 4
            if line_count >= 5 and is_paste and not text.startswith("/"):
                _paste_counter[0] += 1
                # Save to temp file
                paste_dir = _pkg()._spark_home / "pastes"
                paste_dir.mkdir(parents=True, exist_ok=True)
                paste_file = (
                    paste_dir
                    / f"paste_{_paste_counter[0]}_{datetime.now().strftime('%H%M%S')}.txt"
                )
                paste_file.write_text(text, encoding="utf-8")
                # Replace buffer with compact reference
                _paste_just_collapsed[0] = True
                buf.text = f"[Pasted text #{_paste_counter[0]}: {line_count + 1} lines \u2192 {paste_file}]"
                buf.cursor_position = len(buf.text)

        input_area.buffer.on_text_changed += _on_text_changed

        # --- Input processors for password masking and inline placeholder ---

        # Mask input with '*' when the sudo password prompt is active
        input_area.control.input_processors.append(
            ConditionalProcessor(
                PasswordProcessor(),
                filter=Condition(
                    lambda: bool(cli_ref._sudo_state) or bool(cli_ref._secret_state)
                ),
            )
        )

        class _PlaceholderProcessor(Processor):
            """Render grayed-out placeholder text inside the input when empty."""

            def __init__(self, get_text):
                self._get_text = get_text

            def apply_transformation(self, ti):
                if not ti.document.text and ti.lineno == 0:
                    text = self._get_text()
                    if text:
                        # Append after existing fragments (preserves the ❯ prompt)
                        return Transformation(
                            fragments=ti.fragments + [("class:placeholder", text)]
                        )
                return Transformation(fragments=ti.fragments)

        def _get_placeholder():
            if cli_ref._voice_recording:
                return "recording... Ctrl+B to stop, Ctrl+C to cancel"
            if cli_ref._voice_processing:
                return "transcribing..."
            if cli_ref._sudo_state:
                return "type password (hidden), Enter to skip"
            if cli_ref._secret_state:
                return "type secret (hidden), Enter to skip"
            if cli_ref._approval_state:
                return ""
            if cli_ref._clarify_freetext:
                return "type your answer here and press Enter"
            if cli_ref._clarify_state:
                return ""
            if cli_ref._command_running:
                frame = cli_ref._command_spinner_frame()
                status = cli_ref._command_status or "Processing command..."
                return f"{frame} {status}"
            if cli_ref._agent_running:
                return "type a message + Enter to interrupt, Ctrl+C to cancel"
            if cli_ref._voice_mode:
                return "type or Ctrl+B to record"
            # Idle: surface the multiline affordance (Enter sends, Alt+Enter newline).
            return "type a message — Enter to send, Alt+Enter for newline"

        input_area.control.input_processors.append(
            _PlaceholderProcessor(_get_placeholder)
        )

        # Hint line above input: shown only for interactive prompts that need
        # extra instructions (sudo countdown, approval navigation, clarify).
        # The agent-running interrupt hint is now an inline placeholder above.
        def get_hint_text():
            import time as _time

            if cli_ref._sudo_state:
                remaining = max(0, int(cli_ref._sudo_deadline - _time.monotonic()))
                return [
                    ("class:hint", "  password hidden - Enter to skip"),
                    ("class:clarify-countdown", f"  ({remaining}s)"),
                ]

            if cli_ref._secret_state:
                remaining = max(0, int(cli_ref._secret_deadline - _time.monotonic()))
                return [
                    ("class:hint", "  secret hidden - Enter to skip"),
                    ("class:clarify-countdown", f"  ({remaining}s)"),
                ]

            if cli_ref._approval_state:
                remaining = max(0, int(cli_ref._approval_deadline - _time.monotonic()))
                return [
                    ("class:hint", "  ↑/↓ to select, Enter to confirm"),
                    ("class:clarify-countdown", f"  ({remaining}s)"),
                ]

            if cli_ref._clarify_state:
                remaining = max(0, int(cli_ref._clarify_deadline - _time.monotonic()))
                countdown = f"  ({remaining}s)" if cli_ref._clarify_deadline else ""
                if cli_ref._clarify_freetext:
                    return [
                        ("class:hint", "  type your answer and press Enter"),
                        ("class:clarify-countdown", countdown),
                    ]
                return [
                    ("class:hint", "  ↑/↓ to select, Enter to confirm"),
                    ("class:clarify-countdown", countdown),
                ]

            if cli_ref._command_running:
                frame = cli_ref._command_spinner_frame()
                return [
                    (
                        "class:hint",
                        f"  {frame} command in progress - input temporarily disabled",
                    ),
                ]

            return []

        def get_hint_height():
            if (
                cli_ref._sudo_state
                or cli_ref._secret_state
                or cli_ref._approval_state
                or cli_ref._clarify_state
                or cli_ref._command_running
            ):
                return 1
            # Keep a spacer while the agent runs on roomy terminals, but reclaim
            # the row on narrow/mobile screens where every line matters.
            return cli_ref._agent_spacer_height()

        def get_spinner_text():
            import time as _time

            txt = cli_ref._spinner_text
            if not txt:
                return []

            now = _time.monotonic()

            # Braille spinner frame (10 fps)
            spin_frame = _pkg()._COMMAND_SPINNER_FRAMES[
                int(now * 10) % len(_pkg()._COMMAND_SPINNER_FRAMES)
            ]

            # Rotating status verb — changes every _AGENT_VERB_INTERVAL seconds
            verb_idx = int(now / _pkg()._AGENT_VERB_INTERVAL) % len(_pkg()._AGENT_STATUS_VERBS)
            verb = _pkg()._AGENT_STATUS_VERBS[verb_idx]

            # Elapsed timer while a tool is running
            t0 = cli_ref._tool_start_time
            if t0 > 0:
                elapsed = now - t0
                if elapsed >= 60:
                    _m, _s = int(elapsed // 60), int(elapsed % 60)
                    elapsed_str = f"  ({_m}m {_s}s)"
                else:
                    elapsed_str = f"  ({elapsed:.1f}s)"
            else:
                elapsed_str = ""

            return [("class:hint", f"  {spin_frame} {verb}{elapsed_str}")]

        def get_spinner_height():
            return cli_ref._spinner_widget_height()

        spinner_widget = Window(
            content=FormattedTextControl(get_spinner_text),
            height=get_spinner_height,
        )

        spacer = Window(
            content=FormattedTextControl(get_hint_text),
            height=get_hint_height,
        )

        # --- Clarify tool: dynamic display widget for questions + choices ---

        def _panel_box_width(
            title: str,
            content_lines: list[str],
            min_width: int = 46,
            max_width: int = 76,
        ) -> int:
            """Choose a stable panel width wide enough for the title and content."""
            term_cols = shutil.get_terminal_size((100, 20)).columns
            longest = max(
                [len(title)] + [len(line) for line in content_lines] + [min_width - 4]
            )
            inner = min(
                max(longest + 4, min_width - 2), max_width - 2, max(24, term_cols - 6)
            )
            return (
                inner + 2
            )  # account for the single leading/trailing spaces inside borders

        def _wrap_panel_text(
            text: str, width: int, subsequent_indent: str = ""
        ) -> list[str]:
            wrapped = textwrap.wrap(
                text,
                width=max(8, width),
                break_long_words=False,
                break_on_hyphens=False,
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

        def _get_clarify_display():
            """Build styled text for the clarify question/choices panel."""
            state = cli_ref._clarify_state
            if not state:
                return []

            question = state["question"]
            choices = state.get("choices") or []
            selected = state.get("selected", 0)
            preview_lines = _wrap_panel_text(question, 60)
            for i, choice in enumerate(choices):
                prefix = (
                    "❯ " if i == selected and not cli_ref._clarify_freetext else "  "
                )
                preview_lines.extend(
                    _wrap_panel_text(f"{prefix}{choice}", 60, subsequent_indent="  ")
                )
            other_label = (
                "❯ Other (type below)"
                if cli_ref._clarify_freetext
                else "❯ Other (type your answer)"
                if selected == len(choices)
                else "  Other (type your answer)"
            )
            preview_lines.extend(
                _wrap_panel_text(other_label, 60, subsequent_indent="  ")
            )
            box_width = _panel_box_width("Spark needs your input", preview_lines)
            inner_text_width = max(8, box_width - 2)

            lines = []
            # Box top border
            lines.append(("class:clarify-border", "+- "))
            lines.append(("class:clarify-title", "Spark needs your input"))
            lines.append(
                (
                    "class:clarify-border",
                    " "
                    + ("-" * max(0, box_width - len("Spark needs your input") - 3))
                    + "+\n",
                )
            )
            _append_blank_panel_line(lines, "class:clarify-border", box_width)

            # Question text
            for wrapped in _wrap_panel_text(question, inner_text_width):
                _append_panel_line(
                    lines,
                    "class:clarify-border",
                    "class:clarify-question",
                    wrapped,
                    box_width,
                )
            _append_blank_panel_line(lines, "class:clarify-border", box_width)

            if cli_ref._clarify_freetext and not choices:
                guidance = "Type your answer in the prompt below, then press Enter."
                for wrapped in _wrap_panel_text(guidance, inner_text_width):
                    _append_panel_line(
                        lines,
                        "class:clarify-border",
                        "class:clarify-choice",
                        wrapped,
                        box_width,
                    )
                _append_blank_panel_line(lines, "class:clarify-border", box_width)

            if choices:
                # Multiple-choice mode: show selectable options
                for i, choice in enumerate(choices):
                    style = (
                        "class:clarify-selected"
                        if i == selected and not cli_ref._clarify_freetext
                        else "class:clarify-choice"
                    )
                    prefix = (
                        "❯ "
                        if i == selected and not cli_ref._clarify_freetext
                        else "  "
                    )
                    wrapped_lines = _wrap_panel_text(
                        f"{prefix}{choice}", inner_text_width, subsequent_indent="  "
                    )
                    for wrapped in wrapped_lines:
                        _append_panel_line(
                            lines, "class:clarify-border", style, wrapped, box_width
                        )

                # "Other" option (5th line, only shown when choices exist)
                other_idx = len(choices)
                if selected == other_idx and not cli_ref._clarify_freetext:
                    other_style = "class:clarify-selected"
                    other_label = "❯ Other (type your answer)"
                elif cli_ref._clarify_freetext:
                    other_style = "class:clarify-active-other"
                    other_label = "❯ Other (type below)"
                else:
                    other_style = "class:clarify-choice"
                    other_label = "  Other (type your answer)"
                for wrapped in _wrap_panel_text(
                    other_label, inner_text_width, subsequent_indent="  "
                ):
                    _append_panel_line(
                        lines, "class:clarify-border", other_style, wrapped, box_width
                    )

            _append_blank_panel_line(lines, "class:clarify-border", box_width)
            lines.append(("class:clarify-border", "+" + ("-" * box_width) + "+\n"))
            return lines

        clarify_widget = ConditionalContainer(
            Window(
                FormattedTextControl(_get_clarify_display),
                wrap_lines=True,
            ),
            filter=Condition(lambda: cli_ref._clarify_state is not None),
        )

        # --- Sudo password: display widget ---

        def _get_sudo_display():
            state = cli_ref._sudo_state
            if not state:
                return []
            title = "🔐 Sudo Password Required"
            body = "Enter password below (hidden), or press Enter to skip"
            box_width = _panel_box_width(title, [body])
            lines = []
            lines.append(("class:sudo-border", "+- "))
            lines.append(("class:sudo-title", title))
            lines.append(
                (
                    "class:sudo-border",
                    " " + ("-" * max(0, box_width - len(title) - 3)) + "+\n",
                )
            )
            _append_blank_panel_line(lines, "class:sudo-border", box_width)
            _append_panel_line(
                lines, "class:sudo-border", "class:sudo-text", body, box_width
            )
            _append_blank_panel_line(lines, "class:sudo-border", box_width)
            lines.append(("class:sudo-border", "+" + ("-" * box_width) + "+\n"))
            return lines

        sudo_widget = ConditionalContainer(
            Window(
                FormattedTextControl(_get_sudo_display),
                wrap_lines=True,
            ),
            filter=Condition(lambda: cli_ref._sudo_state is not None),
        )

        def _get_secret_display():
            state = cli_ref._secret_state
            if not state:
                return []

            title = "🔑 Skill Setup Required"
            prompt = (
                state.get("prompt")
                or f"Enter value for {state.get('var_name', 'secret')}"
            )
            metadata = state.get("metadata") or {}
            help_text = metadata.get("help")
            body = "Enter secret below (hidden), or press Enter to skip"
            content_lines = [prompt, body]
            if help_text:
                content_lines.insert(1, str(help_text))
            box_width = _panel_box_width(title, content_lines)
            lines = []
            lines.append(("class:sudo-border", "+- "))
            lines.append(("class:sudo-title", title))
            lines.append(
                (
                    "class:sudo-border",
                    " " + ("-" * max(0, box_width - len(title) - 3)) + "+\n",
                )
            )
            _append_blank_panel_line(lines, "class:sudo-border", box_width)
            _append_panel_line(
                lines, "class:sudo-border", "class:sudo-text", prompt, box_width
            )
            if help_text:
                _append_panel_line(
                    lines,
                    "class:sudo-border",
                    "class:sudo-text",
                    str(help_text),
                    box_width,
                )
            _append_blank_panel_line(lines, "class:sudo-border", box_width)
            _append_panel_line(
                lines, "class:sudo-border", "class:sudo-text", body, box_width
            )
            _append_blank_panel_line(lines, "class:sudo-border", box_width)
            lines.append(("class:sudo-border", "+" + ("-" * box_width) + "+\n"))
            return lines

        secret_widget = ConditionalContainer(
            Window(
                FormattedTextControl(_get_secret_display),
                wrap_lines=True,
            ),
            filter=Condition(lambda: cli_ref._secret_state is not None),
        )

        # --- Dangerous command approval: display widget ---

        def _get_approval_display():
            return cli_ref._get_approval_display_fragments()

        approval_widget = ConditionalContainer(
            Window(
                FormattedTextControl(_get_approval_display),
                wrap_lines=True,
            ),
            filter=Condition(lambda: cli_ref._approval_state is not None),
        )

        # --- /model picker: display widget ---
        def _get_model_picker_display():
            state = cli_ref._model_picker_state
            if not state:
                return []
            stage = state.get("stage", "provider")
            if stage == "provider":
                title = "⚙ Model Picker - Select Provider"
                choices = []
                for p in state.get("providers") or []:
                    count = p.get("total_models", len(p.get("models", [])))
                    label = f"{p['name']} ({count} model{'s' if count != 1 else ''})"
                    if p.get("is_current"):
                        label += "  ← current"
                    choices.append(label)
                choices.append("Cancel")
                hint = f"Current: {state.get('current_model', 'unknown')} on {state.get('current_provider', 'unknown')}"
            else:
                provider_data = state.get("provider_data") or {}
                model_list = state.get("model_list") or []
                title = f"⚙ Model Picker - {provider_data.get('name', provider_data.get('slug', 'Provider'))}"
                choices = list(model_list) + ["← Back", "Cancel"]
                if model_list:
                    hint = f"Select a model ({len(model_list)} available)"
                else:
                    hint = "No models listed for this provider. Use Back or Cancel."

            box_width = _panel_box_width(
                title, [hint] + choices, min_width=46, max_width=84
            )
            inner_text_width = max(8, box_width - 6)
            lines = []
            lines.append(("class:clarify-border", "+- "))
            lines.append(("class:clarify-title", title))
            lines.append(
                (
                    "class:clarify-border",
                    " " + ("-" * max(0, box_width - len(title) - 3)) + "+\n",
                )
            )
            _append_blank_panel_line(lines, "class:clarify-border", box_width)
            _append_panel_line(
                lines, "class:clarify-border", "class:clarify-hint", hint, box_width
            )
            _append_blank_panel_line(lines, "class:clarify-border", box_width)
            selected = state.get("selected", 0)
            for idx, choice in enumerate(choices):
                style = (
                    "class:clarify-selected"
                    if idx == selected
                    else "class:clarify-choice"
                )
                prefix = "❯ " if idx == selected else "  "
                for wrapped in _wrap_panel_text(
                    prefix + choice, inner_text_width, subsequent_indent="  "
                ):
                    _append_panel_line(
                        lines, "class:clarify-border", style, wrapped, box_width
                    )
            _append_blank_panel_line(lines, "class:clarify-border", box_width)
            lines.append(("class:clarify-border", "+" + ("-" * box_width) + "+\n"))
            return lines

        model_picker_widget = ConditionalContainer(
            Window(
                FormattedTextControl(_get_model_picker_display),
                wrap_lines=True,
            ),
            filter=Condition(lambda: cli_ref._model_picker_state is not None),
        )

        # Horizontal rules above and below the input.
        # On narrow/mobile terminals we keep the top separator for structure but
        # hide the bottom one to recover a full row for conversation content.
        input_rule_top = Window(
            char="─",
            height=lambda: (
                0
                if cli_ref._show_welcome_logo
                else cli_ref._tui_input_rule_height("top")
            ),
            style="class:input-rule",
        )
        input_rule_bot = Window(
            char="─",
            height=lambda: (
                0
                if cli_ref._show_welcome_logo
                else cli_ref._tui_input_rule_height("bottom")
            ),
            style="class:input-rule",
        )

        # Image attachment indicator - shows badges like [ATTACH Image #1] above input
        cli_ref = self

        def _get_image_bar():
            if not cli_ref._attached_images:
                return []
            badges = _format_image_attachment_badges(
                cli_ref._attached_images,
                cli_ref._image_counter,
            )
            return [("class:image-badge", f" {badges} ")]

        image_bar = Window(
            content=FormattedTextControl(_get_image_bar),
            height=Condition(lambda: bool(cli_ref._attached_images)),
        )

        # Persistent voice mode status bar (visible only when voice mode is on)
        def _get_voice_status():
            return cli_ref._get_voice_status_fragments()

        voice_status_bar = ConditionalContainer(
            Window(
                FormattedTextControl(_get_voice_status),
                height=1,
            ),
            filter=Condition(
                lambda: cli_ref._voice_mode and not cli_ref._show_welcome_logo
            ),
        )

        status_bar = ConditionalContainer(
            Window(
                content=FormattedTextControl(
                    lambda: cli_ref._get_status_bar_fragments()
                ),
                height=1,
                # Prevent fragments that overflow the terminal width from
                # wrapping onto a second line, which causes the status bar to
                # appear duplicated (one full + one partial row) during long
                # sessions, especially on SSH where shutil.get_terminal_size
                # may return stale values.  _get_status_bar_fragments now reads
                # width from prompt_toolkit's own output object, so fragments
                # will always fit; wrap_lines=False is the belt-and-suspenders
                # guard against any future width mismatch.
                wrap_lines=False,
            ),
            filter=Condition(
                lambda: cli_ref._status_bar_visible and not cli_ref._show_welcome_logo
            ),
        )

        # Allow wrapper CLIs to register extra keybindings.
        self._register_extra_tui_keybindings(kb, input_area=input_area)

        # Layout: interactive prompt widgets + ruled input at bottom.
        # The sudo, approval, and clarify widgets appear above the input when
        # the corresponding interactive prompt is active.
        completions_menu = CompletionsMenu(max_height=12, scroll_offset=1)

        layout = Layout(
            HSplit(
                self._build_tui_layout_children(
                    sudo_widget=sudo_widget,
                    secret_widget=secret_widget,
                    approval_widget=approval_widget,
                    clarify_widget=clarify_widget,
                    model_picker_widget=model_picker_widget,
                    spinner_widget=spinner_widget,
                    spacer=spacer,
                    status_bar=status_bar,
                    input_rule_top=input_rule_top,
                    image_bar=image_bar,
                    input_area=input_area,
                    input_rule_bot=input_rule_bot,
                    voice_status_bar=voice_status_bar,
                    completions_menu=completions_menu,
                )
            )
        )

        # Style for the application
        self._tui_style_base = {
            "input-area": "#FFF8DC",
            "placeholder": "#555555 italic",
            "prompt": "#FFF8DC",
            "prompt-working": "#888888 italic",
            "hint": "#555555 italic",
            "welcome-line": "#FFF8DC",
            "welcome-tip": "#B8860B italic",
            "welcome-skills": "#FFD700 bold",
            "status-bar": "bg:#1a1a2e #C0C0C0",
            "status-bar-strong": "bg:#1a1a2e #FFD700 bold",
            "status-bar-dim": "bg:#1a1a2e #8B8682",
            "status-bar-good": "bg:#1a1a2e #8FBC8F bold",
            "status-bar-warn": "bg:#1a1a2e #FFD700 bold",
            "status-bar-bad": "bg:#1a1a2e #FF8C00 bold",
            "status-bar-critical": "bg:#1a1a2e #FF6B6B bold",
            # Horizontal rules around the input area
            "input-rule": "#555555",
            # Clipboard image attachment badges
            "image-badge": "#87CEEB bold",
            "completion-menu": "bg:#1a1a2e #FFF8DC",
            "completion-menu.completion": "bg:#1a1a2e #FFF8DC",
            "completion-menu.completion.current": "bg:#333355 #FFD700",
            "completion-menu.meta.completion": "bg:#1a1a2e #888888",
            "completion-menu.meta.completion.current": "bg:#333355 #FFBF00",
            # Clarify question panel
            "clarify-border": "#CD7F32",
            "clarify-title": "#FFD700 bold",
            "clarify-question": "#FFF8DC bold",
            "clarify-choice": "#AAAAAA",
            "clarify-selected": "#FFD700 bold",
            "clarify-active-other": "#FFD700 italic",
            "clarify-countdown": "#CD7F32",
            # Sudo password panel
            "sudo-prompt": "#FF6B6B bold",
            "sudo-border": "#CD7F32",
            "sudo-title": "#FF6B6B bold",
            "sudo-text": "#FFF8DC",
            # Dangerous command approval panel
            "approval-border": "#CD7F32",
            "approval-title": "#FF8C00 bold",
            "approval-desc": "#FFF8DC bold",
            "approval-cmd": "#AAAAAA italic",
            "approval-choice": "#AAAAAA",
            "approval-selected": "#FFD700 bold",
            # Voice mode
            "voice-prompt": "#87CEEB",
            "voice-recording": "#FF4444 bold",
            "voice-processing": "#FFA500 italic",
            "voice-status": "bg:#1a1a2e #87CEEB",
            "voice-status-recording": "bg:#1a1a2e #FF4444 bold",
        }
        style = PTStyle.from_dict(self._build_tui_style_dict())

        # Create the application
        app = Application(
            layout=layout,
            key_bindings=kb,
            style=style,
            full_screen=False,
            mouse_support=False,
            **({"cursor": _pkg()._STEADY_CURSOR} if _pkg()._STEADY_CURSOR is not None else {}),
        )
        self._app = app  # Store reference for clarify_callback

        # -- Fix ghost status-bar lines on terminal resize --------------
        # When the terminal shrinks (e.g. un-maximize), the emulator reflows
        # the previously-rendered full-width rows (status bar, input rules)
        # into multiple narrower rows.  prompt_toolkit's _on_resize handler
        # only cursor_up()s by the stored layout height, missing the extra
        # rows created by reflow - leaving ghost duplicates visible.
        #
        # Fix: before the standard erase, inflate _cursor_pos.y so the
        # cursor moves up far enough to cover the reflowed ghost content.
        _original_on_resize = app._on_resize

        def _resize_clear_ghosts():
            from prompt_toolkit.data_structures import Point as _Pt

            renderer = app.renderer
            try:
                old_size = renderer._last_size
                new_size = renderer.output.get_size()
                if (
                    old_size
                    and new_size.columns < old_size.columns
                    and new_size.columns > 0
                ):
                    reflow_factor = (
                        old_size.columns + new_size.columns - 1
                    ) // new_size.columns
                    last_h = (
                        renderer._last_screen.height if renderer._last_screen else 0
                    )
                    extra = last_h * (reflow_factor - 1)
                    if extra > 0:
                        renderer._cursor_pos = _Pt(
                            x=renderer._cursor_pos.x,
                            y=renderer._cursor_pos.y + extra,
                        )
            except Exception:
                # never break resize handling
                logger.debug("Ignored exception in _resize_clear_ghosts", exc_info=True)
            _original_on_resize()

        app._on_resize = _resize_clear_ghosts

        def spinner_loop():
            import time as _time

            last_idle_refresh = 0.0
            while not self._should_exit:
                if not self._app:
                    _time.sleep(0.1)
                    continue
                if self._command_running:
                    self._invalidate(min_interval=0.1)
                    _time.sleep(0.1)
                else:
                    now = _time.monotonic()
                    if now - last_idle_refresh >= 1.0:
                        last_idle_refresh = now
                        self._invalidate(min_interval=1.0)
                    _time.sleep(0.2)

        spinner_thread = threading.Thread(target=spinner_loop, daemon=True)
        spinner_thread.start()

        # Background thread to process inputs and run agent
        def process_loop():
            while not self._should_exit:
                try:
                    # Check for pending input with timeout
                    try:
                        user_input = self._pending_input.get(timeout=0.1)
                    except queue.Empty:
                        # Periodic config watcher - auto-reload MCP on mcp_servers change
                        if not self._agent_running:
                            self._check_config_mcp_changes()
                            # Check for background process notifications (completions
                            # and watch pattern matches) while agent is idle.
                            try:
                                from tools.process_registry import process_registry

                                if not process_registry.completion_queue.empty():
                                    evt = process_registry.completion_queue.get_nowait()
                                    # Skip if the agent already consumed this via wait/poll/log
                                    _evt_sid = evt.get("session_id", "")
                                    if (
                                        evt.get("type") == "completion"
                                        and process_registry.is_completion_consumed(
                                            _evt_sid
                                        )
                                    ):
                                        pass  # already delivered via tool result
                                    else:
                                        _synth = _format_process_notification(evt)
                                        if _synth:
                                            self._pending_input.put(_synth)
                            except Exception:
                                logger.debug("Ignoring error in process_loop()", exc_info=True)
                        continue

                    if not user_input:
                        continue

                    # Unpack image payload: (text, [Path, ...]) or plain str
                    submit_images = []
                    if isinstance(user_input, tuple):
                        user_input, submit_images = user_input

                    # Check for commands - but detect dragged/pasted file paths first.
                    # See _detect_file_drop() for details.
                    _file_drop = (
                        _detect_file_drop(user_input)
                        if isinstance(user_input, str)
                        else None
                    )
                    if _file_drop:
                        _drop_path = _file_drop["path"]
                        _remainder = _file_drop["remainder"]
                        if _file_drop["is_image"]:
                            submit_images.append(_drop_path)
                            user_input = (
                                _remainder
                                or f"[User attached image: {_drop_path.name}]"
                            )
                            _cprint(f"  ATTACH Auto-attached image: {_drop_path.name}")
                        else:
                            _cprint(f"  📄 Detected file: {_drop_path.name}")
                            user_input = f"[User attached file: {_drop_path}]" + (
                                f"\n{_remainder}" if _remainder else ""
                            )

                    if (
                        not _file_drop
                        and isinstance(user_input, str)
                        and _pkg()._looks_like_slash_command(user_input)
                    ):
                        _cprint(f"\n⚙️  {user_input}")
                        if not self.process_command(user_input):
                            self._should_exit = True
                            # Schedule app exit
                            if app.is_running:
                                app.exit()
                        continue

                    # Expand paste references back to full content
                    import re as _re

                    _paste_ref_re = _re.compile(
                        r"\[Pasted text #\d+: \d+ lines \u2192 (.+?)\]"
                    )
                    paste_refs = (
                        list(_paste_ref_re.finditer(user_input))
                        if isinstance(user_input, str)
                        else []
                    )
                    if paste_refs:

                        def _expand_ref(m):
                            p = Path(m.group(1))
                            return (
                                p.read_text(encoding="utf-8")
                                if p.exists()
                                else m.group(0)
                            )

                        expanded = _paste_ref_re.sub(_expand_ref, user_input)
                        total_lines = expanded.count("\n") + 1
                        n_pastes = len(paste_refs)
                        _user_bar = f"[{_accent_hex()}]{'─' * 40}[/]"
                        print()
                        _pkg().ChatConsole().print(_user_bar)
                        # Show any surrounding user text alongside the paste summary
                        split_parts = _paste_ref_re.split(user_input)
                        visible_user_text = " ".join(
                            split_parts[i].strip()
                            for i in range(0, len(split_parts), 2)
                            if split_parts[i].strip()
                        )
                        if visible_user_text:
                            _pkg().ChatConsole().print(
                                f"[bold {_accent_hex()}]\u25cf[/] [bold]{_escape(visible_user_text)}[/] "
                                f"[dim]({n_pastes} pasted block{'s' if n_pastes > 1 else ''}, {total_lines} lines total)[/]"
                            )
                        else:
                            _pkg().ChatConsole().print(
                                f"[bold {_accent_hex()}]\u25cf[/] [bold]{_escape(f'[Pasted text: {total_lines} lines]')}[/]"
                            )
                        user_input = expanded
                    else:
                        _user_bar = f"[{_accent_hex()}]{'─' * 40}[/]"
                        if "\n" in user_input:
                            first_line = user_input.split("\n")[0]
                            line_count = user_input.count("\n") + 1
                            print()
                            _pkg().ChatConsole().print(_user_bar)
                            _pkg().ChatConsole().print(
                                f"[bold {_accent_hex()}]●[/] [bold]{_escape(first_line)}[/] "
                                f"[dim](+{line_count - 1} lines)[/]"
                            )
                        else:
                            print()
                            _pkg().ChatConsole().print(_user_bar)
                            _pkg().ChatConsole().print(
                                f"[bold {_accent_hex()}]●[/] [bold]{_escape(user_input)}[/]"
                            )

                    # Show image attachment count
                    if submit_images:
                        n = len(submit_images)
                        _cprint(
                            f"  {_DIM}ATTACH {n} image{'s' if n > 1 else ''} attached{_RST}"
                        )

                    # Regular chat - run agent
                    self._agent_running = True
                    app.invalidate()  # Refresh status line

                    try:
                        self.chat(user_input, images=submit_images or None)
                    finally:
                        self._agent_running = False
                        self._spinner_text = ""
                        self._tool_start_time = 0.0
                        self._pending_tool_info.clear()
                        self._last_scrollback_tool = ""

                        app.invalidate()  # Refresh status line

                        # Continuous voice: auto-restart recording after agent responds.
                        # Dispatch to a daemon thread so play_beep (sd.wait) and
                        # AudioRecorder.start (lock acquire) never block process_loop -
                        # otherwise queued user input would stall silently.
                        if (
                            self._voice_mode
                            and self._voice_continuous
                            and not self._voice_recording
                        ):

                            def _restart_recording():
                                try:
                                    if self._voice_tts:
                                        self._voice_tts_done.wait(timeout=60)
                                        time.sleep(0.3)
                                    self._voice_start_recording()
                                    app.invalidate()
                                except Exception as e:
                                    _cprint(
                                        f"{_DIM}Voice auto-restart failed: {e}{_RST}"
                                    )

                            threading.Thread(
                                target=_restart_recording, daemon=True
                            ).start()

                        # Drain process notifications (completions + watch matches)
                        # that arrived while the agent was running.
                        try:
                            from tools.process_registry import process_registry

                            while not process_registry.completion_queue.empty():
                                evt = process_registry.completion_queue.get_nowait()
                                # Skip if the agent already consumed this via wait/poll/log
                                _evt_sid = evt.get("session_id", "")
                                if (
                                    evt.get("type") == "completion"
                                    and process_registry.is_completion_consumed(
                                        _evt_sid
                                    )
                                ):
                                    continue  # already delivered via tool result
                                _synth = _format_process_notification(evt)
                                if _synth:
                                    self._pending_input.put(_synth)
                        except Exception:
                            # Non-fatal - don't break the main loop
                            logger.debug("Ignored exception in process_loop", exc_info=True)

                except Exception as e:
                    print(f"Error: {e}")

        # Start processing thread
        process_thread = threading.Thread(target=process_loop, daemon=True)
        process_thread.start()

        # Register atexit cleanup so resources are freed even on unexpected exit
        atexit.register(_pkg()._run_cleanup)

        # Register signal handlers for graceful shutdown on SSH disconnect / SIGTERM
        def _signal_handler(signum, frame):
            """Handle SIGHUP/SIGTERM by triggering graceful cleanup."""
            logger.debug("Received signal %s, triggering graceful shutdown", signum)
            raise KeyboardInterrupt()

        try:
            import signal as _signal

            _signal.signal(_signal.SIGTERM, _signal_handler)
            if hasattr(_signal, "SIGHUP"):
                _signal.signal(_signal.SIGHUP, _signal_handler)
        except Exception:
            # Signal handlers may fail in restricted environments
            logger.debug("Ignored exception in run", exc_info=True)

        # Install a custom asyncio exception handler that suppresses the
        # "Event loop is closed" RuntimeError from httpx transport cleanup
        # and the "0 is not registered" KeyError from broken stdin (#6393).
        # The RuntimeError fix is defense-in-depth - the primary fix is
        # neuter_async_httpx_del which disables __del__ entirely.  The
        # KeyError fix handles macOS + uv-managed Python environments where
        # fd 0 is not reliably available to the asyncio selector.
        def _suppress_closed_loop_errors(loop, context):
            exc = context.get("exception")
            if isinstance(exc, RuntimeError) and "Event loop is closed" in str(exc):
                return  # silently suppress
            if isinstance(exc, KeyError) and "is not registered" in str(exc):
                return  # suppress selector registration failures (#6393)
            # Fall back to default handler for everything else
            loop.default_exception_handler(context)

        # Validate stdin before launching prompt_toolkit - on macOS with
        # uv-managed Python, fd 0 can be invalid or unregisterable with the
        # asyncio selector, causing "KeyError: '0 is not registered'" (#6393).
        try:
            import os as _os

            _os.fstat(0)
        except OSError:
            print(
                "Error: stdin (fd 0) is not available.\n"
                "This can happen with certain Python installations (e.g. uv-managed cPython on macOS).\n"
                "Try reinstalling Python via pyenv or Homebrew, then re-run: spark setup"
            )
            _pkg()._run_cleanup()
            self._print_exit_summary()
            return

        # Run the application with patch_stdout for proper output handling
        try:
            with patch_stdout():
                # Set the custom handler on prompt_toolkit's event loop
                try:
                    import asyncio as _aio

                    _loop = _aio.get_event_loop()
                    _loop.set_exception_handler(_suppress_closed_loop_errors)
                except Exception:
                    logger.debug("Ignoring error in run()", exc_info=True)
                app.run()
        except (EOFError, KeyboardInterrupt, BrokenPipeError):
            logger.debug("Ignoring error in run()", exc_info=True)
        except (KeyError, OSError) as _stdin_err:
            # Catch selector registration failures from broken stdin (#6393).
            # This is the fallback for cases that slip past the fstat() guard.
            if "is not registered" in str(_stdin_err) or "Bad file descriptor" in str(
                _stdin_err
            ):
                print(
                    f"\nError: stdin is not usable ({_stdin_err}).\n"
                    "This can happen with certain Python installations (e.g. uv-managed cPython on macOS).\n"
                    "Try reinstalling Python via pyenv or Homebrew, then re-run: spark setup"
                )
            else:
                raise
        finally:
            self._should_exit = True
            # Interrupt the agent immediately so its daemon thread stops making
            # API calls and exits promptly (agent_thread is daemon, so the
            # process will exit once the main thread finishes, but interrupting
            # avoids wasted API calls and lets run_conversation clean up).
            if self.agent and getattr(self, "_agent_running", False):
                try:
                    self.agent.interrupt()
                except Exception:
                    logger.debug("Ignoring error in run()", exc_info=True)
            # Flush memories before exit (only for substantial conversations)
            if self.agent and self.conversation_history:
                try:
                    self.agent.flush_memories(self.conversation_history)
                except (Exception, KeyboardInterrupt):
                    logger.debug("Ignoring error in run()", exc_info=True)
            # Shut down voice recorder (release persistent audio stream)
            if hasattr(self, "_voice_recorder") and self._voice_recorder:
                try:
                    self._voice_recorder.shutdown()
                except Exception:
                    logger.debug("Ignoring error in run()", exc_info=True)
                self._voice_recorder = None
            # Clean up old temp voice recordings
            try:
                from tools.voice_mode import cleanup_temp_recordings

                cleanup_temp_recordings()
            except Exception:
                logger.debug("Ignoring error in run()", exc_info=True)
            # Unregister callbacks to avoid dangling references
            set_sudo_password_callback(None)
            set_approval_callback(None)
            set_secret_capture_callback(None)
            # Close session in SQLite
            if hasattr(self, "_session_db") and self._session_db and self.agent:
                try:
                    self._session_db.end_session(self.agent.session_id, "cli_close")
                except (Exception, KeyboardInterrupt) as e:
                    logger.debug("Could not close session in DB: %s", e)
            # Plugin hook: on_session_end - safety net for interrupted exits.
            # run_conversation() already fires this per-turn on normal completion,
            # so only fire here if the agent was mid-turn (_agent_running) when
            # the exit occurred, meaning run_conversation's hook didn't fire.
            if self.agent and getattr(self, "_agent_running", False):
                try:
                    from spark_cli.plugins import invoke_hook as _invoke_hook

                    _invoke_hook(
                        "on_session_end",
                        session_id=self.agent.session_id,
                        completed=False,
                        interrupted=True,
                        model=getattr(self.agent, "model", None),
                        platform=getattr(self.agent, "platform", None) or "cli",
                    )
                except Exception:
                    logger.debug("Ignoring error in run()", exc_info=True)
            _pkg()._run_cleanup()
            self._print_exit_summary()
