"""Tool-loop dispatch helpers for AIAgent."""

from __future__ import annotations

import json
import logging
import os

from core.run_agent.parallelism import _should_parallelize_tool_batch

logger = logging.getLogger(__name__)


class _ToolLoopMixin:
    """Tool-call guardrails and dispatch helpers shared by the loop paths."""

    @staticmethod
    def _cap_delegate_task_calls(tool_calls: list) -> list:
        """Truncate excess delegate_task calls to max_concurrent_children."""
        from tools.delegate_tool import _get_max_concurrent_children

        max_children = _get_max_concurrent_children()
        delegate_count = sum(1 for tc in tool_calls if tc.function.name == "delegate_task")
        if delegate_count <= max_children:
            return tool_calls
        kept_delegates = 0
        truncated = []
        for tc in tool_calls:
            if tc.function.name == "delegate_task":
                if kept_delegates < max_children:
                    truncated.append(tc)
                    kept_delegates += 1
            else:
                truncated.append(tc)
        logger.warning(
            "Truncated %d excess delegate_task call(s) to enforce "
            "max_concurrent_children=%d limit",
            delegate_count - max_children,
            max_children,
        )
        return truncated

    @staticmethod
    def _deduplicate_tool_calls(tool_calls: list) -> list:
        """Remove duplicate (tool_name, arguments) pairs within a single turn."""
        seen: set = set()
        unique: list = []
        for tc in tool_calls:
            key = (tc.function.name, tc.function.arguments)
            if key not in seen:
                seen.add(key)
                unique.append(tc)
            else:
                logger.warning("Removed duplicate tool call: %s", tc.function.name)
        return unique if len(unique) < len(tool_calls) else tool_calls

    def _execute_tool_calls(
        self,
        assistant_message,
        messages: list,
        effective_task_id: str,
        api_call_count: int = 0,
    ) -> None:
        """Execute tool calls from the assistant message and append results."""
        tool_calls = assistant_message.tool_calls

        self._executing_tools = True
        try:
            if not _should_parallelize_tool_batch(tool_calls):
                return self._execute_tool_calls_sequential(
                    assistant_message, messages, effective_task_id, api_call_count
                )

            return self._execute_tool_calls_concurrent(
                assistant_message, messages, effective_task_id, api_call_count
            )
        finally:
            self._executing_tools = False

    def _on_tool_dispatched(self, function_name: str) -> None:
        """Refresh browser sub-tools after browser_open activates a session."""
        if function_name != "browser_open":
            return
        try:
            from tools.browser_tool import _browser_session_active
        except Exception:
            return
        if not _browser_session_active:
            return
        if any(t.get("function", {}).get("name") == "browser_snapshot" for t in (self.tools or [])):
            return
        try:
            from core import run_agent as run_agent_module

            refreshed = run_agent_module.get_tool_definitions(
                enabled_toolsets=self.enabled_toolsets,
                disabled_toolsets=self.disabled_toolsets,
                quiet_mode=True,
            )
        except Exception:
            return
        self.tools = refreshed
        self.valid_tool_names = {t["function"]["name"] for t in refreshed}

    def _inject_working_dir(self, function_name: str, function_args: dict) -> dict:
        """Prepend self.working_dir to relative paths in tool args."""
        working_dir = self.working_dir
        if not working_dir:
            return function_args
        if function_name == "terminal":
            if not function_args.get("workdir"):
                return {**function_args, "workdir": working_dir}
        elif function_name == "search_files":
            path = function_args.get("path", ".")
            if not os.path.isabs(str(path)):
                return {
                    **function_args,
                    "path": os.path.normpath(os.path.join(working_dir, path)),
                }
        elif function_name in ("read_file", "write_file", "patch"):
            path = function_args.get("path", "")
            if path and not os.path.isabs(str(path)):
                return {
                    **function_args,
                    "path": os.path.normpath(os.path.join(working_dir, path)),
                }
        return function_args

    def _invoke_tool(
        self,
        function_name: str,
        function_args: dict,
        effective_task_id: str,
        tool_call_id: str | None = None,
    ) -> str:
        """Invoke one tool and return the result string without display logic."""
        function_args = self._inject_working_dir(function_name, function_args)
        block_message: str | None = None
        try:
            from spark_cli.plugins import get_pre_tool_call_block_message

            block_message = get_pre_tool_call_block_message(
                function_name, function_args, task_id=effective_task_id or "",
            )
        except Exception:
            pass
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
            if function_name == "session_search":
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
            if function_name == "memory":
                target = function_args.get("target", "memory")
                from tools.memory_tool import memory_tool as _memory_tool

                result = _memory_tool(
                    action=function_args.get("action"),
                    target=target,
                    content=function_args.get("content"),
                    old_text=function_args.get("old_text"),
                    store=self._memory_store,
                )
                if self._memory_manager and function_args.get("action") in ("add", "replace"):
                    try:
                        self._memory_manager.on_memory_write(
                            function_args.get("action", ""),
                            target,
                            function_args.get("content", ""),
                        )
                    except Exception:
                        pass
                return result
            if self._memory_manager and self._memory_manager.has_tool(function_name):
                return self._memory_manager.handle_tool_call(function_name, function_args)
            if function_name == "clarify":
                from tools.clarify_tool import clarify_tool as _clarify_tool

                return _clarify_tool(
                    question=function_args.get("question", ""),
                    choices=function_args.get("choices"),
                    callback=self.clarify_callback,
                )
            if function_name == "delegate_task":
                from tools.delegate_tool import delegate_task as _delegate_task

                return _delegate_task(
                    goal=function_args.get("goal"),
                    context=function_args.get("context"),
                    toolsets=function_args.get("toolsets"),
                    tasks=function_args.get("tasks"),
                    max_iterations=function_args.get("max_iterations"),
                    parent_agent=self,
                )
            from core import run_agent as run_agent_module

            return run_agent_module.handle_function_call(
                function_name,
                function_args,
                effective_task_id,
                tool_call_id=tool_call_id,
                session_id=self.session_id or "",
                enabled_tools=list(self.valid_tool_names) if self.valid_tool_names else None,
                skip_pre_tool_call_hook=True,
            )
        finally:
            self._on_tool_dispatched(function_name)
