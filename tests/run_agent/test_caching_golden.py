"""Caching-invariant golden test (ADR-0001).

This test captures the **byte-exact serialized request** — system blocks,
`cache_control` breakpoint positions, and tool-schema order — for a
representative conversation, and asserts equality against a stored golden.

It exists to gate the Phase 4 split of ``run_agent.py`` into a
``core/run_agent/`` package: that split is purely structural and MUST NOT
change the content or ordering of cached message blocks. A relocation that
silently moves a `cache_control` marker, reorders tools, or rebuilds the
system prompt differently would otherwise pass every other test while
quietly destroying prompt-cache hit rates in production (a cost regression,
not a correctness failure).

If a legitimate, intentional change to prompt assembly lands later, update the
golden in the SAME commit with a clear explanation — never silently.

See docs/adr/0001-preserve-prompt-caching-while-splitting-run-agent.md.
"""

import json
import sys
import types
from unittest.mock import patch

sys.modules.setdefault("fire", types.SimpleNamespace(Fire=lambda *a, **k: None))
sys.modules.setdefault("firecrawl", types.SimpleNamespace(Firecrawl=object))
sys.modules.setdefault("fal_client", types.SimpleNamespace())

from agent.prompt_caching import apply_anthropic_cache_control  # noqa: E402
from core.run_agent import AIAgent  # noqa: E402

# ── Deterministic harness ────────────────────────────────────────────────────

def _tool_defs(*names):
    return [
        {
            "type": "function",
            "function": {
                "name": n,
                "description": f"{n} tool",
                "parameters": {"type": "object", "properties": {}},
            },
        }
        for n in names
    ]


def _make_agent(provider, api_mode, base_url, model):
    """Build a fully deterministic AIAgent for serialization snapshotting.

    Tools are pinned via a mocked ``get_tool_definitions`` so the snapshot does
    not depend on the live toolset; ``skip_context_files``/``skip_memory`` keep
    the system prompt out of scope (it is supplied explicitly per conversation).
    """
    with patch("core.run_agent.get_tool_definitions", lambda **kw: _tool_defs("web_search", "terminal")), \
         patch("core.run_agent.check_toolset_requirements", lambda: {}), \
         patch("core.run_agent.OpenAI", lambda **kw: types.SimpleNamespace(close=lambda: None, api_key="k", base_url="u")):
        agent = AIAgent(
            api_key="test-key",
            base_url=base_url,
            provider=provider,
            api_mode=api_mode,
            model=model,
            max_iterations=4,
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
        )
    # Pin the one volatile field that flows into the serialized request.
    agent.session_id = "GOLDEN_SESSION"
    return agent


# A representative multi-turn conversation: system + user/assistant/user.
_CONVERSATION = [
    {"role": "system", "content": "You are Spark."},
    {"role": "user", "content": "Hello"},
    {"role": "assistant", "content": "Hi! How can I help?"},
    {"role": "user", "content": "What is 2+2?"},
]


def _canonical(kwargs: dict) -> str:
    """Serialize preserving insertion order (cache_control position + tool order
    are order-sensitive), so the comparison is byte-exact."""
    return json.dumps(kwargs, indent=2, default=str, sort_keys=False)


# ── Goldens ──────────────────────────────────────────────────────────────────
# Captured from the pre-split implementation. The Anthropic golden encodes the
# `system_and_3` strategy: a cache_control marker on the system block and on each
# of the last 3 non-system messages.

_ANTHROPIC_GOLDEN = {
    "model": "claude-sonnet-4-5",
    "messages": [
        {"role": "user", "content": [
            {"type": "text", "text": "Hello", "cache_control": {"type": "ephemeral"}}]},
        {"role": "assistant", "content": [
            {"type": "text", "text": "Hi! How can I help?", "cache_control": {"type": "ephemeral"}}]},
        {"role": "user", "content": [
            {"type": "text", "text": "What is 2+2?", "cache_control": {"type": "ephemeral"}}]},
    ],
    "max_tokens": 64000,
    "system": [
        {"type": "text", "text": "You are Spark.", "cache_control": {"type": "ephemeral"}},
    ],
    "tools": [
        {"name": "web_search", "description": "web_search tool",
         "input_schema": {"type": "object", "properties": {}}},
        {"name": "terminal", "description": "terminal tool",
         "input_schema": {"type": "object", "properties": {}}},
    ],
    "tool_choice": {"type": "auto"},
}

_CODEX_GOLDEN = {
    "model": "gpt-5.5",
    "instructions": "You are Spark.",
    "input": [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi! How can I help?"},
        {"role": "user", "content": "What is 2+2?"},
    ],
    "tools": [
        {"type": "function", "name": "web_search", "description": "web_search tool",
         "strict": False, "parameters": {"type": "object", "properties": {}}},
        {"type": "function", "name": "terminal", "description": "terminal tool",
         "strict": False, "parameters": {"type": "object", "properties": {}}},
    ],
    "tool_choice": "auto",
    "parallel_tool_calls": True,
    "store": False,
    "prompt_cache_key": "GOLDEN_SESSION",
    "reasoning": {"effort": "medium", "summary": "auto"},
    "include": ["reasoning.encrypted_content"],
}

_ANTHROPIC_EPHEMERAL_GOLDEN = {
    "model": "claude-sonnet-4-5",
    "messages": [
        {"role": "assistant", "content": [
            {"type": "text", "text": "Ready.", "cache_control": {"type": "ephemeral"}}]},
        {"role": "user", "content": [
            {"type": "text", "text": "Use the project instructions.", "cache_control": {"type": "ephemeral"}}]},
    ],
    "max_tokens": 64000,
    "system": [
        {
            "type": "text",
            "text": "You are Spark.\n\nProject-only system layer.",
            "cache_control": {"type": "ephemeral"},
        },
    ],
    "tools": [
        {"name": "web_search", "description": "web_search tool",
         "input_schema": {"type": "object", "properties": {}}},
        {"name": "terminal", "description": "terminal tool",
         "input_schema": {"type": "object", "properties": {}}},
    ],
    "tool_choice": {"type": "auto"},
}


# ── Tests ────────────────────────────────────────────────────────────────────

def test_anthropic_cache_control_serialization_is_byte_exact():
    """system_and_3 cache breakpoints + tool order must match the golden exactly."""
    agent = _make_agent(
        provider="anthropic",
        api_mode="anthropic_messages",
        base_url="https://api.anthropic.com",
        model="claude-sonnet-4-5",
    )
    cached = apply_anthropic_cache_control(
        _CONVERSATION, cache_ttl=agent._cache_ttl, native_anthropic=True
    )
    kwargs = agent._build_api_kwargs(cached)
    assert _canonical(kwargs) == _canonical(_ANTHROPIC_GOLDEN)


def test_codex_responses_serialization_is_byte_exact():
    """Codex Responses payload (instructions, input order, tools, prompt_cache_key)
    must match the golden exactly."""
    agent = _make_agent(
        provider="openai-codex",
        api_mode="codex_responses",
        base_url="https://chatgpt.com/backend-api/codex",
        model="gpt-5.5",
    )
    kwargs = agent._build_api_kwargs(_CONVERSATION)
    assert _canonical(kwargs) == _canonical(_CODEX_GOLDEN)


def test_ephemeral_system_and_prefill_layers_are_serialized_byte_exact():
    """API-only system additions and prefill messages must keep their request positions."""
    agent = _make_agent(
        provider="anthropic",
        api_mode="anthropic_messages",
        base_url="https://api.anthropic.com",
        model="claude-sonnet-4-5",
    )
    agent._cached_system_prompt = "You are Spark."
    agent.ephemeral_system_prompt = "Project-only system layer."
    agent.prefill_messages = [{"role": "assistant", "content": "Ready."}]

    effective_system = (
        agent._cached_system_prompt + "\n\n" + agent.ephemeral_system_prompt
    ).strip()
    api_messages = [{"role": "system", "content": effective_system}]
    api_messages.extend(message.copy() for message in agent.prefill_messages)
    api_messages.append({"role": "user", "content": "Use the project instructions."})
    cached = apply_anthropic_cache_control(
        api_messages, cache_ttl=agent._cache_ttl, native_anthropic=True
    )

    kwargs = agent._build_api_kwargs(cached)

    assert _canonical(kwargs) == _canonical(_ANTHROPIC_EPHEMERAL_GOLDEN)


def test_cache_breakpoint_count_never_exceeds_anthropic_max():
    """Defense-in-depth: Anthropic permits at most 4 cache_control breakpoints
    (system + 3). Assert the serialized request never emits more."""
    agent = _make_agent(
        provider="anthropic",
        api_mode="anthropic_messages",
        base_url="https://api.anthropic.com",
        model="claude-sonnet-4-5",
    )
    # A longer conversation than the rolling window of 3.
    convo = [{"role": "system", "content": "You are Spark."}]
    for i in range(8):
        convo.append({"role": "user", "content": f"q{i}"})
        convo.append({"role": "assistant", "content": f"a{i}"})
    cached = apply_anthropic_cache_control(
        convo, cache_ttl=agent._cache_ttl, native_anthropic=True
    )
    kwargs = agent._build_api_kwargs(cached)

    markers = 0
    for block in kwargs.get("system", []):
        if isinstance(block, dict) and "cache_control" in block:
            markers += 1
    for msg in kwargs.get("messages", []):
        content = msg.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and "cache_control" in part:
                    markers += 1
        elif isinstance(msg, dict) and "cache_control" in msg:
            markers += 1
    assert markers <= 4, f"expected <=4 cache breakpoints, got {markers}"
