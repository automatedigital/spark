"""Usage/insights/kanban/MCP info commands for SparkCLI (mixin).

Extracted from core/cli/__init__.py (Phase 3). /usage, /insights, /kanban display
and MCP config-reload handling. Combined into SparkCLI via inheritance.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime

from agent.usage_pricing import (
    CanonicalUsage,
    estimate_usage_cost,
    format_duration_compact,
)


class _InfoCommandsMixin:
    def _show_usage(self):
        """Show rate limits (if available) and session token usage."""
        if not self.agent:
            print("(._.) No active agent -- send a message first.")
            return

        agent = self.agent
        calls = agent.session_api_calls

        if calls == 0:
            print("(._.) No API calls made yet in this session.")
            return

        # -- Rate limits (shown first when available) ----------------
        rl_state = agent.get_rate_limit_state()
        if rl_state and rl_state.has_data:
            from agent.rate_limit_tracker import format_rate_limit_display

            print()
            print(format_rate_limit_display(rl_state))
            print()

        # -- Session token usage -------------------------------------
        input_tokens = getattr(agent, "session_input_tokens", 0) or 0
        output_tokens = getattr(agent, "session_output_tokens", 0) or 0
        cache_read_tokens = getattr(agent, "session_cache_read_tokens", 0) or 0
        cache_write_tokens = getattr(agent, "session_cache_write_tokens", 0) or 0
        prompt = agent.session_prompt_tokens
        completion = agent.session_completion_tokens
        total = agent.session_total_tokens

        compressor = agent.context_compressor
        last_prompt = compressor.last_prompt_tokens
        ctx_len = compressor.context_length
        pct = min(100, (last_prompt / ctx_len * 100)) if ctx_len else 0
        compressions = compressor.compression_count

        msg_count = len(self.conversation_history)
        cost_result = estimate_usage_cost(
            agent.model,
            CanonicalUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_write_tokens=cache_write_tokens,
            ),
            provider=getattr(agent, "provider", None),
            base_url=getattr(agent, "base_url", None),
        )
        elapsed = format_duration_compact(
            (datetime.now() - self.session_start).total_seconds()
        )

        print("  📊 Session Token Usage")
        print(f"  {'-' * 40}")
        print(f"  Model:                     {agent.model}")
        print(f"  Input tokens:              {input_tokens:>10,}")
        print(f"  Cache read tokens:         {cache_read_tokens:>10,}")
        print(f"  Cache write tokens:        {cache_write_tokens:>10,}")
        print(f"  Output tokens:             {output_tokens:>10,}")
        print(f"  Prompt tokens (total):     {prompt:>10,}")
        print(f"  Completion tokens:         {completion:>10,}")
        print(f"  Total tokens:              {total:>10,}")
        print(f"  API calls:                 {calls:>10,}")
        print(f"  Session duration:          {elapsed:>10}")
        print(f"  Cost status:              {cost_result.status:>10}")
        print(f"  Cost source:              {cost_result.source:>10}")
        if cost_result.amount_usd is not None:
            prefix = "~" if cost_result.status == "estimated" else ""
            print(
                f"  Total cost:              {prefix}${float(cost_result.amount_usd):>10.4f}"
            )
        elif cost_result.status == "included":
            print(f"  Total cost:              {'included':>10}")
        else:
            print(f"  Total cost:              {'n/a':>10}")
        print(f"  {'-' * 40}")
        print(f"  Current context:  {last_prompt:,} / {ctx_len:,} ({pct:.0f}%)")
        print(f"  Messages:         {msg_count}")
        print(f"  Compressions:     {compressions}")
        if cost_result.status == "unknown":
            print(f"  Note:             Pricing unknown for {agent.model}")

        if self.verbose:
            logging.getLogger().setLevel(logging.DEBUG)
            for noisy in (
                "openai",
                "openai._base_client",
                "httpx",
                "httpcore",
                "asyncio",
                "hpack",
                "grpc",
                "modal",
            ):
                logging.getLogger(noisy).setLevel(logging.WARNING)
        else:
            logging.getLogger().setLevel(logging.INFO)
            for quiet_logger in (
                "tools",
                "run_agent",
                "trajectory_compressor",
                "cron",
                "spark_cli",
            ):
                logging.getLogger(quiet_logger).setLevel(logging.ERROR)

    def _show_insights(self, command: str = "/insights"):
        """Show usage insights and analytics from session history."""
        # Parse optional --days flag
        parts = command.split()
        days = 30
        source = None
        i = 1
        while i < len(parts):
            if parts[i] == "--days" and i + 1 < len(parts):
                try:
                    days = int(parts[i + 1])
                except ValueError:
                    print(f"  Invalid --days value: {parts[i + 1]}")
                    return
                i += 2
            elif parts[i] == "--source" and i + 1 < len(parts):
                source = parts[i + 1]
                i += 2
            else:
                i += 1

        try:
            from core.spark_state import SessionDB
            from agent.insights import InsightsEngine

            db = SessionDB()
            engine = InsightsEngine(db)
            report = engine.generate(days=days, source=source)
            print(engine.format_terminal(report))
            db.close()
        except Exception as e:
            print(f"  Error generating insights: {e}")

    def _handle_kanban_slash(self, command: str = "/kanban"):
        """Show Kanban board summary or run lightweight subcommands."""
        parts = command.split(maxsplit=1)
        args = parts[1].strip() if len(parts) > 1 else ""
        try:
            from core import kanban_db as kb

            kb.init_kanban_db()
        except Exception as e:
            print(f"  Kanban unavailable: {e}")
            return

        from core import kanban_db as kb

        if not args:
            board = kb.get_board(board_slug="default")
            print("  📋 Kanban (board `default`)\n")
            for col in ("triage", "todo", "ready", "running", "blocked", "done"):
                tasks = board["columns"].get(col, []) or []
                print(f"  {col} ({len(tasks)})")
                for t in tasks[:10]:
                    tid = t.get("id", "")
                    title = (t.get("title") or "")[:72]
                    who = t.get("assignee") or "—"
                    print(f"    • {tid}  {title}  — {who}")
                if len(tasks) > 10:
                    print(f"    … +{len(tasks) - 10} more")
                print()
            print("  Try `/kanban show <task_id>` or `/kanban dispatch`.\n")
            return

        sub_parts = args.split(maxsplit=1)
        sub = sub_parts[0].lower()
        rest = sub_parts[1].strip() if len(sub_parts) > 1 else ""

        if sub == "dispatch":
            import asyncio
            from spark_cli.kanban_dispatch import run_dispatch_tick

            try:
                result = asyncio.run(run_dispatch_tick(max_tasks=3))
                print(
                    "  Dispatcher claimed/spawned "
                    f"{result.get('claimed', 0)} task(s): "
                    f"{', '.join(result.get('task_ids', [])) or '-'}\n"
                )
            except Exception as e:
                print(f"  Dispatch error: {e}\n")
            return

        if sub == "show" and rest:
            tid = rest.split()[0]
            detail = kb.get_task_detail(tid)
            if not detail:
                print(f"  Task `{tid}` not found.\n")
                return
            body = (detail.get("body") or "")[:1600]
            print(f"  {detail.get('title')} ({detail['id']})")
            print(f"  status: {detail.get('status')}  assignee: {detail.get('assignee')}\n")
            print(f"  {body}\n")
            return

        print("  Unknown /kanban subcommand. Try `/kanban`, `/kanban show <id>`, `/kanban dispatch`.\n")

    def _check_config_mcp_changes(self) -> None:
        """Detect mcp_servers changes in config.yaml and auto-reload MCP connections.

        Called from process_loop every CONFIG_WATCH_INTERVAL seconds.
        Compares config.yaml mtime + mcp_servers section against the last
        known state.  When a change is detected, triggers _reload_mcp() and
        informs the user so they know the tool list has been refreshed.
        """
        import time
        import yaml as _yaml

        CONFIG_WATCH_INTERVAL = 5.0  # seconds between config.yaml stat() calls

        now = time.monotonic()
        if now - self._last_config_check < CONFIG_WATCH_INTERVAL:
            return
        self._last_config_check = now

        from spark_cli.config import get_config_path as _get_config_path

        cfg_path = _get_config_path()
        if not cfg_path.exists():
            return

        try:
            mtime = cfg_path.stat().st_mtime
        except OSError:
            return

        if mtime == self._config_mtime:
            return  # File unchanged - fast path

        # File changed - check whether mcp_servers section changed
        self._config_mtime = mtime
        try:
            with open(cfg_path, encoding="utf-8") as f:
                new_cfg = _yaml.safe_load(f) or {}
        except Exception:
            return

        new_mcp = new_cfg.get("mcp_servers") or {}
        if new_mcp == self._config_mcp_servers:
            return  # mcp_servers unchanged (some other section was edited)

        self._config_mcp_servers = new_mcp
        # Notify user and reload.  Run in a separate thread with a hard
        # timeout so a hung MCP server cannot block the process_loop
        # indefinitely (which would freeze the entire TUI).
        print()
        print("🔄 MCP server config changed - reloading connections...")
        _reload_thread = threading.Thread(target=self._reload_mcp, daemon=True)
        _reload_thread.start()
        _reload_thread.join(timeout=30)
        if _reload_thread.is_alive():
            print(
                "  WARN  MCP reload timed out (30s). Some servers may not have reconnected."
            )

    def _reload_mcp(self):
        """Reload MCP servers: disconnect all, re-read config.yaml, reconnect.

        After reconnecting, refreshes the agent's tool list so the model
        sees the updated tools on the next turn.
        """
        try:
            from tools.mcp_tool import (
                shutdown_mcp_servers,
                discover_mcp_tools,
                _servers,
                _lock,
            )

            # Capture old server names
            with _lock:
                old_servers = set(_servers.keys())

            if not self._command_running:
                print("🔄 Reloading MCP servers...")

            # Shutdown existing connections
            shutdown_mcp_servers()

            # Reconnect (reads config.yaml fresh)
            new_tools = discover_mcp_tools()

            # Compute what changed
            with _lock:
                connected_servers = set(_servers.keys())

            added = connected_servers - old_servers
            removed = old_servers - connected_servers
            reconnected = connected_servers & old_servers

            if reconnected:
                print(f"  ♻️  Reconnected: {', '.join(sorted(reconnected))}")
            if added:
                print(f"  ➕ Added: {', '.join(sorted(added))}")
            if removed:
                print(f"  ➖ Removed: {', '.join(sorted(removed))}")
            if not connected_servers:
                print("  No MCP servers connected.")
            else:
                print(
                    f"  🔧 {len(new_tools)} tool(s) available from {len(connected_servers)} server(s)"
                )

            # Refresh the agent's tool list so the model can call new tools
            if self.agent is not None:
                from core.model_tools import get_tool_definitions

                self.agent.tools = get_tool_definitions(
                    enabled_toolsets=self.agent.enabled_toolsets
                    if hasattr(self.agent, "enabled_toolsets")
                    else None,
                    quiet_mode=True,
                )
                self.agent.valid_tool_names = (
                    {tool["function"]["name"] for tool in self.agent.tools}
                    if self.agent.tools
                    else set()
                )

            # Inject a message at the END of conversation history so the
            # model knows tools changed.  Appended after all existing
            # messages to preserve prompt-cache for the prefix.
            change_parts = []
            if added:
                change_parts.append(f"Added servers: {', '.join(sorted(added))}")
            if removed:
                change_parts.append(f"Removed servers: {', '.join(sorted(removed))}")
            if reconnected:
                change_parts.append(
                    f"Reconnected servers: {', '.join(sorted(reconnected))}"
                )
            tool_summary = (
                f"{len(new_tools)} MCP tool(s) now available"
                if new_tools
                else "No MCP tools available"
            )
            change_detail = ". ".join(change_parts) + ". " if change_parts else ""
            self.conversation_history.append(
                {
                    "role": "user",
                    "content": f"[SYSTEM: MCP servers have been reloaded. {change_detail}{tool_summary}. The tool list for this conversation has been updated accordingly.]",
                }
            )

            # Persist session immediately so the session log reflects the
            # updated tools list (self.agent.tools was refreshed above).
            if self.agent is not None:
                try:
                    self.agent._persist_session(
                        self.conversation_history,
                        self.conversation_history,
                    )
                except Exception:
                    pass  # Best-effort

            print(
                f"  ✅ Agent updated - {len(self.agent.tools if self.agent else [])} tool(s) available"
            )

        except Exception as e:
            print(f"  ❌ MCP reload failed: {e}")

    # ====================================================================
    # Tool-call generation indicator (shown during streaming)
    # ====================================================================

