"""Command + display methods for SparkCLI (mixin).

Extracted from core/cli/__init__.py (Phase 3). Carries checkpoint/snapshot, image
paste, tools/profile/config display, session list/resume, files/memory/keys/branch
command handlers and their show_* helpers. Combined into SparkCLI via inheritance.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.markup import escape as _escape

# Defined in core/cli/__init__.py before this module is imported, so these
# resolve at import time without a circular dependency.
from core.cli import ChatConsole, _skill_commands  # noqa: E402
from core.cli.attachments import (
    _IMAGE_EXTENSIONS,
    _resolve_attachment_path,
    _split_path_input,
    _termux_example_image_path,
)
from core.cli.config_state import _spark_home
from core.cli.render import _ACCENT, _BOLD, _DIM, _RST, _accent_hex, _cprint
from core.model_tools import get_tool_definitions, get_toolset_for_tool
from core.spark_constants import display_spark_home, get_spark_home
from core.spark_constants import is_termux as _is_termux_environment
from core.toolsets import get_all_toolsets, get_toolset_info


class _DisplayCommandsMixin:
    def _handle_rollback_command(self, command: str):
        """Handle /rollback - list, diff, or restore filesystem checkpoints.

        Syntax:
            /rollback                 - list checkpoints
            /rollback <N>             - restore checkpoint N (also undoes last chat turn)
            /rollback diff <N>        - preview changes since checkpoint N
            /rollback <N> <file>      - restore a single file from checkpoint N
        """
        from tools.checkpoint_manager import format_checkpoint_list

        if not hasattr(self, "agent") or not self.agent:
            print("  No active agent session.")
            return

        mgr = self.agent._checkpoint_mgr
        if not mgr.enabled:
            print("  Checkpoints are not enabled.")
            print("  Enable with: spark --checkpoints")
            print("  Or in config.yaml: checkpoints: { enabled: true }")
            return

        cwd = os.getenv("TERMINAL_CWD", os.getcwd())
        parts = command.split()
        args = parts[1:] if len(parts) > 1 else []

        if not args:
            # List checkpoints
            checkpoints = mgr.list_checkpoints(cwd)
            print(format_checkpoint_list(checkpoints, cwd))
            return

        # Handle /rollback diff <N>
        if args[0].lower() == "diff":
            if len(args) < 2:
                print("  Usage: /rollback diff <N>")
                return
            checkpoints = mgr.list_checkpoints(cwd)
            if not checkpoints:
                print(f"  No checkpoints found for {cwd}")
                return
            target_hash = self._resolve_checkpoint_ref(args[1], checkpoints)
            if not target_hash:
                return
            result = mgr.diff(cwd, target_hash)
            if result["success"]:
                stat = result.get("stat", "")
                diff = result.get("diff", "")
                if not stat and not diff:
                    print("  No changes since this checkpoint.")
                else:
                    if stat:
                        print(f"\n{stat}")
                    if diff:
                        # Limit diff output to avoid terminal flood
                        diff_lines = diff.splitlines()
                        if len(diff_lines) > 80:
                            print("\n".join(diff_lines[:80]))
                            print(
                                f"\n  ... ({len(diff_lines) - 80} more lines, showing first 80)"
                            )
                        else:
                            print(f"\n{diff}")
            else:
                print(f"  ❌ {result['error']}")
            return

        # Resolve checkpoint reference (number or hash)
        checkpoints = mgr.list_checkpoints(cwd)
        if not checkpoints:
            print(f"  No checkpoints found for {cwd}")
            return

        target_hash = self._resolve_checkpoint_ref(args[0], checkpoints)
        if not target_hash:
            return

        # Check for file-level restore: /rollback <N> <file>
        file_path = args[1] if len(args) > 1 else None

        result = mgr.restore(cwd, target_hash, file_path=file_path)
        if result["success"]:
            if file_path:
                print(
                    f"  ✅ Restored {file_path} from checkpoint {result['restored_to']}: {result['reason']}"
                )
            else:
                print(
                    f"  ✅ Restored to checkpoint {result['restored_to']}: {result['reason']}"
                )
            print("  A pre-rollback snapshot was saved automatically.")

            # Also undo the last conversation turn so the agent's context
            # matches the restored filesystem state
            if self.conversation_history:
                self.undo_last()
                print("  Chat turn undone to match restored file state.")
        else:
            print(f"  ❌ {result['error']}")

    def _resolve_checkpoint_ref(self, ref: str, checkpoints: list) -> str | None:
        """Resolve a checkpoint number or hash to a full commit hash."""
        try:
            idx = int(ref) - 1  # 1-indexed for user
            if 0 <= idx < len(checkpoints):
                return checkpoints[idx]["hash"]
            else:
                print(f"  Invalid checkpoint number. Use 1-{len(checkpoints)}.")
                return None
        except ValueError:
            # Treat as a git hash
            return ref

    def _handle_snapshot_command(self, command: str):
        """Handle /snapshot - lightweight state snapshots for Spark config/state.

        Syntax:
            /snapshot                  - list recent snapshots
            /snapshot create [label]   - create a snapshot
            /snapshot restore <id>     - restore state from snapshot
            /snapshot prune [N]        - prune to N snapshots (default 20)
        """
        from core.spark_constants import display_spark_home
        from spark_cli.backup import (
            create_quick_snapshot,
            list_quick_snapshots,
            prune_quick_snapshots,
            restore_quick_snapshot,
        )

        parts = command.split()
        subcmd = parts[1].lower() if len(parts) > 1 else "list"

        if subcmd in ("list", "ls"):
            snaps = list_quick_snapshots()
            if not snaps:
                print("  No state snapshots yet.")
                print("  Create one: /snapshot create [label]")
                return
            print(f"  State snapshots ({display_spark_home()}/state-snapshots/):\n")
            print(f"  {'#':>3}  {'ID':<35} {'Files':>5} {'Size':>10} {'Label'}")
            print(f"  {'-' * 3}  {'-' * 35} {'-' * 5} {'-' * 10} {'-' * 20}")
            for i, s in enumerate(snaps, 1):
                size = s.get("total_size", 0)
                if size < 1024:
                    size_str = f"{size} B"
                elif size < 1024 * 1024:
                    size_str = f"{size / 1024:.0f} KB"
                else:
                    size_str = f"{size / 1024 / 1024:.1f} MB"
                label = s.get("label") or ""
                print(
                    f"  {i:3}  {s['id']:<35} {s.get('file_count', 0):>5} {size_str:>10} {label}"
                )

        elif subcmd == "create":
            label = " ".join(parts[2:]) if len(parts) > 2 else None
            snap_id = create_quick_snapshot(label=label)
            if snap_id:
                print(f"  Snapshot created: {snap_id}")
            else:
                print("  No state files found to snapshot.")

        elif subcmd in ("restore", "rewind"):
            if len(parts) < 3:
                print("  Usage: /snapshot restore <snapshot-id>")
                # Show hint with most recent snapshot
                snaps = list_quick_snapshots(limit=1)
                if snaps:
                    print(f"  Most recent: {snaps[0]['id']}")
                return
            snap_id = parts[2]
            # Allow restore by number (1-indexed)
            try:
                idx = int(snap_id)
                snaps = list_quick_snapshots()
                if 1 <= idx <= len(snaps):
                    snap_id = snaps[idx - 1]["id"]
                else:
                    print(f"  Invalid snapshot number. Use 1-{len(snaps)}.")
                    return
            except ValueError:
                pass
            if restore_quick_snapshot(snap_id):
                print(f"  Restored state from: {snap_id}")
                print("  Restart recommended for state.db changes to take effect.")
            else:
                print(f"  Snapshot not found: {snap_id}")

        elif subcmd == "prune":
            keep = 20
            if len(parts) > 2:
                try:
                    keep = int(parts[2])
                except ValueError:
                    print("  Usage: /snapshot prune [keep-count]")
                    return
            deleted = prune_quick_snapshots(keep=keep)
            print(f"  Pruned {deleted} old snapshot(s) (keeping {keep}).")

        else:
            print(f"  Unknown subcommand: {subcmd}")
            print("  Usage: /snapshot [list|create [label]|restore <id>|prune [N]]")

    def _handle_stop_command(self):
        """Handle /stop - kill all running background processes.

        Inspired by OpenAI Codex's separation of interrupt (stop current turn)
        from /stop (clean up background processes). See openai/codex#14602.
        """
        from tools.process_registry import process_registry

        processes = process_registry.list_sessions()
        running = [p for p in processes if p.get("status") == "running"]

        if not running:
            print("  No running background processes.")
            return

        print(f"  Stopping {len(running)} background process(es)...")
        killed = process_registry.kill_all()
        print(f"  ✅ Stopped {killed} process(es).")

    def _handle_paste_command(self):
        """Handle /paste - explicitly check clipboard for an image.

        This is the reliable fallback for terminals where BracketedPaste
        doesn't fire for image-only clipboard content (e.g., VSCode terminal,
        Windows Terminal with WSL2).
        """
        if _is_termux_environment():
            _cprint(
                f"  {_DIM}Clipboard image paste is not available on Termux - "
                f"use /image <path> or paste a local image path like "
                f"{_termux_example_image_path()}{_RST}"
            )
            return

        from spark_cli.clipboard import has_clipboard_image

        if has_clipboard_image():
            if self._try_attach_clipboard_image():
                n = len(self._attached_images)
                _cprint(f"  ATTACH Image #{n} attached from clipboard")
            else:
                _cprint(
                    f"  {_DIM}(>_<) Clipboard has an image but extraction failed{_RST}"
                )
        else:
            _cprint(f"  {_DIM}(._.) No image found in clipboard{_RST}")

    def _handle_image_command(self, cmd_original: str):
        """Handle /image <path> - attach a local image file for the next prompt."""
        raw_args = cmd_original.split(None, 1)[1].strip() if " " in cmd_original else ""
        if not raw_args:
            hint = (
                _termux_example_image_path()
                if _is_termux_environment()
                else "/path/to/image.png"
            )
            _cprint(f"  {_DIM}Usage: /image <path>  e.g. /image {hint}{_RST}")
            return

        path_token, _remainder = _split_path_input(raw_args)
        image_path = _resolve_attachment_path(path_token)
        if image_path is None:
            _cprint(f"  {_DIM}(>_<) File not found: {path_token}{_RST}")
            return
        if image_path.suffix.lower() not in _IMAGE_EXTENSIONS:
            _cprint(
                f"  {_DIM}(._.) Not a supported image file: {image_path.name}{_RST}"
            )
            return

        self._attached_images.append(image_path)
        _cprint(f"  ATTACH Attached image: {image_path.name}")
        if _remainder:
            _cprint(
                f"  {_DIM}Now type your prompt (or use --image in single-query mode): {_remainder}{_RST}"
            )
        elif _is_termux_environment():
            _cprint(
                f'  {_DIM}Tip: type your next message, or run spark chat -q --image {_termux_example_image_path(image_path.name)} "What do you see?"{_RST}'
            )

    def _preprocess_images_with_vision(
        self, text: str, images: list, *, announce: bool = True
    ) -> str:
        """Analyze attached images via the vision tool and return enriched text.

        Instead of embedding raw base64 ``image_url`` content parts in the
        conversation (which only works with vision-capable models), this
        pre-processes each image through the auxiliary vision model (Gemini
        Flash) and prepends the descriptions to the user's message - the
        same approach the messaging gateway uses.

        The local file path is included so the agent can re-examine the
        image later with ``vision_analyze`` if needed.
        """
        import asyncio as _asyncio
        import json as _json

        from tools.vision_tools import vision_analyze_tool

        analysis_prompt = (
            "Describe everything visible in this image in thorough detail. "
            "Include any text, code, data, objects, people, layout, colors, "
            "and any other notable visual information."
        )

        enriched_parts = []
        for img_path in images:
            if not img_path.exists():
                continue
            size_kb = img_path.stat().st_size // 1024
            if announce:
                _cprint(f"  {_DIM}👁️  analyzing {img_path.name} ({size_kb}KB)...{_RST}")
            try:
                result_json = _asyncio.run(
                    vision_analyze_tool(
                        image_url=str(img_path), user_prompt=analysis_prompt
                    )
                )
                result = _json.loads(result_json)
                if result.get("success"):
                    description = result.get("analysis", "")
                    enriched_parts.append(
                        f"[The user attached an image. Here's what it contains:\n{description}]\n"
                        f"[If you need a closer look, use vision_analyze with "
                        f"image_url: {img_path}]"
                    )
                    if announce:
                        _cprint(f"  {_DIM}OK: image analyzed{_RST}")
                else:
                    enriched_parts.append(
                        f"[The user attached an image but it couldn't be analyzed. "
                        f"You can try examining it with vision_analyze using "
                        f"image_url: {img_path}]"
                    )
                    if announce:
                        _cprint(
                            f"  {_DIM}WARN vision analysis failed - path included for retry{_RST}"
                        )
            except Exception as e:
                enriched_parts.append(
                    f"[The user attached an image but analysis failed ({e}). "
                    f"You can try examining it with vision_analyze using "
                    f"image_url: {img_path}]"
                )
                if announce:
                    _cprint(
                        f"  {_DIM}WARN vision analysis error - path included for retry{_RST}"
                    )

        # Combine: vision descriptions first, then the user's original text
        user_text = text if isinstance(text, str) and text else ""
        if enriched_parts:
            prefix = "\n\n".join(enriched_parts)
            return f"{prefix}\n\n{user_text}" if user_text else prefix
        return user_text or "What do you see in this image?"

    def _show_tool_availability_warnings(self):
        """Show warnings about disabled tools due to missing API keys."""
        try:
            from core.model_tools import check_tool_availability

            available, unavailable = check_tool_availability()

            # Filter to only those missing API keys (not system deps)
            api_key_missing = [u for u in unavailable if u["missing_vars"]]

            if api_key_missing:
                self.console.print()
                self.console.print(
                    "[yellow]WARN  Some tools disabled (missing API keys):[/]"
                )
                for item in api_key_missing:
                    tools_str = ", ".join(item["tools"][:2])  # Show first 2 tools
                    if len(item["tools"]) > 2:
                        tools_str += f", +{len(item['tools']) - 2} more"
                    self.console.print(
                        f"   [dim]• {item['name']}[/] [dim italic]({', '.join(item['missing_vars'])})[/]"
                    )
                self.console.print("[dim]   Run 'spark setup' to configure[/]")
        except Exception:
            pass  # Don't crash on import errors

    def _show_status(self):
        """Show compact startup status line."""
        # Get tool count
        tools = get_tool_definitions(
            enabled_toolsets=self.enabled_toolsets, quiet_mode=True
        )
        tool_count = len(tools) if tools else 0

        # Format model name (shorten if needed)
        model_short = self.model.split("/")[-1] if "/" in self.model else self.model
        if len(model_short) > 30:
            model_short = model_short[:27] + "..."

        # Get API status indicator
        if self.api_key:
            api_indicator = "[green bold]●[/]"
        else:
            api_indicator = "[red bold]●[/]"

        # Build status line with proper markup - skin-aware colors
        try:
            from spark_cli.skin_engine import get_active_skin

            skin = get_active_skin()
            separator_color = skin.get_color("banner_dim", "#B8860B")
            accent_color = skin.get_color("ui_accent", "#FFBF00")
            label_color = skin.get_color("ui_label", "#4dd0e1")
        except Exception:
            separator_color, accent_color, label_color = "#B8860B", "#FFBF00", "cyan"
        toolsets_info = ""
        if self.enabled_toolsets and "all" not in self.enabled_toolsets:
            toolsets_info = f" [dim {separator_color}]-[/] [{label_color}]toolsets: {', '.join(self.enabled_toolsets)}[/]"

        provider_info = (
            f" [dim {separator_color}]-[/] [dim]provider: {self.provider}[/]"
        )
        if self._provider_source:
            provider_info += (
                f" [dim {separator_color}]-[/] [dim]auth: {self._provider_source}[/]"
            )

        self.console.print(
            f"  {api_indicator} [{accent_color}]{model_short}[/] "
            f"[dim {separator_color}]-[/] [bold {label_color}]{tool_count} tools[/]"
            f"{toolsets_info}{provider_info}"
        )

    def _show_session_status(self):
        """Show gateway-style status for the current CLI session."""
        session_meta = {}
        if self._session_db:
            try:
                session_meta = self._session_db.get_session(self.session_id) or {}
            except Exception:
                session_meta = {}

        title = (session_meta.get("title") or "").strip()

        created_at = self.session_start
        started_at = session_meta.get("started_at")
        if started_at:
            try:
                created_at = datetime.fromtimestamp(float(started_at))
            except Exception:
                created_at = self.session_start

        updated_at = created_at
        for field in ("updated_at", "last_updated_at", "last_activity_at"):
            value = session_meta.get(field)
            if not value:
                continue
            try:
                updated_at = datetime.fromtimestamp(float(value))
                break
            except Exception:
                pass

        agent = getattr(self, "agent", None)
        total_tokens = getattr(agent, "session_total_tokens", 0) or 0
        provider = getattr(self, "provider", None) or "unknown"
        model = getattr(self, "model", None) or "(unknown)"
        is_running = bool(getattr(self, "_agent_running", False))

        lines = [
            "Spark CLI Status",
            "",
            f"Session ID: {self.session_id}",
            f"Path: {display_spark_home()}",
        ]
        if title:
            lines.append(f"Title: {title}")
        lines.extend(
            [
                f"Model: {model} ({provider})",
                f"Created: {created_at.strftime('%Y-%m-%d %H:%M')}",
                f"Last Activity: {updated_at.strftime('%Y-%m-%d %H:%M')}",
                f"Tokens: {total_tokens:,}",
                f"Agent Running: {'Yes' if is_running else 'No'}",
            ]
        )
        self.console.print("\n".join(lines), highlight=False, markup=False)

    def _fast_command_available(self) -> bool:
        try:
            from spark_cli.models import model_supports_fast_mode
        except Exception:
            return False
        agent = getattr(self, "agent", None)
        model = getattr(agent, "model", None) or getattr(self, "model", None)
        return model_supports_fast_mode(model)

    def _command_available(self, slash_command: str) -> bool:
        if slash_command == "/fast":
            return self._fast_command_available()
        return True

    def show_help(self):
        """Display help information with categorized commands."""
        from spark_cli.commands import COMMANDS_BY_CATEGORY

        try:
            from spark_cli.skin_engine import get_active_help_header

            header = get_active_help_header("[?] Available Commands")
        except Exception:
            header = "[?] Available Commands"
        header = (header or "").strip() or "[?] Available Commands"
        inner_width = 55
        if len(header) > inner_width:
            header = header[:inner_width]
        _cprint(f"\n{_BOLD}+{'-' * inner_width}+{_RST}")
        _cprint(f"{_BOLD}|{header:^{inner_width}}|{_RST}")
        _cprint(f"{_BOLD}+{'-' * inner_width}+{_RST}")

        for category, commands in COMMANDS_BY_CATEGORY.items():
            _cprint(f"\n  {_BOLD}-- {category} --{_RST}")
            for cmd, desc in commands.items():
                if not self._command_available(cmd):
                    continue
                ChatConsole().print(
                    f"    [bold {_accent_hex()}]{cmd:<15}[/] [dim]-[/] {_escape(desc)}"
                )

        if _skill_commands:
            _cprint(
                f"\n  ⚡ {_BOLD}Skill Commands{_RST} ({len(_skill_commands)} installed):"
            )
            for cmd, info in sorted(_skill_commands.items()):
                ChatConsole().print(
                    f"    [bold {_accent_hex()}]{cmd:<22}[/] [dim]-[/] {_escape(info['description'])}"
                )

        _cprint(f"\n  {_DIM}Tip: Just type your message to chat with Spark!{_RST}")
        _cprint(f"  {_DIM}Multi-line: Alt+Enter for a new line{_RST}")
        if _is_termux_environment():
            _cprint(
                f"  {_DIM}Attach image: /image {_termux_example_image_path()} or start your prompt with a local image path{_RST}\n"
            )
        else:
            _cprint(f"  {_DIM}Paste image: Alt+V (or /paste){_RST}\n")

    def show_tools(self):
        """Display available tools with kawaii ASCII art."""
        tools = get_tool_definitions(
            enabled_toolsets=self.enabled_toolsets, quiet_mode=True
        )

        if not tools:
            print("(;_;) No tools available")
            return

        # Header
        print()
        title = "Available Tools"
        width = 78
        pad = width - len(title)
        print("+" + "-" * width + "+")
        print("|" + " " * (pad // 2) + title + " " * (pad - pad // 2) + "|")
        print("+" + "-" * width + "+")
        print()

        # Group tools by toolset
        toolsets = {}
        for tool in sorted(tools, key=lambda t: t["function"]["name"]):
            name = tool["function"]["name"]
            toolset = get_toolset_for_tool(name) or "unknown"
            if toolset not in toolsets:
                toolsets[toolset] = []
            desc = tool["function"].get("description", "")
            # First sentence: split on ". " (period+space) to avoid breaking on "e.g." or "v2.0"
            desc = desc.split("\n")[0]
            if ". " in desc:
                desc = desc[: desc.index(". ") + 1]
            toolsets[toolset].append((name, desc))

        # Display by toolset
        for toolset in sorted(toolsets.keys()):
            print(f"  [{toolset}]")
            for name, desc in toolsets[toolset]:
                print(f"    * {name:<20} - {desc}")
            print()

        print(f"  Total: {len(tools)} tools")
        print()

    def _handle_tools_command(self, cmd: str):
        """Handle /tools [list|disable|enable] slash commands.

        /tools (no args) shows the tool list.
        /tools list shows enabled/disabled status per toolset.
        /tools disable/enable saves the change to config and resets
        the session so the new tool set takes effect cleanly (no
        prompt-cache breakage mid-conversation).
        """
        import shlex
        from argparse import Namespace

        from spark_cli.tools_config import tools_disable_enable_command

        try:
            parts = shlex.split(cmd)
        except ValueError:
            parts = cmd.split()

        subcommand = parts[1] if len(parts) > 1 else ""
        if subcommand not in ("list", "disable", "enable"):
            self.show_tools()
            return

        if subcommand == "list":
            tools_disable_enable_command(Namespace(tools_action="list", platform="cli"))
            return

        names = parts[2:]
        if not names:
            print(f"(._.) Usage: /tools {subcommand} <name> [name ...]")
            print(f"  Built-in toolset:  /tools {subcommand} web")
            print(f"  MCP tool:          /tools {subcommand} github:create_issue")
            return

        # Apply the change directly - the user typing the command is implicit
        # consent.  Do NOT use input() here; it hangs inside prompt_toolkit's
        # TUI event loop (known pitfall).
        verb = "Disabling" if subcommand == "disable" else "Enabling"
        label = ", ".join(names)
        _cprint(f"{_ACCENT}{verb} {label}...{_RST}")

        tools_disable_enable_command(
            Namespace(tools_action=subcommand, names=names, platform="cli")
        )

        # Reset session so the new tool config is picked up from a clean state
        from spark_cli.config import load_config
        from spark_cli.tools_config import _get_platform_tools

        self.enabled_toolsets = _get_platform_tools(load_config(), "cli")
        self.new_session()
        _cprint(f"{_DIM}Session reset. New tool configuration is active.{_RST}")

    def show_toolsets(self):
        """Display available toolsets with kawaii ASCII art."""
        all_toolsets = get_all_toolsets()

        # Header
        print()
        title = "Available Toolsets"
        width = 58
        pad = width - len(title)
        print("+" + "-" * width + "+")
        print("|" + " " * (pad // 2) + title + " " * (pad - pad // 2) + "|")
        print("+" + "-" * width + "+")
        print()

        for name in sorted(all_toolsets.keys()):
            info = get_toolset_info(name)
            if info:
                tool_count = info["tool_count"]
                desc = info["description"]

                # Mark if currently enabled
                marker = (
                    "(*)"
                    if self.enabled_toolsets and name in self.enabled_toolsets
                    else "   "
                )
                print(f"  {marker} {name:<18} [{tool_count:>2} tools] - {desc}")

        print()
        print("  (*) = currently enabled")
        print()
        print("  Tip: Use 'all' or '*' to enable all toolsets")
        print("  Example: python cli.py --toolsets web,terminal")
        print()

    def _handle_profile_command(self):
        """Display active profile name and home directory."""
        from core.spark_constants import display_spark_home, get_spark_home

        home = get_spark_home()
        display = display_spark_home()

        profiles_parent = Path.home() / ".spark" / "profiles"
        try:
            rel = home.relative_to(profiles_parent)
            profile_name = str(rel).split("/")[0]
        except ValueError:
            profile_name = None

        print()
        if profile_name:
            print(f"  Profile: {profile_name}")
        else:
            print("  Profile: default")
        print(f"  Home:    {display}")
        print()

    def show_config(self):
        """Display current configuration with kawaii ASCII art."""
        # Get terminal config from environment (which was set from cli-config.yaml)
        terminal_env = os.getenv("TERMINAL_ENV", "local")
        terminal_cwd = os.getenv("TERMINAL_CWD", os.getcwd())
        terminal_timeout = os.getenv("TERMINAL_TIMEOUT", "60")

        user_config_path = _spark_home / "config.yaml"
        project_config_path = Path(__file__).parent / "cli-config.yaml"
        if user_config_path.exists():
            config_path = user_config_path
        else:
            config_path = project_config_path
        config_status = "(loaded)" if config_path.exists() else "(not found)"

        api_key_display = (
            "********" + self.api_key[-4:]
            if self.api_key and len(self.api_key) > 4
            else "Not set!"
        )

        print()
        title = "Configuration"
        width = 50
        pad = width - len(title)
        print("+" + "-" * width + "+")
        print("|" + " " * (pad // 2) + title + " " * (pad - pad // 2) + "|")
        print("+" + "-" * width + "+")
        print()
        print("  -- Model --")
        print(f"  Model:     {self.model}")
        print(f"  Base URL:  {self.base_url}")
        print(f"  API Key:   {api_key_display}")
        print()
        print("  -- Terminal --")
        print(f"  Environment:  {terminal_env}")
        if terminal_env == "ssh":
            ssh_host = os.getenv("TERMINAL_SSH_HOST", "not set")
            ssh_user = os.getenv("TERMINAL_SSH_USER", "not set")
            ssh_port = os.getenv("TERMINAL_SSH_PORT", "22")
            print(f"  SSH Target:   {ssh_user}@{ssh_host}:{ssh_port}")
        print(f"  Working Dir:  {terminal_cwd}")
        print(f"  Timeout:      {terminal_timeout}s")
        print()
        print("  -- Agent --")
        print(f"  Max Turns:  {self.max_turns}")
        print(
            f"  Toolsets:   {', '.join(self.enabled_toolsets) if self.enabled_toolsets else 'all'}"
        )
        print(f"  Verbose:    {self.verbose}")
        print()
        print("  -- Session --")
        print(f"  Started:     {self.session_start.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Config File: {config_path} {config_status}")
        print()

    def _list_recent_sessions(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return recent CLI sessions for in-chat browsing/resume affordances."""
        if not self._session_db:
            return []
        try:
            sessions = self._session_db.list_sessions_rich(
                source="cli",
                exclude_sources=["tool"],
                limit=limit,
            )
        except Exception:
            return []
        return [s for s in sessions if s.get("id") != self.session_id]

    def _show_recent_sessions(
        self, *, reason: str = "history", limit: int = 10
    ) -> bool:
        """Render recent sessions inline from the active chat TUI.

        Returns True when something was shown, False if no session list was available.
        """
        sessions = self._list_recent_sessions(limit=limit)
        if not sessions:
            return False

        from spark_cli.main import _relative_time

        print()
        if reason == "history":
            print(
                "(._.) No messages in the current chat yet - here are recent sessions you can resume:"
            )
        else:
            print("  Recent sessions:")
        print()
        print(f"  {'Title':<32} {'Preview':<40} {'Last Active':<13} {'ID'}")
        print(f"  {'-' * 32} {'-' * 40} {'-' * 13} {'-' * 24}")
        for session in sessions:
            title = (session.get("title") or "-")[:30]
            preview = (session.get("preview") or "")[:38]
            last_active = _relative_time(session.get("last_active"))
            print(f"  {title:<32} {preview:<40} {last_active:<13} {session['id']}")
        print()
        print("  Use /resume <session id or title> to continue where you left off.")
        print()
        return True

    def show_history(self):
        """Display conversation history."""
        if not self.conversation_history:
            if not self._show_recent_sessions(reason="history"):
                print("(._.) No conversation history yet.")
            return

        preview_limit = 400
        visible_index = 0
        hidden_tool_messages = 0

        def flush_tool_summary():
            nonlocal hidden_tool_messages
            if not hidden_tool_messages:
                return

            noun = "message" if hidden_tool_messages == 1 else "messages"
            print("\n  [Tools]")
            print(f"    ({hidden_tool_messages} tool {noun} hidden)")
            hidden_tool_messages = 0

        print()
        print("+" + "-" * 50 + "+")
        print("|" + " " * 14 + "Conversation History" + " " * 13 + "|")
        print("+" + "-" * 50 + "+")

        for msg in self.conversation_history:
            role = msg.get("role", "unknown")

            if role == "tool":
                hidden_tool_messages += 1
                continue

            if role not in {"user", "assistant"}:
                continue

            flush_tool_summary()
            visible_index += 1

            content = msg.get("content")
            content_text = "" if content is None else str(content)

            if role == "user":
                print(f"\n  [You #{visible_index}]")
                print(
                    f"    {content_text[:preview_limit]}{'...' if len(content_text) > preview_limit else ''}"
                )
                continue

            print(f"\n  [Spark #{visible_index}]")
            tool_calls = msg.get("tool_calls") or []
            if content_text:
                preview = content_text[:preview_limit]
                suffix = "..." if len(content_text) > preview_limit else ""
            elif tool_calls:
                tool_count = len(tool_calls)
                noun = "call" if tool_count == 1 else "calls"
                preview = f"(requested {tool_count} tool {noun})"
                suffix = ""
            else:
                preview = "(no text response)"
                suffix = ""
            print(f"    {preview}{suffix}")

        flush_tool_summary()
        print()

    def _notify_session_boundary(self, event_type: str) -> None:
        """Fire a session-boundary plugin hook (on_session_finalize or on_session_reset).

        Non-blocking - errors are caught and logged.  Safe to call from any
        lifecycle point (shutdown, /new, /reset).
        """
        try:
            from spark_cli.plugins import invoke_hook as _invoke_hook

            _invoke_hook(
                event_type,
                session_id=self.agent.session_id if self.agent else None,
                platform=getattr(self, "platform", None) or "cli",
            )
        except Exception:
            pass

    def new_session(self, silent=False):
        """Start a fresh session with a new session ID and cleared agent state."""
        if self.agent and self.conversation_history:
            try:
                self.agent.flush_memories(self.conversation_history)
            except (Exception, KeyboardInterrupt):
                pass
            self._notify_session_boundary("on_session_finalize")
        elif self.agent:
            # First session or empty history - still finalize the old session
            self._notify_session_boundary("on_session_finalize")

        old_session_id = self.session_id
        if self._session_db and old_session_id:
            try:
                self._session_db.end_session(old_session_id, "new_session")
            except Exception:
                pass

        self.session_start = datetime.now()
        timestamp_str = self.session_start.strftime("%Y%m%d_%H%M%S")
        short_uuid = uuid.uuid4().hex[:6]
        self.session_id = f"{timestamp_str}_{short_uuid}"
        self.conversation_history = []
        self._pending_title = None
        self._resumed = False

        if self.agent:
            self.agent.session_id = self.session_id
            self.agent.session_start = self.session_start
            self.agent.reset_session_state()
            if hasattr(self.agent, "_last_flushed_db_idx"):
                self.agent._last_flushed_db_idx = 0
            if hasattr(self.agent, "_todo_store"):
                try:
                    from tools.todo_tool import TodoStore

                    self.agent._todo_store = TodoStore()
                except Exception:
                    pass
            if hasattr(self.agent, "_invalidate_system_prompt"):
                self.agent._invalidate_system_prompt()

            if self._session_db:
                try:
                    self._session_db.create_session(
                        session_id=self.session_id,
                        source=os.environ.get("SPARK_SESSION_SOURCE", "cli"),
                        model=self.model,
                        model_config={
                            "max_iterations": self.max_turns,
                            "reasoning_config": self.reasoning_config,
                        },
                    )
                except Exception:
                    pass
            self._notify_session_boundary("on_session_reset")

        if not silent:
            print("New session started!")

    def _handle_resume_command(self, cmd_original: str) -> None:
        """Handle /resume <session_id_or_title> - switch to a previous session mid-conversation."""
        parts = cmd_original.split(None, 1)
        target = parts[1].strip() if len(parts) > 1 else ""

        if not target:
            _cprint("  Usage: /resume <session_id_or_title>")
            if self._show_recent_sessions(reason="resume"):
                return
            _cprint("  Tip:   Use /history or `spark sessions list` to find sessions.")
            return

        if not self._session_db:
            _cprint("  Session database not available.")
            return

        # Resolve title or ID
        from spark_cli.main import _resolve_session_by_name_or_id

        resolved = _resolve_session_by_name_or_id(target)
        target_id = resolved or target

        session_meta = self._session_db.get_session(target_id)
        if not session_meta:
            _cprint(f"  Session not found: {target}")
            _cprint(
                "  Use /history or `spark sessions list` to see available sessions."
            )
            return

        if target_id == self.session_id:
            _cprint("  Already on that session.")
            return

        # End current session
        try:
            self._session_db.end_session(self.session_id, "resumed_other")
        except Exception:
            pass

        # Switch to the target session
        self.session_id = target_id
        self._resumed = True
        self._pending_title = None

        # Load conversation history (strip transcript-only metadata entries)
        restored = self._session_db.get_messages_as_conversation(target_id)
        restored = [m for m in (restored or []) if m.get("role") != "session_meta"]
        self.conversation_history = restored

        # Re-open the target session so it's not marked as ended
        try:
            self._session_db.reopen_session(target_id)
        except Exception:
            pass

        # Sync the agent if already initialised
        if self.agent:
            self.agent.session_id = target_id
            self.agent.reset_session_state()
            if hasattr(self.agent, "_last_flushed_db_idx"):
                self.agent._last_flushed_db_idx = len(self.conversation_history)
            if hasattr(self.agent, "_todo_store"):
                try:
                    from tools.todo_tool import TodoStore

                    self.agent._todo_store = TodoStore()
                except Exception:
                    pass
            if hasattr(self.agent, "_invalidate_system_prompt"):
                self.agent._invalidate_system_prompt()

        title_part = f' "{session_meta["title"]}"' if session_meta.get("title") else ""
        msg_count = len(
            [m for m in self.conversation_history if m.get("role") == "user"]
        )
        if self.conversation_history:
            _cprint(
                f"  ↻ Resumed session {target_id}{title_part}"
                f" ({msg_count} user message{'s' if msg_count != 1 else ''},"
                f" {len(self.conversation_history)} total)"
            )
        else:
            _cprint(
                f"  ↻ Resumed session {target_id}{title_part} - no messages, starting fresh."
            )

    def _handle_sessions_command(self) -> None:
        """Handle /sessions — fuzzy-browse recent sessions and resume one."""
        if not self._session_db:
            _cprint("  Session database not available.")
            return
        try:
            sessions = self._session_db.list_sessions_rich(limit=50)
        except Exception:
            sessions = []
        if not sessions:
            _cprint("  No sessions found.")
            return
        # Reuse the curses-based session browser from spark_cli/main.py
        try:
            from spark_cli.main import _session_browse_picker
        except ImportError:
            _cprint("  Session browser not available — use 'spark sessions browse' instead.")
            return
        selected_id = _session_browse_picker(sessions)
        if not selected_id or selected_id == self.session_id:
            return
        # Delegate to /resume logic
        fake_cmd = f"/resume {selected_id}"
        self._handle_resume_command(fake_cmd)

    def _handle_files_command(self) -> None:
        """Handle /files — fuzzy file picker that inserts @path into the next message."""
        import os
        import subprocess
        cwd = os.getcwd()
        try:
            # Try fzf first (most common fuzzy finder)
            result = subprocess.run(
                ["fzf", "--height=40%", "--reverse", "--preview=head -20 {}", "--preview-window=right:50%"],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0 and result.stdout.strip():
                selected = result.stdout.strip()
                # Insert into the prompt buffer as @path
                rel = os.path.relpath(selected, cwd)
                self._pending_input.put(f"@{rel} ")
                _cprint(f"  Added @{rel} to your message.")
                return
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        # Fallback: simple glob-based picker using curses
        try:
            import glob
            files = sorted(glob.glob("**/*", recursive=True))
            files = [f for f in files if os.path.isfile(f) and not any(
                seg.startswith(".") or seg == "__pycache__" or seg == "node_modules"
                for seg in f.split(os.sep)
            )][:200]
            if not files:
                _cprint("  No files found in current directory.")
                return
            from spark_cli.curses_ui import curses_radiolist
            idx = curses_radiolist("/files — pick a file", files, selected=0)
            if idx is not None and 0 <= idx < len(files):
                self._pending_input.put(f"@{files[idx]} ")
                _cprint(f"  Added @{files[idx]} to your message.")
        except Exception as e:
            _cprint(f"  File picker unavailable: {e}")
            _cprint("  Tip: Install fzf for a better experience.")

    def _handle_memory_command(self) -> None:
        """Handle /memory — show recent memory entries stored by the agent."""
        try:
            memories_dir = get_spark_home() / "memories"
            if not memories_dir.exists():
                _cprint("  No memories directory found. Memory is built automatically as you chat.")
                return
            # Show MEMORY.md and USER.md if they exist
            shown = False
            for fname in ("MEMORY.md", "USER.md", "FEEDBACK.md"):
                fpath = memories_dir / fname
                if fpath.exists():
                    content = fpath.read_text(encoding="utf-8").strip()
                    if content:
                        _cprint(f"\n  ── {fname} ──")
                        # Show first 40 lines
                        lines = content.splitlines()[:40]
                        for line in lines:
                            _cprint(f"  {line}")
                        if len(content.splitlines()) > 40:
                            _cprint(f"  ... ({len(content.splitlines()) - 40} more lines)")
                        shown = True
            if not shown:
                _cprint("  Memory files exist but are empty — memories accumulate as you chat.")
                _cprint(f"  Memory location: {memories_dir}")
        except Exception as e:
            _cprint(f"  Could not read memories: {e}")

    def _handle_keys_command(self) -> None:
        """Handle /keys — show keyboard shortcuts reference."""
        _cprint("")
        _cprint("  ┌─ Keyboard Shortcuts ─────────────────────────────────────┐")
        _cprint("  │                                                            │")
        _cprint("  │  Input                                                     │")
        _cprint("  │    Enter           Send message (short, single-line input) │")
        _cprint("  │    Alt+Enter       New line (multi-line input)             │")
        _cprint("  │    Ctrl+J          New line (alternative)                  │")
        _cprint("  │    Ctrl+C          Interrupt running agent                 │")
        _cprint("  │    Ctrl+D          Exit / quit                             │")
        _cprint("  │                                                            │")
        _cprint("  │  Navigation                                                │")
        _cprint("  │    ↑ / ↓           Scroll input history                   │")
        _cprint("  │    Ctrl+↑/↓        Scroll message output                  │")
        _cprint("  │    Page Up/Down    Scroll output area                      │")
        _cprint("  │    Home/End        Jump to top/bottom of output            │")
        _cprint("  │                                                            │")
        _cprint("  │  Commands (type / to see all)                              │")
        _cprint("  │    /help           Show all commands                       │")
        _cprint("  │    /sessions       Browse and resume past sessions         │")
        _cprint("  │    /files          Fuzzy file picker → @path               │")
        _cprint("  │    /memory         Show stored memories                    │")
        _cprint("  │    /model          Switch AI model                         │")
        _cprint("  │    /skills         Browse and install skills               │")
        _cprint("  │    /clear          Clear screen, new session               │")
        _cprint("  │    /new            New session (keeps terminal)            │")
        _cprint("  │    /undo           Remove last exchange                    │")
        _cprint("  │    /retry          Resend last message                     │")
        _cprint("  │    /verbose        Cycle tool progress display             │")
        _cprint("  │    /quit           Exit                                    │")
        _cprint("  │                                                            │")
        _cprint("  └────────────────────────────────────────────────────────────┘")
        _cprint("")

    def _handle_branch_command(self, cmd_original: str) -> None:
        """Handle /branch [name] - fork the current session into a new independent copy.

        Copies the full conversation history to a new session so the user can
        explore a different approach without losing the original session state.
        Inspired by Claude Code's /branch command.
        """
        if not self.conversation_history:
            _cprint("  No conversation to branch - send a message first.")
            return

        if not self._session_db:
            _cprint("  Session database not available.")
            return

        parts = cmd_original.split(None, 1)
        branch_name = parts[1].strip() if len(parts) > 1 else ""

        # Generate the new session ID
        now = datetime.now()
        timestamp_str = now.strftime("%Y%m%d_%H%M%S")
        short_uuid = uuid.uuid4().hex[:6]
        new_session_id = f"{timestamp_str}_{short_uuid}"

        # Determine branch title
        if branch_name:
            branch_title = branch_name
        else:
            # Auto-generate from the current session title
            current_title = None
            if self._session_db:
                current_title = self._session_db.get_session_title(self.session_id)
            base = current_title or "branch"
            branch_title = self._session_db.get_next_title_in_lineage(base)

        # Save the current session's state before branching
        parent_session_id = self.session_id

        # End the old session
        try:
            self._session_db.end_session(self.session_id, "branched")
        except Exception:
            pass

        # Create the new session with parent link
        try:
            self._session_db.create_session(
                session_id=new_session_id,
                source=os.environ.get("SPARK_SESSION_SOURCE", "cli"),
                model=self.model,
                model_config={
                    "max_iterations": self.max_turns,
                    "reasoning_config": self.reasoning_config,
                },
                parent_session_id=parent_session_id,
            )
        except Exception as e:
            _cprint(f"  Failed to create branch session: {e}")
            return

        # Copy conversation history to the new session
        for msg in self.conversation_history:
            try:
                self._session_db.append_message(
                    session_id=new_session_id,
                    role=msg.get("role", "user"),
                    content=msg.get("content"),
                    tool_name=msg.get("tool_name") or msg.get("name"),
                    tool_calls=msg.get("tool_calls"),
                    tool_call_id=msg.get("tool_call_id"),
                    reasoning=msg.get("reasoning"),
                )
            except Exception:
                pass  # Best-effort copy

        # Set title on the branch
        try:
            self._session_db.set_session_title(new_session_id, branch_title)
        except Exception:
            pass

        # Switch to the new session
        self.session_id = new_session_id
        self.session_start = now
        self._pending_title = None
        self._resumed = True  # Prevents auto-title generation

        # Sync the agent
        if self.agent:
            self.agent.session_id = new_session_id
            self.agent.session_start = now
            self.agent.reset_session_state()
            if hasattr(self.agent, "_last_flushed_db_idx"):
                self.agent._last_flushed_db_idx = len(self.conversation_history)
            if hasattr(self.agent, "_todo_store"):
                try:
                    from tools.todo_tool import TodoStore

                    self.agent._todo_store = TodoStore()
                except Exception:
                    pass
            if hasattr(self.agent, "_invalidate_system_prompt"):
                self.agent._invalidate_system_prompt()

        msg_count = len(
            [m for m in self.conversation_history if m.get("role") == "user"]
        )
        _cprint(
            f'  ⑂ Branched session "{branch_title}"'
            f" ({msg_count} user message{'s' if msg_count != 1 else ''})"
        )
        _cprint(f"  Original session: {parent_session_id}")
        _cprint(f"  Branch session:   {new_session_id}")

