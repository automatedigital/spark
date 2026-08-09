"""Tool-call execution for AIAgent: dispatch, concurrency, and budgets.

Extracted from run_agent/__init__.py. These methods are mixed into AIAgent and
use instance state resolved at runtime through the MRO, so this is a pure
relocation with no behaviour change.
"""

from __future__ import annotations

import json
import logging
import os
import random
import time

from agent.display import KawaiiSpinner, _detect_tool_failure
from agent.display import build_tool_preview as _build_tool_preview
from agent.display import get_cute_tool_message as _get_cute_tool_message_impl
from agent.display import get_tool_emoji as _get_tool_emoji
from agent.efficiency_metrics import ToolRuntimeAccounting
from core.model_tools import handle_function_call
from core.run_agent.parallelism import _MAX_TOOL_WORKERS as _MAX_TOOL_WORKERS
from core.run_agent.parallelism import _is_destructive_command as _is_destructive_command
from core.tool_scheduler import ToolBatchScheduler, build_tool_dag
from tools.budget_config import BudgetConfig
from tools.tool_result_storage import enforce_turn_budget, maybe_persist_tool_result


def get_active_env(*args, **kwargs):
    """Resolve a terminal environment only when a tool turn needs it."""
    from tools.terminal_tool import get_active_env as implementation

    return implementation(*args, **kwargs)


logger = logging.getLogger(__name__)


class _ToolExecutionMixin:
    def _execute_tool_calls(self, assistant_message, messages: list, effective_task_id: str, api_call_count: int = 0) -> None:
        """Execute tool calls from the assistant message and append results to messages.

        Dispatches to concurrent execution only for batches that look
        independent: read-only tools may always share the parallel path, while
        file reads/writes may do so only when their target paths do not overlap.
        """
        tool_calls = assistant_message.tool_calls

        # Allow _vprint during tool execution even with stream consumers
        self._executing_tools = True
        try:
            valid_batch = True
            for tool_call in tool_calls:
                try:
                    parsed = json.loads(tool_call.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    valid_batch = False
                    break
                if not isinstance(parsed, dict):
                    valid_batch = False
                    break
            if (
                len(tool_calls) <= 1
                or not self.dependency_scheduler
                or (
                    isinstance(self.tool_delay, (int, float))
                    and self.tool_delay > 0
                )
                or not valid_batch
            ):
                return self._execute_tool_calls_sequential(
                    assistant_message, messages, effective_task_id, api_call_count
                )

            return self._execute_tool_calls_concurrent(
                assistant_message, messages, effective_task_id, api_call_count
            )
        finally:
            self._executing_tools = False

    def _invoke_tool(self, function_name: str, function_args: dict, effective_task_id: str,
                     tool_call_id: str | None = None) -> str:
        """Invoke a single tool and return the result string. No display logic.

        Handles both agent-level tools (todo, memory, etc.) and registry-dispatched
        tools. Used by the concurrent execution path; the sequential path retains
        its own inline invocation for backward-compatible display handling.
        """
        try:
            from tools.facades import normalize_facade_call
            function_name, function_args = normalize_facade_call(function_name, function_args)
        except ValueError as exc:
            return json.dumps({"error": str(exc)}, ensure_ascii=False)
        function_args = self._inject_working_dir(function_name, function_args)
        # Check plugin hooks for a block directive before executing anything.
        block_message: str | None = None
        try:
            from spark_cli.plugins import get_pre_tool_call_block_message
            block_message = get_pre_tool_call_block_message(
                function_name, function_args, task_id=effective_task_id or "",
            )
        except Exception:
            logger.debug("Ignoring error in _invoke_tool()", exc_info=True)
        if block_message is not None:
            return json.dumps({"error": block_message}, ensure_ascii=False)

        try:
            if function_name == "todo":
                from tools.todo_tool import todo_tool as _todo_tool
                return _todo_tool(
                    todos=function_args.get("todos"),
                    merge=function_args.get("merge", False),
                    store=self._todo_store,
                )
            elif function_name == "session_search":
                if not self._session_db:
                    return json.dumps({"success": False, "error": "Session database not available."})
                from tools.session_search_tool import session_search as _session_search
                return _session_search(
                    query=function_args.get("query", ""),
                    role_filter=function_args.get("role_filter"),
                    limit=function_args.get("limit", 3),
                    db=self._session_db,
                    current_session_id=self.session_id,
                )
            elif function_name == "memory":
                target = function_args.get("target", "memory")
                from tools.memory_tool import memory_tool as _memory_tool
                result = _memory_tool(
                    action=function_args.get("action"),
                    target=target,
                    content=function_args.get("content"),
                    old_text=function_args.get("old_text"),
                    store=self._memory_store,
                )
                # Bridge: notify external memory provider of built-in memory writes
                if self._memory_manager and function_args.get("action") in ("add", "replace"):
                    try:
                        self._memory_manager.on_memory_write(
                            function_args.get("action", ""),
                            target,
                            function_args.get("content", ""),
                        )
                    except Exception:
                        logger.debug("Ignoring error in _invoke_tool()", exc_info=True)
                return result
            elif self._memory_manager and self._memory_manager.has_tool(function_name):
                return self._memory_manager.handle_tool_call(function_name, function_args)
            elif function_name == "clarify":
                from tools.clarify_tool import clarify_tool as _clarify_tool
                return _clarify_tool(
                    question=function_args.get("question", ""),
                    choices=function_args.get("choices"),
                    callback=self.clarify_callback,
                )
            elif function_name == "delegate_task":
                from tools.delegate_tool import delegate_task as _delegate_task
                return _delegate_task(
                    goal=function_args.get("goal"),
                    context=function_args.get("context"),
                    toolsets=function_args.get("toolsets"),
                    tasks=function_args.get("tasks"),
                    max_iterations=function_args.get("max_iterations"),
                    parent_agent=self,
                )
            else:
                return handle_function_call(
                    function_name, function_args, effective_task_id,
                    tool_call_id=tool_call_id,
                    session_id=self.session_id or "",
                    enabled_tools=list(self.valid_tool_names) if self.valid_tool_names else None,
                    skip_pre_tool_call_hook=True,
                )
        finally:
            self._on_tool_dispatched(function_name)

    def _tool_budget_config(self, tool_name: str | None = None) -> BudgetConfig:
        """Allocate tool-result context from the current model/request state."""
        compressor = getattr(self, "context_compressor", None)
        context_length = int(getattr(compressor, "context_length", 0) or 0)
        prompt_tokens = int(getattr(compressor, "last_prompt_tokens", 0) or 0)
        remaining = max(0, context_length - prompt_tokens) if context_length else None
        phase = str(getattr(self, "_request_phase", "work") or "work")
        result_kind = "text"
        if tool_name in {"web_search", "search_files", "session_search"}:
            result_kind = "search"
        elif tool_name in {"terminal", "process"}:
            result_kind = "terminal"
        elif tool_name in {"connectors", "artifact_read"}:
            result_kind = "structured"
        return BudgetConfig.for_request(
            remaining_context_tokens=remaining,
            task_phase=phase,
            result_kind=result_kind,
            provider_count_tokens=getattr(self, "_provider_token_counter", None),
        )

    def _execute_tool_calls_concurrent(self, assistant_message, messages: list, effective_task_id: str, api_call_count: int = 0) -> None:
        """Execute multiple tool calls concurrently using a thread pool.

        Results are collected in the original tool-call order and appended to
        messages so the API sees them in the expected sequence.
        """
        tool_calls = assistant_message.tool_calls
        num_tools = len(tool_calls)

        # ── Pre-flight: interrupt check ──────────────────────────────────
        if self._interrupt_requested:
            print(f"{self.log_prefix}⚡ Interrupt: skipping {num_tools} tool call(s)")
            for tc in tool_calls:
                messages.append({
                    "role": "tool",
                    "content": f"[Tool execution cancelled — {tc.function.name} was skipped due to user interrupt]",
                    "tool_call_id": tc.id,
                })
            return

        # ── Parse args + pre-execution bookkeeping ───────────────────────
        parsed_calls = []  # list of (tool_call, function_name, function_args)
        for tool_call in tool_calls:
            function_name = tool_call.function.name

            # Reset nudge counters
            if function_name == "memory":
                self._turns_since_memory = 0
            elif function_name == "skill_manage":
                self._iters_since_skill = 0

            try:
                function_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                function_args = {}
            if not isinstance(function_args, dict):
                function_args = {}
            try:
                from tools.facades import normalize_facade_call
                function_name, function_args = normalize_facade_call(function_name, function_args)
            except ValueError:
                # Let _invoke_tool produce the aligned error result.  Retain
                # the facade call here so invalid calls cannot trigger legacy
                # checkpoints or bookkeeping.
                parsed_calls.append((tool_call, function_name, function_args))
                continue

            # Checkpoint for file-mutating tools
            if function_name in ("write_file", "patch") and self._checkpoint_mgr.enabled:
                try:
                    file_path = function_args.get("path", "")
                    if file_path:
                        work_dir = self._checkpoint_mgr.get_working_dir_for_path(file_path)
                        self._checkpoint_mgr.ensure_checkpoint(work_dir, f"before {function_name}")
                except Exception:
                    logger.debug("Ignoring error in _execute_tool_calls_concurrent()", exc_info=True)

            # Checkpoint before destructive terminal commands
            if function_name == "terminal" and self._checkpoint_mgr.enabled:
                try:
                    cmd = function_args.get("command", "")
                    if _is_destructive_command(cmd):
                        cwd = function_args.get("workdir") or os.getenv("TERMINAL_CWD", os.getcwd())
                        self._checkpoint_mgr.ensure_checkpoint(
                            cwd, f"before terminal: {cmd[:60]}"
                        )
                except Exception:
                    logger.debug("Ignoring error in _execute_tool_calls_concurrent()", exc_info=True)

            parsed_calls.append((tool_call, function_name, function_args))

        # ── Logging / callbacks ──────────────────────────────────────────
        tool_names_str = ", ".join(name for _, name, _ in parsed_calls)
        if not self.quiet_mode:
            print(f"  ⚡ Concurrent: {num_tools} tool calls — {tool_names_str}")
            for i, (_tc, name, args) in enumerate(parsed_calls, 1):
                args_str = json.dumps(args, ensure_ascii=False)
                if self.verbose_logging:
                    print(f"  📞 Tool {i}: {name}({list(args.keys())})")
                    print(f"     Args: {args_str}")
                else:
                    args_preview = args_str[:self.log_prefix_chars] + "..." if len(args_str) > self.log_prefix_chars else args_str
                    print(f"  📞 Tool {i}: {name}({list(args.keys())}) - {args_preview}")

        for _tc, name, args in parsed_calls:
            if self.tool_progress_callback:
                preview = _build_tool_preview(name, args)
                self._queue_tool_callback(
                    self.tool_progress_callback, "tool.started", name, preview, args
                )

        for tc, name, args in parsed_calls:
            if self.tool_start_callback:
                try:
                    self.tool_start_callback(tc.id, name, args)
                except Exception as cb_err:
                    logging.debug("Tool start callback error: %s", cb_err)

        # ── Concurrent execution ─────────────────────────────────────────
        # Each slot holds (function_name, function_args, function_result, duration, error_flag)
        results = [None] * num_tools
        # Start spinner for CLI mode (skip when TUI handles tool progress)
        spinner = None
        if self._should_emit_quiet_tool_messages() and self._should_start_quiet_spinner():
            face = random.choice(KawaiiSpinner.KAWAII_WAITING)
            spinner = KawaiiSpinner(f"{face} ⚡ running {num_tools} tools concurrently", spinner_type='dots', print_fn=self._print_fn)
            spinner.start()

        try:
            nodes = build_tool_dag(tool_calls)
            timeout_raw = os.environ.get("SPARK_TOOL_BATCH_TIMEOUT", "")
            try:
                timeout = float(timeout_raw) if timeout_raw else None
            except ValueError:
                timeout = None
            deadline = time.monotonic() + timeout if timeout and timeout > 0 else None
            scheduled = ToolBatchScheduler(max_workers=_MAX_TOOL_WORKERS).execute(
                nodes,
                lambda node: self._invoke_tool(
                    node.name, node.args, effective_task_id, node.tool_call_id
                ),
                interrupted=lambda: self._interrupt_requested,
                batch_deadline=deadline,
            )
            for item in scheduled:
                is_error, _ = _detect_tool_failure(item.name, item.content)
                results[item.index] = (
                    item.name, item.args, item.content, item.duration, is_error
                )
                if is_error:
                    logger.info(
                        "tool %s failed (%.2fs): %s",
                        item.name, item.duration, item.content[:200],
                    )
                else:
                    logger.info(
                        "tool %s completed (%.2fs, %d chars)",
                        item.name, item.duration, len(item.content),
                    )
                try:
                    self._efficiency_recorder.record_tool_call(
                        ToolRuntimeAccounting(
                            session_id=self.session_id,
                            iteration=api_call_count,
                            tool_name=item.name,
                            queue_wait_ms=round(item.queue_wait * 1000, 3),
                            execution_ms=round(item.duration * 1000, 3),
                            result_bytes=len(
                                str(item.content).encode("utf-8", errors="replace")
                            ),
                            failed=is_error,
                        )
                    )
                except Exception:
                    logger.debug("Efficiency tool accounting failed", exc_info=True)
        finally:
            if spinner:
                # Build a summary message for the spinner stop
                completed = sum(1 for r in results if r is not None)
                total_dur = sum(r[3] for r in results if r is not None)
                spinner.stop(f"⚡ {completed}/{num_tools} tools completed in {total_dur:.1f}s total")

        # ── Post-execution: display per-tool results ─────────────────────
        for i, (tc, name, args) in enumerate(parsed_calls):
            r = results[i]
            if r is None:
                # Shouldn't happen, but safety fallback
                function_result = f"Error executing tool '{name}': thread did not return a result"
                tool_duration = 0.0
            else:
                function_name, function_args, function_result, tool_duration, is_error = r

                if is_error:
                    result_preview = function_result[:200] if len(function_result) > 200 else function_result
                    logger.warning("Tool %s returned error (%.2fs): %s", function_name, tool_duration, result_preview)

                self._queue_tool_callback(
                    self.tool_progress_callback,
                    "tool.completed", function_name, None, None,
                    duration=tool_duration, is_error=is_error,
                    result_lines=sum(
                        1 for ln in str(function_result or "").splitlines() if ln.strip()
                    ),
                )

                if self.verbose_logging:
                    logging.debug(f"Tool {function_name} completed in {tool_duration:.2f}s")
                    logging.debug(f"Tool result ({len(function_result)} chars): {function_result}")

            # Print cute message per tool
            if self._should_emit_quiet_tool_messages():
                cute_msg = _get_cute_tool_message_impl(name, args, tool_duration, result=function_result)
                self._safe_print(f"  {cute_msg}")
            elif not self.quiet_mode:
                if self.verbose_logging:
                    print(f"  ✅ Tool {i+1} completed in {tool_duration:.2f}s")
                    print(f"     Result: {function_result}")
                else:
                    response_preview = function_result[:self.log_prefix_chars] + "..." if len(function_result) > self.log_prefix_chars else function_result
                    print(f"  ✅ Tool {i+1} completed in {tool_duration:.2f}s - {response_preview}")

            self._current_tool = None
            self._touch_activity(f"tool completed: {name} ({tool_duration:.1f}s)")

            if self.tool_complete_callback:
                try:
                    self.tool_complete_callback(tc.id, name, args, function_result)
                except Exception as cb_err:
                    logging.debug("Tool complete callback error: %s", cb_err)

            function_result = maybe_persist_tool_result(
                content=function_result,
                tool_name=name,
                tool_use_id=tc.id,
                env=get_active_env(effective_task_id),
                config=self._tool_budget_config(name),
                task_id=effective_task_id,
            )

            subdir_hints = self._subdirectory_hints.check_tool_call(name, args)
            if subdir_hints:
                function_result += subdir_hints

            tool_msg = {
                "role": "tool",
                "content": function_result,
                "tool_call_id": tc.id,
            }
            messages.append(tool_msg)

        # ── Per-turn aggregate budget enforcement ─────────────────────────
        num_tools = len(parsed_calls)
        if num_tools > 0:
            turn_tool_msgs = messages[-num_tools:]
            enforce_turn_budget(
                turn_tool_msgs,
                env=get_active_env(effective_task_id),
                config=self._tool_budget_config(),
                tool_names=[function_name for _, function_name, _ in parsed_calls],
                task_id=effective_task_id,
            )

    def _execute_tool_calls_sequential(self, assistant_message, messages: list, effective_task_id: str, api_call_count: int = 0) -> None:
        """Execute tool calls sequentially (original behavior). Used for single calls or interactive tools."""
        for i, tool_call in enumerate(assistant_message.tool_calls, 1):
            # SAFETY: check interrupt BEFORE starting each tool.
            # If the user sent "stop" during a previous tool's execution,
            # do NOT start any more tools -- skip them all immediately.
            if self._interrupt_requested:
                remaining_calls = assistant_message.tool_calls[i-1:]
                if remaining_calls:
                    self._vprint(f"{self.log_prefix}⚡ Interrupt: skipping {len(remaining_calls)} tool call(s)", force=True)
                for skipped_tc in remaining_calls:
                    skipped_name = skipped_tc.function.name
                    skip_msg = {
                        "role": "tool",
                        "content": f"[Tool execution cancelled — {skipped_name} was skipped due to user interrupt]",
                        "tool_call_id": skipped_tc.id,
                    }
                    messages.append(skip_msg)
                break

            function_name = tool_call.function.name

            try:
                function_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError as e:
                logging.warning(f"Unexpected JSON error after validation: {e}")
                function_args = {}
            if not isinstance(function_args, dict):
                function_args = {}
            try:
                from tools.facades import normalize_facade_call
                function_name, function_args = normalize_facade_call(function_name, function_args)
            except ValueError as exc:
                function_result = json.dumps({"error": str(exc)}, ensure_ascii=False)
                messages.append({
                    "role": "tool", "content": function_result,
                    "tool_call_id": tool_call.id,
                })
                continue
            function_args = self._inject_working_dir(function_name, function_args)

            # Check plugin hooks for a block directive before executing.
            _block_msg: str | None = None
            try:
                from spark_cli.plugins import get_pre_tool_call_block_message
                _block_msg = get_pre_tool_call_block_message(
                    function_name, function_args, task_id=effective_task_id or "",
                )
            except Exception:
                logger.debug("Ignoring error in _execute_tool_calls_sequential()", exc_info=True)

            if _block_msg is not None:
                # Tool blocked by plugin policy — skip counter resets.
                # Execution is handled below in the tool dispatch chain.
                pass
            else:
                # Reset nudge counters when the relevant tool is actually used
                if function_name == "memory":
                    self._turns_since_memory = 0
                elif function_name == "skill_manage":
                    self._iters_since_skill = 0

            if not self.quiet_mode:
                args_str = json.dumps(function_args, ensure_ascii=False)
                if self.verbose_logging:
                    print(f"  📞 Tool {i}: {function_name}({list(function_args.keys())})")
                    print(f"     Args: {args_str}")
                else:
                    args_preview = args_str[:self.log_prefix_chars] + "..." if len(args_str) > self.log_prefix_chars else args_str
                    print(f"  📞 Tool {i}: {function_name}({list(function_args.keys())}) - {args_preview}")

            if _block_msg is None:
                self._current_tool = function_name
                self._touch_activity(f"executing tool: {function_name}")

            # Set activity callback for long-running tool execution (terminal
            # commands, etc.) so the gateway's inactivity monitor doesn't kill
            # the agent while a command is running.
            if _block_msg is None:
                try:
                    from tools.environments.base import (
                        set_activity_callback,
                        set_output_callback,
                    )
                    set_activity_callback(self._touch_activity)
                    # Stream stdout lines incrementally to the progress callback
                    # so the TUI can show live output instead of only the final
                    # buffer. The TUI decides whether to render (tool_progress_mode).
                    if self.tool_progress_callback:
                        def _stream_output(line: str, _fn=function_name) -> None:
                            # Skip internal CWD-tracking sentinel lines.
                            if "__SPARK_CWD_" in line:
                                return
                            try:
                                self.tool_progress_callback("tool.output", _fn, line)
                            except Exception:
                                logger.debug("Ignoring error in _stream_output()", exc_info=True)
                        set_output_callback(_stream_output)
                    else:
                        set_output_callback(None)
                except Exception:
                    logger.debug("Ignoring error in _execute_tool_calls_sequential()", exc_info=True)

            if _block_msg is None and self.tool_progress_callback:
                try:
                    preview = _build_tool_preview(function_name, function_args)
                    self.tool_progress_callback("tool.started", function_name, preview, function_args)
                except Exception as cb_err:
                    logging.debug(f"Tool progress callback error: {cb_err}")

            if _block_msg is None and self.tool_start_callback:
                try:
                    self.tool_start_callback(tool_call.id, function_name, function_args)
                except Exception as cb_err:
                    logging.debug(f"Tool start callback error: {cb_err}")

            # Checkpoint: snapshot working dir before file-mutating tools
            if _block_msg is None and function_name in ("write_file", "patch") and self._checkpoint_mgr.enabled:
                try:
                    file_path = function_args.get("path", "")
                    if file_path:
                        work_dir = self._checkpoint_mgr.get_working_dir_for_path(file_path)
                        self._checkpoint_mgr.ensure_checkpoint(
                            work_dir, f"before {function_name}"
                        )
                except Exception:
                    pass  # never block tool execution

            # Checkpoint before destructive terminal commands
            if _block_msg is None and function_name == "terminal" and self._checkpoint_mgr.enabled:
                try:
                    cmd = function_args.get("command", "")
                    if _is_destructive_command(cmd):
                        cwd = function_args.get("workdir") or os.getenv("TERMINAL_CWD", os.getcwd())
                        self._checkpoint_mgr.ensure_checkpoint(
                            cwd, f"before terminal: {cmd[:60]}"
                        )
                except Exception:
                    pass  # never block tool execution

            tool_start_time = time.time()

            if _block_msg is not None:
                # Tool blocked by plugin policy — return error without executing.
                function_result = json.dumps({"error": _block_msg}, ensure_ascii=False)
                tool_duration = 0.0
            elif function_name == "todo":
                from tools.todo_tool import todo_tool as _todo_tool
                function_result = _todo_tool(
                    todos=function_args.get("todos"),
                    merge=function_args.get("merge", False),
                    store=self._todo_store,
                )
                tool_duration = time.time() - tool_start_time
                if self._should_emit_quiet_tool_messages():
                    self._vprint(f"  {_get_cute_tool_message_impl('todo', function_args, tool_duration, result=function_result)}")
            elif function_name == "session_search":
                if not self._session_db:
                    function_result = json.dumps({"success": False, "error": "Session database not available."})
                else:
                    from tools.session_search_tool import session_search as _session_search
                    function_result = _session_search(
                        query=function_args.get("query", ""),
                        role_filter=function_args.get("role_filter"),
                        limit=function_args.get("limit", 3),
                        db=self._session_db,
                        current_session_id=self.session_id,
                    )
                tool_duration = time.time() - tool_start_time
                if self._should_emit_quiet_tool_messages():
                    self._vprint(f"  {_get_cute_tool_message_impl('session_search', function_args, tool_duration, result=function_result)}")
            elif function_name == "memory":
                target = function_args.get("target", "memory")
                from tools.memory_tool import memory_tool as _memory_tool
                function_result = _memory_tool(
                    action=function_args.get("action"),
                    target=target,
                    content=function_args.get("content"),
                    old_text=function_args.get("old_text"),
                    store=self._memory_store,
                )
                tool_duration = time.time() - tool_start_time
                if self._should_emit_quiet_tool_messages():
                    self._vprint(f"  {_get_cute_tool_message_impl('memory', function_args, tool_duration, result=function_result)}")
            elif function_name == "clarify":
                from tools.clarify_tool import clarify_tool as _clarify_tool
                function_result = _clarify_tool(
                    question=function_args.get("question", ""),
                    choices=function_args.get("choices"),
                    callback=self.clarify_callback,
                )
                tool_duration = time.time() - tool_start_time
                if self._should_emit_quiet_tool_messages():
                    self._vprint(f"  {_get_cute_tool_message_impl('clarify', function_args, tool_duration, result=function_result)}")
            elif function_name == "delegate_task":
                from tools.delegate_tool import delegate_task as _delegate_task
                tasks_arg = function_args.get("tasks")
                if tasks_arg and isinstance(tasks_arg, list):
                    spinner_label = f"🔀 delegating {len(tasks_arg)} tasks"
                else:
                    goal_preview = (function_args.get("goal") or "")[:30]
                    spinner_label = f"🔀 {goal_preview}" if goal_preview else "🔀 delegating"
                spinner = None
                if self._should_emit_quiet_tool_messages() and self._should_start_quiet_spinner():
                    face = random.choice(KawaiiSpinner.KAWAII_WAITING)
                    spinner = KawaiiSpinner(f"{face} {spinner_label}", spinner_type='dots', print_fn=self._print_fn)
                    spinner.start()
                self._delegate_spinner = spinner
                _delegate_result = None
                try:
                    function_result = _delegate_task(
                        goal=function_args.get("goal"),
                        context=function_args.get("context"),
                        toolsets=function_args.get("toolsets"),
                        tasks=tasks_arg,
                        max_iterations=function_args.get("max_iterations"),
                        parent_agent=self,
                    )
                    _delegate_result = function_result
                finally:
                    self._delegate_spinner = None
                    tool_duration = time.time() - tool_start_time
                    cute_msg = _get_cute_tool_message_impl('delegate_task', function_args, tool_duration, result=_delegate_result)
                    if spinner:
                        spinner.stop(cute_msg)
                    elif self._should_emit_quiet_tool_messages():
                        self._vprint(f"  {cute_msg}")
            elif self._context_engine_tool_names and function_name in self._context_engine_tool_names:
                # Context engine tools (lcm_grep, lcm_describe, lcm_expand, etc.)
                spinner = None
                if self.quiet_mode and not self.tool_progress_callback:
                    face = random.choice(KawaiiSpinner.KAWAII_WAITING)
                    emoji = _get_tool_emoji(function_name)
                    preview = _build_tool_preview(function_name, function_args) or function_name
                    spinner = KawaiiSpinner(f"{face} {emoji} {preview}", spinner_type='dots', print_fn=self._print_fn)
                    spinner.start()
                _ce_result = None
                try:
                    function_result = self.context_compressor.handle_tool_call(function_name, function_args, messages=messages)
                    _ce_result = function_result
                except Exception as tool_error:
                    function_result = json.dumps({"error": f"Context engine tool '{function_name}' failed: {tool_error}"})
                    logger.error("context_engine.handle_tool_call raised for %s: %s", function_name, tool_error, exc_info=True)
                finally:
                    tool_duration = time.time() - tool_start_time
                    cute_msg = _get_cute_tool_message_impl(function_name, function_args, tool_duration, result=_ce_result)
                    if spinner:
                        spinner.stop(cute_msg)
                    elif self.quiet_mode:
                        self._vprint(f"  {cute_msg}")
            elif self._memory_manager and self._memory_manager.has_tool(function_name):
                # Memory provider tools (hindsight_retain, honcho_search, etc.)
                # These are not in the tool registry — route through MemoryManager.
                spinner = None
                if self._should_emit_quiet_tool_messages() and self._should_start_quiet_spinner():
                    face = random.choice(KawaiiSpinner.KAWAII_WAITING)
                    emoji = _get_tool_emoji(function_name)
                    preview = _build_tool_preview(function_name, function_args) or function_name
                    spinner = KawaiiSpinner(f"{face} {emoji} {preview}", spinner_type='dots', print_fn=self._print_fn)
                    spinner.start()
                _mem_result = None
                try:
                    function_result = self._memory_manager.handle_tool_call(function_name, function_args)
                    _mem_result = function_result
                except Exception as tool_error:
                    function_result = json.dumps({"error": f"Memory tool '{function_name}' failed: {tool_error}"})
                    logger.error("memory_manager.handle_tool_call raised for %s: %s", function_name, tool_error, exc_info=True)
                finally:
                    tool_duration = time.time() - tool_start_time
                    cute_msg = _get_cute_tool_message_impl(function_name, function_args, tool_duration, result=_mem_result)
                    if spinner:
                        spinner.stop(cute_msg)
                    elif self._should_emit_quiet_tool_messages():
                        self._vprint(f"  {cute_msg}")
            elif self.quiet_mode:
                spinner = None
                if self._should_emit_quiet_tool_messages() and self._should_start_quiet_spinner():
                    face = random.choice(KawaiiSpinner.KAWAII_WAITING)
                    emoji = _get_tool_emoji(function_name)
                    preview = _build_tool_preview(function_name, function_args) or function_name
                    spinner = KawaiiSpinner(f"{face} {emoji} {preview}", spinner_type='dots', print_fn=self._print_fn)
                    spinner.start()
                _spinner_result = None
                try:
                    function_result = handle_function_call(
                        function_name, function_args, effective_task_id,
                        tool_call_id=tool_call.id,
                        session_id=self.session_id or "",
                        enabled_tools=list(self.valid_tool_names) if self.valid_tool_names else None,
                        skip_pre_tool_call_hook=True,
                    )
                    _spinner_result = function_result
                except Exception as tool_error:
                    function_result = f"Error executing tool '{function_name}': {tool_error}"
                    logger.error("handle_function_call raised for %s: %s", function_name, tool_error, exc_info=True)
                finally:
                    tool_duration = time.time() - tool_start_time
                    cute_msg = _get_cute_tool_message_impl(function_name, function_args, tool_duration, result=_spinner_result)
                    if spinner:
                        spinner.stop(cute_msg)
                    elif self._should_emit_quiet_tool_messages():
                        self._vprint(f"  {cute_msg}")
            else:
                try:
                    function_result = handle_function_call(
                        function_name, function_args, effective_task_id,
                        tool_call_id=tool_call.id,
                        session_id=self.session_id or "",
                        enabled_tools=list(self.valid_tool_names) if self.valid_tool_names else None,
                        skip_pre_tool_call_hook=True,
                    )
                except Exception as tool_error:
                    function_result = f"Error executing tool '{function_name}': {tool_error}"
                    logger.error("handle_function_call raised for %s: %s", function_name, tool_error, exc_info=True)
                tool_duration = time.time() - tool_start_time

            self._on_tool_dispatched(function_name)

            result_preview = function_result if self.verbose_logging else (
                function_result[:200] if len(function_result) > 200 else function_result
            )

            # Log tool errors to the persistent error log so [error] tags
            # in the UI always have a corresponding detailed entry on disk.
            _is_error_result, _ = _detect_tool_failure(function_name, function_result)
            try:
                self._efficiency_recorder.record_tool_call(
                    ToolRuntimeAccounting(
                        session_id=self.session_id,
                        iteration=api_call_count,
                        tool_name=function_name,
                        queue_wait_ms=0.0,
                        execution_ms=round(tool_duration * 1000, 3),
                        result_bytes=len(str(function_result).encode("utf-8", errors="replace")),
                        failed=_is_error_result,
                    )
                )
            except Exception:
                logger.debug("Efficiency tool accounting failed", exc_info=True)
            if _is_error_result:
                logger.warning("Tool %s returned error (%.2fs): %s", function_name, tool_duration, result_preview)
            else:
                logger.info("tool %s completed (%.2fs, %d chars)", function_name, tool_duration, len(function_result))

            if self.tool_progress_callback:
                try:
                    self.tool_progress_callback(
                        "tool.completed", function_name, None, None,
                        duration=tool_duration, is_error=_is_error_result,
                        result_lines=sum(
                            1 for ln in str(function_result or "").splitlines() if ln.strip()
                        ),
                    )
                except Exception as cb_err:
                    logging.debug(f"Tool progress callback error: {cb_err}")

            self._current_tool = None
            self._touch_activity(f"tool completed: {function_name} ({tool_duration:.1f}s)")

            if self.verbose_logging:
                logging.debug(f"Tool {function_name} completed in {tool_duration:.2f}s")
                logging.debug(f"Tool result ({len(function_result)} chars): {function_result}")

            if self.tool_complete_callback:
                try:
                    self.tool_complete_callback(tool_call.id, function_name, function_args, function_result)
                except Exception as cb_err:
                    logging.debug(f"Tool complete callback error: {cb_err}")

            function_result = maybe_persist_tool_result(
                content=function_result,
                tool_name=function_name,
                tool_use_id=tool_call.id,
                env=get_active_env(effective_task_id),
                config=self._tool_budget_config(function_name),
                task_id=effective_task_id,
            )

            # Discover subdirectory context files from tool arguments
            subdir_hints = self._subdirectory_hints.check_tool_call(function_name, function_args)
            if subdir_hints:
                function_result += subdir_hints

            tool_msg = {
                "role": "tool",
                "content": function_result,
                "tool_call_id": tool_call.id
            }
            messages.append(tool_msg)

            if not self.quiet_mode:
                if self.verbose_logging:
                    print(f"  ✅ Tool {i} completed in {tool_duration:.2f}s")
                    print(f"     Result: {function_result}")
                else:
                    response_preview = function_result[:self.log_prefix_chars] + "..." if len(function_result) > self.log_prefix_chars else function_result
                    print(f"  ✅ Tool {i} completed in {tool_duration:.2f}s - {response_preview}")

            if self._interrupt_requested and i < len(assistant_message.tool_calls):
                remaining = len(assistant_message.tool_calls) - i
                self._vprint(f"{self.log_prefix}⚡ Interrupt: skipping {remaining} remaining tool call(s)", force=True)
                for skipped_tc in assistant_message.tool_calls[i:]:
                    skipped_name = skipped_tc.function.name
                    skip_msg = {
                        "role": "tool",
                        "content": f"[Tool execution skipped — {skipped_name} was not started. User sent a new message]",
                        "tool_call_id": skipped_tc.id
                    }
                    messages.append(skip_msg)
                break

            if (
                isinstance(self.tool_delay, (int, float))
                and self.tool_delay > 0
                and i < len(assistant_message.tool_calls)
            ):
                time.sleep(self.tool_delay)

        # ── Per-turn aggregate budget enforcement ─────────────────────────
        num_tools_seq = len(assistant_message.tool_calls)
        if num_tools_seq > 0:
            enforce_turn_budget(
                messages[-num_tools_seq:],
                env=get_active_env(effective_task_id),
                config=self._tool_budget_config(),
                tool_names=[tool_call.function.name for tool_call in assistant_message.tool_calls],
                task_id=effective_task_id,
            )
