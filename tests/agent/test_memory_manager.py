"""Tests for agent/memory_manager.py — MemoryManager.

Covers: provider registration rules, concurrent prefetch with timeout,
tool routing, sync/lifecycle hooks, and sanitize_context.
"""

import threading
import time
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from agent.memory_manager import MemoryManager, build_memory_context_block, sanitize_context
from agent.memory_provider import MemoryProvider


# ---------------------------------------------------------------------------
# Minimal stub provider
# ---------------------------------------------------------------------------

class _StubProvider(MemoryProvider):
    def __init__(
        self,
        name: str,
        prefetch_result: str = "",
        prefetch_delay: float = 0.0,
        tools: list | None = None,
        system_prompt: str = "",
    ) -> None:
        self._name = name
        self._prefetch_result = prefetch_result
        self._prefetch_delay = prefetch_delay
        self._tools = tools or []
        self._system_prompt = system_prompt
        self.sync_calls: list[tuple[str, str]] = []
        self.turn_start_calls: list[tuple[int, str]] = []

    @property
    def name(self) -> str:
        return self._name

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        if self._prefetch_delay:
            time.sleep(self._prefetch_delay)
        return self._prefetch_result

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        pass

    def sync_turn(self, user: str, assistant: str, *, session_id: str = "") -> None:
        self.sync_calls.append((user, assistant))

    def on_turn_start(self, turn: int, message: str, **kwargs) -> None:
        self.turn_start_calls.append((turn, message))

    def on_session_end(self, messages: list) -> None:
        pass

    def on_pre_compress(self, messages: list) -> str:
        return ""

    def on_memory_write(self, action: str, target: str, content: str) -> None:
        pass

    def on_delegation(self, task: str, result: str, **kwargs) -> None:
        pass

    def is_available(self) -> bool:
        return True

    def initialize(self, session_id: str, **kwargs) -> None:
        pass

    def shutdown(self) -> None:
        pass

    def system_prompt_block(self) -> str:
        return self._system_prompt

    def get_tool_schemas(self) -> list:
        return self._tools

    def handle_tool_call(self, tool_name: str, args: dict, **kwargs) -> str:
        return f'{{"result": "handled by {self._name}"}}'


# ---------------------------------------------------------------------------
# Registration rules
# ---------------------------------------------------------------------------

class TestProviderRegistration:
    def test_builtin_always_accepted(self):
        mgr = MemoryManager()
        p = _StubProvider("builtin")
        mgr.add_provider(p)
        assert mgr.get_provider("builtin") is p

    def test_one_external_accepted(self):
        mgr = MemoryManager()
        mgr.add_provider(_StubProvider("builtin"))
        external = _StubProvider("honcho")
        mgr.add_provider(external)
        assert mgr.get_provider("honcho") is external

    def test_second_external_rejected(self, caplog):
        mgr = MemoryManager()
        mgr.add_provider(_StubProvider("builtin"))
        mgr.add_provider(_StubProvider("first"))
        mgr.add_provider(_StubProvider("second"))  # must be rejected
        assert mgr.get_provider("second") is None
        assert "rejected" in caplog.text.lower() or "only one" in caplog.text.lower()

    def test_providers_list_order(self):
        mgr = MemoryManager()
        b = _StubProvider("builtin")
        e = _StubProvider("ext")
        mgr.add_provider(b)
        mgr.add_provider(e)
        assert mgr.providers == [b, e]


# ---------------------------------------------------------------------------
# Concurrent prefetch
# ---------------------------------------------------------------------------

class TestConcurrentPrefetch:
    def test_results_merged(self):
        mgr = MemoryManager()
        mgr.add_provider(_StubProvider("builtin", prefetch_result="builtin context"))
        mgr.add_provider(_StubProvider("ext", prefetch_result="ext context"))
        result = mgr.prefetch_all("query")
        assert "builtin context" in result
        assert "ext context" in result

    def test_slow_provider_doesnt_block(self):
        """A provider that sleeps 3 s must not delay the result past ~2.5 s."""
        mgr = MemoryManager()
        mgr.add_provider(_StubProvider("builtin", prefetch_result="fast"))
        mgr.add_provider(_StubProvider("ext", prefetch_result="slow", prefetch_delay=5.0))
        start = time.monotonic()
        result = mgr.prefetch_all("q")
        elapsed = time.monotonic() - start
        # The slow provider should be timed out; fast one should still be included
        assert elapsed < 3.5, f"prefetch_all took {elapsed:.2f}s — should have timed out"
        assert "fast" in result

    def test_provider_exception_does_not_abort(self):
        mgr = MemoryManager()
        good = _StubProvider("builtin", prefetch_result="good data")
        bad = _StubProvider("ext")
        bad.prefetch = lambda q, **kw: (_ for _ in ()).throw(RuntimeError("boom"))  # type: ignore
        mgr.add_provider(good)
        mgr.add_provider(bad)
        result = mgr.prefetch_all("q")
        assert "good data" in result

    def test_empty_providers_returns_empty_string(self):
        mgr = MemoryManager()
        assert mgr.prefetch_all("q") == ""


# ---------------------------------------------------------------------------
# Tool routing
# ---------------------------------------------------------------------------

class TestToolRouting:
    def _make_tool_schema(self, name: str) -> dict:
        return {"name": name, "description": f"{name} tool", "parameters": {}}

    def test_has_tool(self):
        mgr = MemoryManager()
        p = _StubProvider("builtin", tools=[self._make_tool_schema("mem_read")])
        mgr.add_provider(p)
        assert mgr.has_tool("mem_read")
        assert not mgr.has_tool("nonexistent")

    def test_handle_tool_call_routes_correctly(self):
        mgr = MemoryManager()
        p = _StubProvider("builtin", tools=[self._make_tool_schema("mem_write")])
        mgr.add_provider(p)
        result = mgr.handle_tool_call("mem_write", {})
        assert "handled by builtin" in result

    def test_handle_tool_call_unknown_returns_error(self):
        mgr = MemoryManager()
        mgr.add_provider(_StubProvider("builtin"))
        result = mgr.handle_tool_call("unknown_tool", {})
        assert "error" in result.lower() or "no memory provider" in result.lower()

    def test_tool_name_conflict_first_wins(self):
        mgr = MemoryManager()
        p1 = _StubProvider("builtin", tools=[self._make_tool_schema("shared_tool")])
        mgr.add_provider(p1)
        p2 = _StubProvider("ext", tools=[self._make_tool_schema("shared_tool")])
        mgr.add_provider(p2)
        result = mgr.handle_tool_call("shared_tool", {})
        assert "handled by builtin" in result


# ---------------------------------------------------------------------------
# Lifecycle hooks
# ---------------------------------------------------------------------------

class TestLifecycleHooks:
    def test_sync_all_calls_all_providers(self):
        mgr = MemoryManager()
        p1 = _StubProvider("builtin")
        p2 = _StubProvider("ext")
        mgr.add_provider(p1)
        mgr.add_provider(p2)
        mgr.sync_all("user msg", "assistant msg")
        assert len(p1.sync_calls) == 1
        assert len(p2.sync_calls) == 1
        assert p1.sync_calls[0] == ("user msg", "assistant msg")

    def test_on_turn_start_calls_all_providers(self):
        mgr = MemoryManager()
        p = _StubProvider("builtin")
        mgr.add_provider(p)
        mgr.on_turn_start(1, "hello")
        assert p.turn_start_calls == [(1, "hello")]

    def test_build_system_prompt_combines_blocks(self):
        mgr = MemoryManager()
        mgr.add_provider(_StubProvider("builtin", system_prompt="mem block"))
        mgr.add_provider(_StubProvider("ext", system_prompt="ext block"))
        prompt = mgr.build_system_prompt()
        assert "mem block" in prompt
        assert "ext block" in prompt


# ---------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------

class TestContextHelpers:
    def test_sanitize_context_strips_fence_tags(self):
        raw = "before <memory-context> inside </memory-context> after"
        result = sanitize_context(raw)
        assert "<memory-context>" not in result
        assert "</memory-context>" not in result

    def test_build_memory_context_block_wraps(self):
        block = build_memory_context_block("some recalled data")
        assert "<memory-context>" in block
        assert "some recalled data" in block
        assert "[System note:" in block

    def test_build_memory_context_block_empty(self):
        assert build_memory_context_block("") == ""
        assert build_memory_context_block("   ") == ""
