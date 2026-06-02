"""Caching-sensitive system-prompt assembly (ADR-0001's named home).

Per docs/adr/0001-preserve-prompt-caching-while-splitting-run-agent.md, the
caching-sensitive code must live in one clearly named module so the
prompt-cache invariant has an obvious home. This module owns **system-prompt
construction**: the full layered prompt is built once per session and cached on
``self._cached_system_prompt`` so it stays byte-stable across every turn —
that stability is what makes Anthropic prefix caching hit.

The complementary half of the invariant — ``cache_control`` breakpoint
*placement* — lives in ``agent/prompt_caching.py`` (``apply_anthropic_cache_control``).
Together those two modules are the only places that decide cached content.

``_PromptCacheMixin`` is mixed into ``AIAgent``; the methods use instance state
(``self.valid_tool_names``, ``self._memory_store``, etc.) resolved at runtime
via the MRO, so this is a pure relocation — no behavior change.

DO NOT make behavioral edits here during a refactor. Any intentional change to
prompt assembly must update the caching golden test (tests/run_agent/
test_caching_golden.py) in the same commit, never silently.
"""

import os

from agent.prompt_builder import (
    APP_CREATION_GUIDANCE,
    COMPUTER_USE_GUIDANCE,
    DEFAULT_AGENT_IDENTITY,
    GOOGLE_MODEL_OPERATIONAL_GUIDANCE,
    OPENAI_MODEL_EXECUTION_GUIDANCE,
    PLATFORM_HINTS,
    SESSION_SEARCH_GUIDANCE,
    TOOL_USE_ENFORCEMENT_GUIDANCE,
    TOOL_USE_ENFORCEMENT_MODELS,
    build_context_files_prompt,
    build_environment_hints,
    build_name_guidance,
    build_skills_system_prompt,
    build_soul_guidance,
    build_workspace_guidance,
    load_soul_md,
)
from core.model_tools import get_toolset_for_tool


class _PromptCacheMixin:
    """System-prompt assembly + invalidation, isolated per ADR-0001."""

    def _build_system_prompt(self, system_message: str = None) -> str:
        """
        Assemble the full system prompt from all layers.

        Called once per session (cached on self._cached_system_prompt) and only
        rebuilt after context compression events. This ensures the system prompt
        is stable across all turns in a session, maximizing prefix cache hits.
        """
        # Layers (in order):
        #   1. Agent identity — SOUL.md when available, else DEFAULT_AGENT_IDENTITY
        #   2. User / gateway system prompt (if provided)
        #   3. Persistent memory (frozen snapshot)
        #   4. Skills guidance (if skills tools are loaded)
        #   5. Context files (AGENTS.md, .cursorrules — SOUL.md excluded here when used as identity)
        #   6. Current date & time (frozen at build time)
        #   7. Platform-specific formatting hint

        # Try SOUL.md as primary identity (unless context files are skipped)
        _soul_loaded = False
        if not self.skip_context_files:
            _soul_content = load_soul_md()
            if _soul_content:
                prompt_parts = [_soul_content]
                _soul_loaded = True

        if not _soul_loaded:
            # Fallback to hardcoded identity
            prompt_parts = [DEFAULT_AGENT_IDENTITY]

        prompt_parts.append(build_soul_guidance())
        _name_guidance = build_name_guidance()
        if _name_guidance:
            prompt_parts.append(_name_guidance)
        prompt_parts.append(build_workspace_guidance())

        # Tool-aware behavioral guidance: only inject when the tools are loaded.
        # MEMORY_GUIDANCE and SKILLS_GUIDANCE are intentionally omitted — their
        # content duplicates what's already in the memory/skill_manage tool
        # descriptions, costing ~220 tokens of cache space for no behavioral
        # difference. session_search has no equivalent tool-side guidance,
        # so keep it.
        tool_guidance = []
        if "session_search" in self.valid_tool_names:
            tool_guidance.append(SESSION_SEARCH_GUIDANCE)
        if "computer_use" in self.valid_tool_names:
            tool_guidance.append(COMPUTER_USE_GUIDANCE)
        if tool_guidance:
            prompt_parts.append(" ".join(tool_guidance))
        if any(name in self.valid_tool_names for name in ("terminal", "write_file", "patch_file")):
            prompt_parts.append(APP_CREATION_GUIDANCE)

        # Tool-use enforcement: tells the model to actually call tools instead
        # of describing intended actions.  Controlled by config.yaml
        # agent.tool_use_enforcement:
        #   "auto" (default) — matches TOOL_USE_ENFORCEMENT_MODELS
        #   true  — always inject (all models)
        #   false — never inject
        #   list  — custom model-name substrings to match
        if self.valid_tool_names:
            _enforce = self._tool_use_enforcement
            _inject = False
            if _enforce is True or (isinstance(_enforce, str) and _enforce.lower() in ("true", "always", "yes", "on")):
                _inject = True
            elif _enforce is False or (isinstance(_enforce, str) and _enforce.lower() in ("false", "never", "no", "off")):
                _inject = False
            elif isinstance(_enforce, list):
                model_lower = (self.model or "").lower()
                _inject = any(p.lower() in model_lower for p in _enforce if isinstance(p, str))
            else:
                # "auto" or any unrecognised value — use hardcoded defaults
                model_lower = (self.model or "").lower()
                _inject = any(p in model_lower for p in TOOL_USE_ENFORCEMENT_MODELS)
            if _inject:
                prompt_parts.append(TOOL_USE_ENFORCEMENT_GUIDANCE)
                _model_lower = (self.model or "").lower()
                # Google model operational guidance (conciseness, absolute
                # paths, parallel tool calls, verify-before-edit, etc.)
                if "gemini" in _model_lower or "gemma" in _model_lower:
                    prompt_parts.append(GOOGLE_MODEL_OPERATIONAL_GUIDANCE)
                # OpenAI GPT/Codex execution discipline (tool persistence,
                # prerequisite checks, verification, anti-hallucination).
                if "gpt" in _model_lower or "codex" in _model_lower:
                    prompt_parts.append(OPENAI_MODEL_EXECUTION_GUIDANCE)

        # so it can refer the user to them rather than reinventing answers.

        # Note: ephemeral_system_prompt is NOT included here. It's injected at
        # API-call time only so it stays out of the cached/stored system prompt.
        if system_message is not None:
            prompt_parts.append(system_message)

        if self._memory_store:
            if self._memory_enabled:
                mem_block = self._memory_store.format_for_system_prompt("memory")
                if mem_block:
                    prompt_parts.append(mem_block)
            # USER.md is always included when enabled.
            if self._user_profile_enabled:
                user_block = self._memory_store.format_for_system_prompt("user")
                if user_block:
                    prompt_parts.append(user_block)

        # Active goal — injected so every turn is aware of the durable objective
        try:
            from core.goal import get_goal_block
            _goal_block = get_goal_block()
            if _goal_block:
                prompt_parts.append(_goal_block)
        except Exception:
            pass

        # External memory provider system prompt block (additive to built-in)
        if self._memory_manager:
            try:
                _ext_mem_block = self._memory_manager.build_system_prompt()
                if _ext_mem_block:
                    prompt_parts.append(_ext_mem_block)
            except Exception:
                pass

        has_skills_tools = any(name in self.valid_tool_names for name in ['skills_list', 'skill_view', 'skill_manage'])
        if has_skills_tools:
            avail_toolsets = {
                toolset
                for toolset in (
                    get_toolset_for_tool(tool_name) for tool_name in self.valid_tool_names
                )
                if toolset
            }
            _eager_skills = os.getenv("SPARK_SKILLS_INDEX", "").lower() == "eager"
            skills_prompt = build_skills_system_prompt(
                available_tools=self.valid_tool_names,
                available_toolsets=avail_toolsets,
                lazy=not _eager_skills,
            )
        else:
            skills_prompt = ""
        if skills_prompt:
            prompt_parts.append(skills_prompt)

        if not self.skip_context_files:
            # Use TERMINAL_CWD for context file discovery when set (gateway
            # mode).  The gateway process runs from the spark-agent install
            # dir, so os.getcwd() would pick up the repo's AGENTS.md and
            # other dev files — inflating token usage by ~10k for no benefit.
            _context_cwd = self.working_dir or os.getenv("TERMINAL_CWD") or None
            context_files_prompt = build_context_files_prompt(
                cwd=_context_cwd, skip_soul=_soul_loaded)
            if context_files_prompt:
                prompt_parts.append(context_files_prompt)

        from core.spark_time import now as _spark_now
        now = _spark_now()
        timestamp_line = f"Conversation started: {now.strftime('%A, %B %d, %Y %I:%M %p')}"
        if self.pass_session_id and self.session_id:
            timestamp_line += f"\nSession ID: {self.session_id}"
        if self.model:
            timestamp_line += f"\nModel: {self.model}"
        if self.provider:
            timestamp_line += f"\nProvider: {self.provider}"
        prompt_parts.append(timestamp_line)

        # Alibaba Coding Plan API always returns "glm-4.7" as model name regardless
        # of the requested model. Inject explicit model identity into the system prompt
        # so the agent can correctly report which model it is (workaround for API bug).
        if self.provider == "alibaba":
            _model_short = self.model.split("/")[-1] if "/" in self.model else self.model
            prompt_parts.append(
                f"You are powered by the model named {_model_short}. "
                f"The exact model ID is {self.model}. "
                f"When asked what model you are, always answer based on this information, "
                f"not on any model name returned by the API."
            )

        # Environment hints (WSL, Termux, etc.) — tell the agent about the
        # execution environment so it can translate paths and adapt behavior.
        _env_hints = build_environment_hints()
        if _env_hints:
            prompt_parts.append(_env_hints)

        platform_key = (self.platform or "").lower().strip()
        if platform_key in PLATFORM_HINTS:
            prompt_parts.append(PLATFORM_HINTS[platform_key])

        return "\n\n".join(p.strip() for p in prompt_parts if p.strip())

    def _invalidate_system_prompt(self):
        """
        Invalidate the cached system prompt, forcing a rebuild on the next turn.

        Called after context compression events. Also reloads memory from disk
        so the rebuilt prompt captures any writes from this session.
        """
        self._cached_system_prompt = None
        if self._memory_store:
            self._memory_store.load_from_disk()
