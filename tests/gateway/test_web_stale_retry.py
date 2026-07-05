"""Web provider-stall retry behavior + error surfacing through the gateway.

Regression tests for:
- "API call failed after 1 retries" — a web-platform stale-provider kill used
  to fast-fail immediately (max_retries = retry_count on the FIRST stall).
  The turn must now get exactly one quick retry before hard-failing.
- Frozen web UI — a failed turn's error message must be flagged with
  failed=True through the gateway result so delivery is never suppressed as
  "already streamed", and follow-up messages aren't swallowed.
"""

import asyncio
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

sys.modules.setdefault("fire", types.SimpleNamespace(Fire=lambda *a, **k: None))
sys.modules.setdefault("firecrawl", types.SimpleNamespace(Firecrawl=object))
sys.modules.setdefault("fal_client", types.SimpleNamespace())

import core.run_agent as run_agent  # noqa: E402
import gateway.run as gateway_run  # noqa: E402
from gateway.config import Platform  # noqa: E402
from gateway.session import SessionSource  # noqa: E402


def _patch_agent_bootstrap(monkeypatch):
    monkeypatch.setattr(
        run_agent,
        "get_tool_definitions",
        lambda **kwargs: [
            {
                "type": "function",
                "function": {
                    "name": "terminal",
                    "description": "Run shell commands.",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    )
    monkeypatch.setattr(run_agent, "check_toolset_requirements", lambda: {})
    # Pricing lookup performs a real network fetch for unknown models — stub it.
    monkeypatch.setattr(
        run_agent,
        "estimate_usage_cost",
        lambda *a, **k: SimpleNamespace(amount_usd=None, status="unknown", source="test"),
    )


def _anthropic_response(text: str):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        model="claude-sonnet-4-6-20250514",
    )


class _FakeMessages:
    def create(self, **kwargs):
        raise NotImplementedError

    def stream(self, **kwargs):
        raise NotImplementedError


class _FakeAnthropicClient:
    def __init__(self):
        self.messages = _FakeMessages()

    def close(self):
        pass


def _fake_build_anthropic_client(key, base_url=None):
    return _FakeAnthropicClient()


def _stale_timeout_error():
    return TimeoutError(
        "API call timed out after 61s with no provider progress (threshold: 60s)"
    )


def _make_web_stall_agent_cls(recover_after=None, call_counter=None):
    """AIAgent subclass on platform=web whose API calls raise the stale-kill
    TimeoutError, optionally recovering after N failures."""

    class _Agent(run_agent.AIAgent):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("skip_context_files", True)
            kwargs.setdefault("skip_memory", True)
            kwargs.setdefault("max_iterations", 4)
            super().__init__(*args, **kwargs)
            self.platform = "web"
            self._cleanup_task_resources = lambda task_id: None
            self._persist_session = lambda messages, history=None: None
            self._save_trajectory = lambda messages, user_message, completed: None
            self._save_session_log = lambda messages: None

        def run_conversation(self, user_message, conversation_history=None, task_id=None):
            calls = call_counter if call_counter is not None else {"n": 0}

            def _fake_api_call(api_kwargs, **kw):
                calls["n"] += 1
                if recover_after is not None and calls["n"] > recover_after:
                    return _anthropic_response("Recovered")
                raise _stale_timeout_error()

            self._interruptible_api_call = _fake_api_call
            self._interruptible_streaming_api_call = _fake_api_call
            return super().run_conversation(
                user_message, conversation_history=conversation_history, task_id=task_id
            )

    return _Agent


def _run_with_agent(monkeypatch, agent_cls):
    _patch_agent_bootstrap(monkeypatch)
    monkeypatch.setattr(
        "agent.anthropic_adapter.build_anthropic_client", _fake_build_anthropic_client
    )
    monkeypatch.setattr(run_agent, "AIAgent", agent_cls)
    monkeypatch.setattr(
        gateway_run,
        "_resolve_runtime_agent_kwargs",
        lambda: {
            "provider": "anthropic",
            "api_mode": "anthropic_messages",
            "base_url": "https://api.anthropic.com",
            "api_key": "sk-ant-api03-test-key",
        },
    )
    monkeypatch.setattr(
        gateway_run,
        "_load_gateway_config",
        lambda: {"model": {"default": "claude-sonnet-4-6-20250514"}},
    )
    monkeypatch.setenv("SPARK_TOOL_PROGRESS", "false")

    runner = gateway_run.GatewayRunner.__new__(gateway_run.GatewayRunner)
    runner.adapters = {}
    runner._ephemeral_system_prompt = ""
    runner._prefill_messages = []
    runner._reasoning_config = None
    runner._provider_routing = {}
    runner._fallback_model = None
    runner._running_agents = {}
    runner.hooks = MagicMock()
    runner.hooks.emit = AsyncMock()
    runner.hooks.loaded_hooks = []
    runner._session_db = None

    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="test-user-1",
    )

    return runner, asyncio.run(
        runner._run_agent(
            message="hello",
            context_prompt="",
            history=[],
            source=source,
            session_id="test-session",
            session_key="agent:main:local:dm",
        )
    )


def test_web_stall_gets_one_retry_then_recovers(monkeypatch):
    """First stale kill must be retried once (not fast-failed after 1 attempt)."""
    calls = {"n": 0}
    agent_cls = _make_web_stall_agent_cls(recover_after=1, call_counter=calls)
    _, result = _run_with_agent(monkeypatch, agent_cls)
    assert result["final_response"] == "Recovered"
    assert calls["n"] == 2  # one stall + one successful retry


def test_web_stall_hard_fails_after_second_stall(monkeypatch):
    """A second consecutive stall ends the turn instead of looping for minutes."""
    calls = {"n": 0}
    agent_cls = _make_web_stall_agent_cls(recover_after=None, call_counter=calls)
    _, result = _run_with_agent(monkeypatch, agent_cls)
    resp = str(result.get("final_response", ""))
    assert "provider progress" in resp or "retries" in resp.lower()
    assert calls["n"] == 2  # exactly one retry, then hard fail
    # The failure must be visible to the delivery path so the web UI shows it.
    assert result.get("failed") is True


def test_failed_turn_releases_running_agent_and_surfaces_error(monkeypatch):
    """After a stale-killed turn, the session must not stay busy and the error
    must be present as the final response (no frozen UI, no swallowed turns)."""
    agent_cls = _make_web_stall_agent_cls(recover_after=None)
    runner, result = _run_with_agent(monkeypatch, agent_cls)
    assert result.get("final_response")  # explicit user-visible error text
    assert result.get("failed") is True
    assert runner._running_agents == {}  # busy state released for follow-ups
