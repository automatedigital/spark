"""Capability negotiation through real agents/SDKs; replace only external HTTP."""

from __future__ import annotations

import copy
import json

import httpx
import pytest
from openai import APIError

from tests.run_agent.test_orchestration_replay import replay as replay

pytestmark = pytest.mark.serial


@pytest.fixture(autouse=True)
def _profile_runtime_config(replay, monkeypatch):
    # CLI imports in earlier tests can retain another profile's runtime config.
    # Initialize the real runtime data from this replay's on-disk profile, as a
    # fresh CLI entrypoint would; do not substitute the config loader/transport.
    from core.cli import CLI_CONFIG
    from spark_cli.config import load_config

    monkeypatch.setitem(CLI_CONFIG, "delegation", load_config()["delegation"])


def without_stream_options(body):
    return {k: v for k, v in body.items() if k not in {"stream", "stream_options"}}


def test_capability_retry_preserves_cached_request_and_explicit_turn(replay):
    r = replay
    parent = r.parent()
    parent.run_conversation("Establish cached history")
    prefix = copy.deepcopy(parent._session_messages)
    system, tools = parent._cached_system_prompt, copy.deepcopy(parent.tools)
    r.wire.calls.clear()
    r.wire.reject_stream = True

    result = parent.run_conversation("Provider capability negotiation")

    assert result["completed"] and result["api_calls"] == 1
    assert result["final_response"] == r.script["root_result"]
    assert len(r.wire.calls) == 2
    streaming, json_request = r.wire.calls
    assert streaming["stream"] is True and not json_request.get("stream")
    assert without_stream_options(streaming) == json_request
    assert parent._session_messages[:len(prefix)] == prefix
    assert parent._cached_system_prompt == system and parent.tools == tools
    assert [m["role"] for m in r.db.get_messages(parent.session_id)] == [
        "user", "assistant", "user", "assistant",
    ]

    # Once negotiated, subsequent explicit turns never probe streaming again.
    parent.run_conversation("Next explicit turn")
    assert len(r.wire.calls) == 3 and not r.wire.calls[-1].get("stream")


def test_root_and_children_negotiate_without_duplicate_dispatch_or_file_tools(replay):
    r = replay
    r.wire.reject_stream = True
    r.wire.release_all()
    parent = r.parent()
    result = parent.run_conversation(r.script["root_prompt"])
    assert result["completed"]
    runs = r.runs(parent)
    assert len(runs) == 2 and len(r.db.list_async_child_jobs()) == 2
    for run in runs.values():
        r.terminal(run)
        events = r.db.get_subagent_events(run["id"])
        assert sum(e["event_type"] == "tool_started" for e in events) == 1
        assert sum(e["event_type"] == "tool_completed" for e in events) == 1
    assert len([m for m in r.db.get_messages(parent.session_id) if m["role"] == "tool"]) == 1
    # One rejected streaming request per agent, with its exact JSON counterpart.
    probes = [c for c in r.wire.calls if c.get("stream")]
    assert len(probes) == 3
    for probe in probes:
        assert sum(without_stream_options(probe) == c for c in r.wire.calls) == 1


@pytest.mark.parametrize("message", ["stream is not supported", "Synthetic invalid request"])
def test_json_rejection_after_capability_retry_is_bounded(replay, monkeypatch, message):
    r = replay
    parent = r.parent()

    def handle(transport, request):
        body = json.loads(request.content)
        r.wire.calls.append(body)
        error = "stream is not supported" if body.get("stream") else message
        return httpx.Response(400, json={"error": {"message": error}}, request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)
    result = parent.run_conversation("Reject both transport modes")
    assert result["failed"] and not result["completed"]
    assert message in result["error"]
    assert len(r.wire.calls) == 2
    assert r.wire.calls[0]["stream"] and not r.wire.calls[1].get("stream")
    assert without_stream_options(r.wire.calls[0]) == r.wire.calls[1]
    assert [m["role"] for m in r.db.get_messages(parent.session_id)] == ["user"]


def test_unrelated_http_400_remains_fatal_without_capability_retry(replay, monkeypatch):
    r = replay

    def handle(transport, request):
        r.wire.calls.append(json.loads(request.content))
        return httpx.Response(400, json={"error": {"message": "Synthetic invalid request"}}, request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)
    parent = r.parent()
    result = parent.run_conversation("Unrelated client failure")
    assert result["failed"] and not result["completed"]
    assert len(r.wire.calls) == 1 and r.wire.calls[0]["stream"]
    assert not getattr(parent, "_disable_streaming", False)


@pytest.mark.parametrize("kind", ["text", "reasoning", "tool"])
def test_unsupported_error_after_sdk_output_never_signals_capability_retry(replay, monkeypatch, kind):
    r = replay
    parent = r.parent()
    delivered = []
    parent.stream_delta_callback = delivered.append
    parent.reasoning_callback = delivered.append
    parent.tool_gen_callback = delivered.append
    delta = {
        "text": {"content": "Already delivered"},
        "reasoning": {"reasoning_content": "Already thinking"},
        "tool": {"tool_calls": [{"index": 0, "id": "read-1", "type": "function",
                  "function": {"name": "read_file", "arguments": "{}"}}]},
    }[kind]

    def handle(transport, request):
        r.wire.calls.append(json.loads(request.content))
        chunk = {"id": "partial", "object": "chat.completion.chunk", "created": 1,
                 "model": r.script["model"], "choices": [
                     {"index": 0, "delta": delta, "finish_reason": None}]}
        error = {"error": {"message": "stream is not supported"}}
        data = "".join("data: " + json.dumps(item) + "\n\n" for item in (chunk, error))
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=data.encode(), request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)
    kwargs = parent._build_api_kwargs([{"role": "user", "content": "Partial stream"}])
    if kind == "text":
        # Preserve the existing partial-text response instead of replaying it.
        response = parent._interruptible_streaming_api_call(kwargs)
        assert response.choices[0].message.content == "Already delivered"
        assert response.choices[0].message.tool_calls is None
    else:
        with pytest.raises(APIError, match="stream is not supported"):
            parent._interruptible_streaming_api_call(kwargs)
    assert len(delivered) == 1
    assert len(r.wire.calls) == 1
    assert not getattr(parent, "_disable_streaming", False)
    assert r.db.get_messages(parent.session_id) == []


def test_stop_before_capability_fallback_prevents_json_request(replay, monkeypatch):
    r = replay
    parent = r.parent()

    def handle(transport, request):
        r.wire.calls.append(json.loads(request.content))
        parent.interrupt("Stop during negotiation")
        return httpx.Response(400, json={"error": {"message": "stream is not supported"}}, request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)
    result = parent.run_conversation("Stop capability negotiation")
    assert result["interrupted"]
    assert len(r.wire.calls) == 1 and r.wire.calls[0]["stream"]
