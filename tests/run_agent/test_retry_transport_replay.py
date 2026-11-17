"""SP16 real SDK transport boundary; no external provider or live profile."""

import json
import threading
import time

import httpx
import pytest

from core.run_agent.retry_policy import RetryBudget, RetryBudgetExceeded, call_with_retry_budget
from tests.run_agent.test_orchestration_replay import replay as replay

pytestmark = pytest.mark.serial


def test_stop_at_stream_transport_error_does_not_dispatch_inner_retry(replay, monkeypatch):
    parent = replay.parent()

    def handle(transport, request):
        replay.wire.calls.append(json.loads(request.content))
        parent.interrupt("Stop at transport error")
        raise httpx.ReadTimeout("Replay read timeout", request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)
    result = parent.run_conversation("Stop at stream retry")
    assert result["interrupted"]
    assert len(replay.wire.calls) == 1


def test_inflight_stream_retry_deadline_closes_worker_without_another_request(replay, monkeypatch):
    parent = replay.parent()
    release = threading.Event()
    entered = threading.Event()
    finished = threading.Event()
    budget = RetryBudget(0.15)
    started = []
    close = parent._close_request_openai_client

    def close_request(client, **kwargs):
        release.set()
        try:
            return close(client, **kwargs)
        finally:
            if kwargs.get("reason") == "stream_request_complete":
                finished.set()

    def handle(transport, request):
        replay.wire.calls.append(json.loads(request.content))
        # Measure an in-flight request, excluding SDK/client startup cost.
        budget.start()
        started.append(time.monotonic())
        entered.set()
        release.wait(5)
        raise httpx.ReadTimeout("Replay read timeout", request=request)

    monkeypatch.setattr(parent, "_close_request_openai_client", close_request)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)
    kwargs = parent._build_api_kwargs([{"role": "user", "content": "In-flight retry deadline"}])
    try:
        with pytest.raises(RetryBudgetExceeded):
            call_with_retry_budget(parent, budget, parent._interruptible_streaming_api_call, kwargs)
        assert entered.is_set()
        assert time.monotonic() - started[0] < 0.5
        assert len(replay.wire.calls) == 1
        assert parent._active_retry_budget is None
    finally:
        release.set()
        assert finished.wait(5), "Stream worker must finish before replay teardown"


def test_expired_retry_during_client_setup_never_dispatches_after_return(replay, monkeypatch):
    parent = replay.parent()
    budget = RetryBudget(0.15)
    release = threading.Event()
    finished = threading.Event()
    client = parent._create_request_openai_client(reason="replay_setup")
    close = parent._close_request_openai_client

    def create_request(**kwargs):
        budget.start()
        release.wait(5)
        return client

    def close_request(client, **kwargs):
        try:
            return close(client, **kwargs)
        finally:
            if kwargs.get("reason") == "stream_request_complete":
                finished.set()

    def handle(transport, request):
        replay.wire.calls.append(json.loads(request.content))
        raise httpx.ReadTimeout("Unexpected late request", request=request)

    monkeypatch.setattr(parent, "_create_request_openai_client", create_request)
    monkeypatch.setattr(parent, "_close_request_openai_client", close_request)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)
    kwargs = parent._build_api_kwargs([{"role": "user", "content": "Retire during setup"}])
    try:
        with pytest.raises(RetryBudgetExceeded):
            call_with_retry_budget(parent, budget, parent._interruptible_streaming_api_call, kwargs)
        assert parent._active_retry_budget is None
    finally:
        release.set()
        assert finished.wait(5), "Late setup worker must finish before teardown"
    assert replay.wire.calls == []
