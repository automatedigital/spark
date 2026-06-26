"""Persistence and memory-flush helpers for AIAgent."""

from __future__ import annotations

import json
import logging
import time

logger = logging.getLogger(__name__)


class _PersistenceMixin:
    """Cross-cutting persistence helpers extracted from the AIAgent facade."""

    def flush_memories(self, messages: list = None, min_turns: int = None):
        """Give the model one turn to persist memories before context is lost."""
        if self._memory_flush_min_turns == 0 and min_turns is None:
            return
        if "memory" not in self.valid_tool_names or not self._memory_store:
            return
        effective_min = min_turns if min_turns is not None else self._memory_flush_min_turns
        if self._user_turn_count < effective_min:
            return

        if messages is None:
            messages = getattr(self, "_session_messages", None)
        if not messages or len(messages) < 3:
            return

        flush_content = (
            "[System: The session is being compressed. "
            "Save anything worth remembering — prioritize user preferences, "
            "corrections, and recurring patterns over task-specific details.]"
        )
        sentinel = f"__flush_{id(self)}_{time.monotonic()}"
        flush_msg = {"role": "user", "content": flush_content, "_flush_sentinel": sentinel}
        messages.append(flush_msg)

        try:
            needs_sanitize = self._should_sanitize_tool_calls()
            api_messages = []
            for msg in messages:
                api_msg = msg.copy()
                if msg.get("role") == "assistant":
                    reasoning = msg.get("reasoning")
                    if reasoning:
                        api_msg["reasoning_content"] = reasoning
                api_msg.pop("reasoning", None)
                api_msg.pop("finish_reason", None)
                api_msg.pop("_flush_sentinel", None)
                api_msg.pop("_thinking_prefill", None)
                if needs_sanitize:
                    self._sanitize_tool_calls_for_strict_api(api_msg)
                api_messages.append(api_msg)

            if self._cached_system_prompt:
                api_messages = [{"role": "system", "content": self._cached_system_prompt}] + api_messages

            memory_tool_def = None
            for tool_def in self.tools or []:
                if tool_def.get("function", {}).get("name") == "memory":
                    memory_tool_def = tool_def
                    break

            if not memory_tool_def:
                messages.pop()
                return

            from agent.auxiliary_client import call_llm as _call_llm

            aux_available = True
            try:
                response = _call_llm(
                    task="flush_memories",
                    messages=api_messages,
                    tools=[memory_tool_def],
                    temperature=0.3,
                    max_tokens=5120,
                )
            except RuntimeError:
                aux_available = False
                response = None

            if not aux_available and self.api_mode == "codex_responses":
                codex_kwargs = self._build_api_kwargs(api_messages)
                codex_kwargs["tools"] = self._responses_tools([memory_tool_def])
                codex_kwargs["temperature"] = 0.3
                if "max_output_tokens" in codex_kwargs:
                    codex_kwargs["max_output_tokens"] = 5120
                response = self._run_codex_stream(codex_kwargs)
            elif not aux_available and self.api_mode == "anthropic_messages":
                from agent.anthropic_adapter import build_anthropic_kwargs as _build_ant_kwargs

                ant_kwargs = _build_ant_kwargs(
                    model=self.model,
                    messages=api_messages,
                    tools=[memory_tool_def],
                    max_tokens=5120,
                    reasoning_config=None,
                    preserve_dots=self._anthropic_preserve_dots(),
                )
                response = self._anthropic_messages_create(ant_kwargs)
            elif not aux_available:
                api_kwargs = {
                    "model": self.model,
                    "messages": api_messages,
                    "tools": [memory_tool_def],
                    "temperature": 0.3,
                    **self._max_tokens_param(5120),
                }
                from agent.auxiliary_client import _get_task_timeout

                response = self._ensure_primary_openai_client(
                    reason="flush_memories"
                ).chat.completions.create(
                    **api_kwargs,
                    timeout=_get_task_timeout("flush_memories"),
                )

            tool_calls = []
            if self.api_mode == "codex_responses" and not aux_available:
                assistant_msg, _ = self._normalize_codex_response(response)
                if assistant_msg and assistant_msg.tool_calls:
                    tool_calls = assistant_msg.tool_calls
            elif self.api_mode == "anthropic_messages" and not aux_available:
                from agent.anthropic_adapter import normalize_anthropic_response as _nar_flush

                flush_msg_obj, _ = _nar_flush(
                    response,
                    strip_tool_prefix=self._is_anthropic_oauth,
                )
                if flush_msg_obj and flush_msg_obj.tool_calls:
                    tool_calls = flush_msg_obj.tool_calls
            elif hasattr(response, "choices") and response.choices:
                assistant_message = response.choices[0].message
                if assistant_message.tool_calls:
                    tool_calls = assistant_message.tool_calls

            for tool_call in tool_calls:
                if tool_call.function.name == "memory":
                    try:
                        args = json.loads(tool_call.function.arguments)
                        flush_target = args.get("target", "memory")
                        from tools.memory_tool import memory_tool as _memory_tool

                        _memory_tool(
                            action=args.get("action"),
                            target=flush_target,
                            content=args.get("content"),
                            old_text=args.get("old_text"),
                            store=self._memory_store,
                        )
                        if not self.quiet_mode:
                            print(f"  🧠 Memory flush: saved to {args.get('target', 'memory')}")
                    except Exception as exc:
                        logger.debug("Memory flush tool call failed: %s", exc)
        except Exception as exc:
            logger.debug("Memory flush API call failed: %s", exc)
        finally:
            while messages and messages[-1].get("_flush_sentinel") != sentinel:
                messages.pop()
                if not messages:
                    break
            if messages and messages[-1].get("_flush_sentinel") == sentinel:
                messages.pop()
