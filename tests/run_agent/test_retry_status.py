"""SP16 provider-boundary replays: bounded, cache-stable, cancellable retries."""

import copy
import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.run_agent import AIAgent, retry_policy
from core.run_agent.retry_policy import (
    RetryBudget,
    RetryStatus,
    retry_after_seconds,
    wait_for_retry,
)


class ProviderError(Exception):
    def __init__(self, status=None, retry_after=None):
        super().__init__(f"HTTP {status}" if status else "Connection timed out")
        self.status_code = status
        self.response = SimpleNamespace(headers={} if retry_after is None else {"Retry-After": retry_after})


@pytest.fixture
def agent(monkeypatch):
    monkeypatch.setenv("SPARK_TOOL_PROGRESS", "false")
    with (
        patch("core.run_agent.get_tool_definitions", return_value=[]),
        patch("core.run_agent.check_toolset_requirements", return_value={}),
        patch("core.run_agent.OpenAI"),
    ):
        value = AIAgent(
            api_key="replay-only", base_url="http://127.0.0.1:1/v1",
            api_mode="chat_completions", model="replay", provider="openai",
            quiet_mode=True, skip_context_files=True, skip_memory=True, max_iterations=3,
        )
    value._persist_session = lambda *a, **kw: None
    value._save_trajectory = lambda *a, **kw: None
    value._save_session_log = lambda *a, **kw: None
    value._cleanup_task_resources = lambda *a, **kw: None
    value._try_recover_primary_transport = lambda *a, **kw: False
    value._try_activate_fallback = lambda: False
    value._recover_with_credential_pool = lambda **kw: (False, kw["has_retried_429"])
    value._dump_api_request_debug = lambda *a, **kw: None
    return value


def response():
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="Recovered", tool_calls=None, role="assistant"), finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


def replay(agent, errors, *, partial=False):
    calls = []
    events = []
    agent.status_callback = lambda kind, message: events.append(message)

    def request(kwargs, **kw):
        calls.append(copy.deepcopy(kwargs))
        if len(calls) <= len(errors):
            if partial:
                agent._record_streamed_assistant_text("Already visible")
            raise errors[len(calls) - 1]
        return response()

    agent._interruptible_api_call = request
    agent._interruptible_streaming_api_call = request
    return calls, events


@pytest.mark.parametrize("status,reason", [(429, "rate_limit"), (500, "server_error"), (503, "overloaded"), (None, "timeout")])
def test_transient_replays_preserve_payload_and_publish_sparse_status(agent, monkeypatch, status, reason):
    monkeypatch.setattr("core.run_agent.turn_loop.jittered_backoff", lambda *a, **kw: 0.001)
    calls, events = replay(agent, [TimeoutError("Provider request timeout") if status is None else ProviderError(status)])
    result = agent.run_conversation("Same prefix")
    assert result["final_response"] == "Recovered"
    assert len(calls) == 2
    assert json.dumps(calls[0], default=str) == json.dumps(calls[1], default=str)
    retries = [event.data for event in events if isinstance(event, RetryStatus)]
    assert len(retries) == 1
    assert retries[0]["reason_class"] == reason
    assert retries[0]["attempt"] == 2
    assert retries[0]["budget_seconds"] == 240
    assert retries[0]["next_attempt_at"] <= retries[0]["budget_deadline_at"]


@pytest.mark.parametrize("status", [401, 403])
def test_permanent_auth_stops_without_fallback_or_extra_request(agent, status):
    agent._try_activate_fallback = lambda: pytest.fail("Auth failure must not change provider")
    calls, events = replay(agent, [ProviderError(status)])
    result = agent.run_conversation("Auth replay")
    assert result["failed"]
    assert len(calls) == 1
    assert not any(isinstance(event, RetryStatus) for event in events)


def test_partial_stream_is_not_replayed(agent):
    calls, events = replay(agent, [ProviderError(500)], partial=True)
    result = agent.run_conversation("Partial stream replay")
    assert result["partial"] and result["failed"] and result["interrupted"]
    assert result["final_response"] == "Already visible"
    assert len(calls) == 1
    assert not any(isinstance(event, RetryStatus) for event in events)


def test_retry_after_beyond_budget_stops_without_another_request(agent):
    calls, events = replay(agent, [ProviderError(429, "241")])
    result = agent.run_conversation("Budget replay")
    assert result["failed"]
    assert "budget exhausted" in result["error"]
    assert len(calls) == 1
    assert not any(isinstance(event, RetryStatus) for event in events)


def test_stop_during_backoff_prevents_dispatch_under_250ms(agent, record_property):
    calls, events = replay(agent, [ProviderError(429, "120")])
    waiting = threading.Event()
    original = agent.status_callback

    def status(kind, message):
        original(kind, message)
        if isinstance(message, RetryStatus):
            waiting.set()

    agent.status_callback = status
    result = []
    worker = threading.Thread(target=lambda: result.append(agent.run_conversation("Stop replay")))
    worker.start()
    assert waiting.wait(5)
    started = time.monotonic()
    agent.interrupt()
    worker.join(0.25)
    elapsed = time.monotonic() - started
    record_property("stop_latency_seconds", elapsed)
    assert not worker.is_alive(), f"Stop took {elapsed:.3f}s"
    assert elapsed < 0.25
    assert result[0]["interrupted"]
    assert len(calls) == 1
    assert len([e for e in events if isinstance(e, RetryStatus)]) == 1


@pytest.mark.parametrize("raw,expected", [("0", 0), ("1.5", 1.5), ("-1", 0), ("nan", None), ("inf", None), ("junk", None)])
def test_retry_after_numbers(raw, expected):
    assert retry_after_seconds(ProviderError(429, raw)) == expected


def test_retry_after_http_date(monkeypatch):
    monkeypatch.setattr(retry_policy.time, "time", lambda: 0)
    assert retry_after_seconds(ProviderError(503, "Thu, 01 Jan 1970 00:00:10 GMT")) == 10


def test_elapsed_request_time_consumes_budget_and_wall_jump_does_not(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(retry_policy.time, "monotonic", lambda: clock[0])
    budget = RetryBudget(5)
    budget.start()
    clock[0] = 14
    monkeypatch.setattr(retry_policy.time, "time", lambda: -99999)
    assert budget.remaining == 1
    emitted = []
    agent = SimpleNamespace(_interrupt_requested=False, _emit_status=emitted.append)
    assert wait_for_retry(agent, budget, reason="timeout", attempt=2, max_attempts=3, delay=2) == "exhausted"
    assert not emitted
    clock[0] = 16
    assert budget.exhausted


def test_long_wait_emits_sparse_liveness_without_resetting_deadline(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(retry_policy.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(retry_policy.time, "time", lambda: 1000 + clock[0])
    monkeypatch.setattr(retry_policy.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    events = []
    touches = []
    agent = SimpleNamespace(_interrupt_requested=False, _emit_status=events.append, _touch_activity=touches.append)
    assert wait_for_retry(agent, RetryBudget(240), reason="rate_limit", attempt=2, max_attempts=3, delay=65) == "ready"
    retries = [e for e in events if isinstance(e, RetryStatus)]
    assert len(retries) == 3  # One transition, then 30s/60s liveness; no 1Hz backend clock.
    assert len(touches) == 2
    assert all(e.data == retries[0].data for e in retries)
    assert retries[0].data["next_attempt_at"] == 1165
    assert events[-1] == "Calling model…"


def test_inflight_retry_closes_transport_at_elapsed_deadline(monkeypatch):
    from tests.run_agent.test_provider_stall_watchdog import (
        FakeRequestClient,
        OpenAIFactory,
        _build_agent,
    )

    release = threading.Event()
    request_client = FakeRequestClient(lambda **kwargs: release.wait(5))
    original_close = request_client.close

    def close():
        original_close()
        release.set()

    request_client.close = close
    monkeypatch.setattr("core.run_agent.OpenAI", OpenAIFactory([request_client]))
    agent = _build_agent()
    budget = RetryBudget(0.08)
    budget.start()  # This is a retry; the initial request has already failed.
    started = time.monotonic()
    try:
        with pytest.raises(retry_policy.RetryBudgetExceeded, match="retry budget exhausted"):
            retry_policy.call_with_retry_budget(agent, budget, agent._interruptible_api_call, {"model": "replay", "messages": []})
        assert time.monotonic() - started < 0.25
        assert request_client.close_calls >= 1
        assert agent._active_retry_budget is None
    finally:
        release.set()


def test_expired_budget_does_not_invoke_provider_and_restores_scope():
    agent = SimpleNamespace(_active_retry_budget="previous")
    budget = RetryBudget(0)
    budget.start()
    with pytest.raises(retry_policy.RetryBudgetExceeded):
        retry_policy.call_with_retry_budget(agent, budget, lambda: pytest.fail("Expired retry dispatched"))
    assert agent._active_retry_budget == "previous"
