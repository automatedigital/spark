"""Regression tests for the non-streaming stale-call watchdog.

Covers the provider-stall bugs reported as:
- "API call timed out after 390s with no provider progress (threshold: 60s)"
  → wall-clock (time.time) elapsed math jumped across machine sleep; the
    watchdog must use time.monotonic() so elapsed never wildly exceeds the
    threshold.
- Keep-alive/ping stream events resetting the progress timestamp and masking
  a genuinely stalled provider.
"""

import sys
import threading
import time
import types
from types import SimpleNamespace

import pytest

sys.modules.setdefault("fire", types.SimpleNamespace(Fire=lambda *a, **k: None))
sys.modules.setdefault("firecrawl", types.SimpleNamespace(Firecrawl=object))
sys.modules.setdefault("fal_client", types.SimpleNamespace())

import core.run_agent as run_agent  # noqa: E402
from core.run_agent import _stream_event_is_progress  # noqa: E402


class FakeRequestClient:
    def __init__(self, responder):
        self._responder = responder
        self._client = SimpleNamespace(is_closed=False)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.responses = SimpleNamespace()
        self.close_calls = 0

    def _create(self, **kwargs):
        return self._responder(**kwargs)

    def close(self):
        self.close_calls += 1
        self._client.is_closed = True


class OpenAIFactory:
    def __init__(self, clients):
        self._clients = list(clients)
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(dict(kwargs))
        if not self._clients:
            raise AssertionError("OpenAI factory exhausted")
        return self._clients.pop(0)


class FakeCodexResponseStream:
    def __init__(self, events, final_response):
        self._events = list(events)
        self._final_response = final_response

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def __iter__(self):
        for delay, event in self._events:
            if delay:
                threading.Event().wait(delay)
            yield event

    def get_final_response(self):
        return self._final_response


def _build_agent():
    agent = run_agent.AIAgent.__new__(run_agent.AIAgent)
    agent.api_mode = "chat_completions"
    agent.provider = "openai-codex"
    agent.base_url = "https://chatgpt.com/backend-api/codex"
    agent.model = "gpt-5-codex"
    agent.log_prefix = ""
    agent.quiet_mode = True
    agent._interrupt_requested = False
    agent._interrupt_message = None
    agent._client_lock = threading.RLock()
    agent._client_kwargs = {"api_key": "***", "base_url": agent.base_url}
    agent.client = FakeRequestClient(lambda **kwargs: {"shared": True})
    agent.stream_delta_callback = None
    agent._stream_callback = None
    agent.reasoning_callback = None
    agent.status_callback = None
    return agent


# ---------------------------------------------------------------------------
# _stream_event_is_progress unit behavior
# ---------------------------------------------------------------------------


def test_stream_event_is_progress_rejects_keepalives():
    assert not _stream_event_is_progress(None)
    assert not _stream_event_is_progress("")
    assert not _stream_event_is_progress("ping")
    assert not _stream_event_is_progress("keep_alive")
    assert not _stream_event_is_progress("keep-alive")
    assert not _stream_event_is_progress("heartbeat")
    assert not _stream_event_is_progress("response.ping")


def test_stream_event_is_progress_accepts_content_events():
    assert _stream_event_is_progress("response.output_text.delta")
    assert _stream_event_is_progress("response.output_item.done")
    assert _stream_event_is_progress("response.function_call_arguments.delta")
    assert _stream_event_is_progress("response.completed")


# ---------------------------------------------------------------------------
# Monotonic clock: wall-clock jumps (machine sleep) must not fire the watchdog
# ---------------------------------------------------------------------------


def test_wall_clock_jump_does_not_trigger_stale_timeout(monkeypatch):
    """Simulated machine sleep: time.time() jumps forward wildly during the
    call.  The watchdog must use time.monotonic() so the healthy 1s call still
    succeeds instead of being reported as (e.g.) 390s of silence."""
    done = threading.Event()

    def responder(**kwargs):
        done.wait(timeout=1.0)
        return {"ok": True}

    request_client = FakeRequestClient(responder)
    factory = OpenAIFactory([request_client])
    monkeypatch.setattr(run_agent, "OpenAI", factory)
    monkeypatch.setenv("SPARK_API_CALL_STALE_TIMEOUT", "5.0")

    real_time = time.time
    state = {"offset": 0.0}

    def jumping_wall_clock():
        # Every observation of the wall clock jumps another 100s forward,
        # emulating a laptop sleep/resume mid-call.
        state["offset"] += 100.0
        return real_time() + state["offset"]

    monkeypatch.setattr(run_agent.time, "time", jumping_wall_clock)
    try:
        agent = _build_agent()
        agent.platform = "web"
        result = agent._interruptible_api_call({"model": agent.model, "messages": []})
    finally:
        monkeypatch.setattr(run_agent.time, "time", real_time)

    assert result == {"ok": True}


def test_stale_timeout_reports_consistent_elapsed(monkeypatch):
    """When the watchdog fires, the reported elapsed must be close to the
    threshold (threshold + poll slop), never a 6x overshoot."""
    never = threading.Event()

    def hung_responder(**kwargs):
        never.wait(timeout=10.0)
        return {"ok": True}

    request_client = FakeRequestClient(hung_responder)
    factory = OpenAIFactory([request_client])
    monkeypatch.setattr(run_agent, "OpenAI", factory)
    monkeypatch.setenv("SPARK_API_CALL_STALE_TIMEOUT", "0.5")

    agent = _build_agent()
    agent.platform = "web"

    with pytest.raises(TimeoutError) as excinfo:
        agent._interruptible_api_call({"model": agent.model, "messages": []})

    msg = str(excinfo.value)
    assert "no provider progress" in msg
    import re

    m = re.search(r"timed out after (\d+)s", msg)
    assert m, msg
    # Threshold 0.5s, poll interval 0.3s → elapsed must stay within ~3s.
    assert int(m.group(1)) <= 3


# ---------------------------------------------------------------------------
# Keep-alive pings must not mask a stalled provider
# ---------------------------------------------------------------------------


def test_keepalive_pings_do_not_reset_stale_watchdog(monkeypatch):
    """A provider that keeps the socket warm with ping events but never
    produces content must still trip the stale watchdog."""
    events = [(0.15, SimpleNamespace(type="ping")) for _ in range(40)]
    final_response = SimpleNamespace(output=[], status="completed", model="gpt-5-codex")

    request_client = FakeRequestClient(
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("chat completions unused"))
    )
    request_client.responses = SimpleNamespace(
        stream=lambda **kwargs: FakeCodexResponseStream(events, final_response)
    )
    factory = OpenAIFactory([request_client])
    monkeypatch.setattr(run_agent, "OpenAI", factory)
    monkeypatch.setenv("SPARK_API_CALL_STALE_TIMEOUT", "0.5")

    agent = _build_agent()
    agent.api_mode = "codex_responses"
    agent.platform = "web"

    with pytest.raises(TimeoutError) as excinfo:
        agent._interruptible_api_call({"model": agent.model, "messages": []})

    assert "no provider progress" in str(excinfo.value)
