import asyncio

import pytest

from spark_cli.turn_timing import TurnTiming


def test_monotonic_delayed_stages_and_unknowns():
    now = [10.0]
    timing = TurnTiming(clock=lambda: now[0])
    assert all(value is None for value in timing.summary()["seconds"].values())
    for mark, at in [("accepted", 10), ("preparation_ready", 12), ("execution_queued", 12),
                     ("execution_started", 15), ("provider_start", 16), ("first_token", 20), ("finish", 24)]:
        now[0] = at
        timing.mark(mark)
    timing.tool_count = 2
    timing.tool_seconds = 3.5
    assert timing.summary()["seconds"] == dict(preparation=2, queue=3, provider_start=6,
        first_token=4, accepted_to_first_token=10, tools=3.5, finish=14)
    now[0] = 1
    timing.mark("finish")
    timing.mark("unbounded-status")
    assert timing.summary()["seconds"]["finish"] == 14
    assert len(timing.marks) == 7


def test_provider_accounting_uses_only_this_turn_and_rejects_estimates():
    timing = TurnTiming()
    old = dict(usage_source="provider", prompt_tokens=999)
    row = dict(usage_source="provider", prompt_tokens=12, output_tokens=3, cache_read_tokens=0,
               cache_write_tokens=1, reasoning_tokens=0)
    result = {"efficiency": {"model_iterations": [old, row]}}
    timing.account(result, 1)
    assert timing.summary()["usage"] == {key: value for key, value in row.items() if key != "usage_source"}
    timing.usage = None
    row["usage_source"] = "estimator"
    timing.account(result, 1)
    assert timing.summary()["usage"] is None


def test_actual_route_allowlist_excludes_credentials_and_transcript():
    timing = TurnTiming()
    timing.select_route(dict(model="selected", role="fast", runtime={"provider": "custom", "api_key": "secret"},
        routing_reason="configured reason", routing_decision={"role": "fast", "reason": "simple", "signals": {"has_code": True},
        "scores": {"fast": 2}, "prompt": "secret"}, api_key="secret"))
    summary = timing.summary()
    assert summary["routing_decision"] == dict(role="fast", reason="simple", signals={"has_code": True}, scores={"fast": 2})
    assert summary["routing_reason"] == "configured reason"
    assert "secret" not in str(summary)
    assert "routing_reason" not in TurnTiming().summary()


def test_callbacks_status_is_not_first_token_and_tools_are_measured(monkeypatch):
    from spark_cli import web_server as server
    now = [100.0]
    turn = server.WebActiveTurn(0, 0, "", False, "test", "starting")
    turn.timing_summary = TurnTiming(clock=lambda: now[0])
    turn.timing_summary.mark("accepted")
    monkeypatch.setattr(server, "_get_web_turn", lambda *_: ("test", turn))
    monkeypatch.setattr(server, "_publish_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "_touch_web_turn", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "_record_web_turn_timing", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "_append_web_turn_token", lambda *args: None)
    monkeypatch.setattr(server.time, "monotonic", lambda: now[0])
    callbacks = server._make_web_chat_callbacks("test", asyncio.Queue(), None)
    callbacks[4]("api_call_started", "status only")
    callbacks[0]("")
    assert turn.timing_summary.summary()["seconds"]["accepted_to_first_token"] is None
    now[0] = 101
    callbacks[0]("actual text")
    callbacks[1]("tool", "read", {})
    now[0] = 104
    callbacks[2]("tool", "read", {}, "ok")
    assert turn.timing_summary.summary()["seconds"]["accepted_to_first_token"] == 1
    assert turn.timing_summary.summary()["seconds"]["tools"] == 3
    assert turn.timing_summary.summary()["seconds"]["first_token"] is None


def test_two_chat_outcomes_survive_refresh_without_shared_timing():
    from core.spark_state import SessionDB
    from spark_cli import web_server as server
    db = SessionDB()
    try:
        for name, duration in [("timing-a", 2), ("timing-b", 7)]:
            db.ensure_session(name, source="web", model="test")
            turn = server.WebActiveTurn(0, 0, "", False, name, "starting")
            turn.timing_summary.marks = {"accepted": 10, "finish": 10 + duration}
            server._persist_web_turn_projection(name, turn, status="completed")
        assert server._latest_web_turn_projection("timing-a")["timing_summary"]["seconds"]["finish"] == 2
        assert server._latest_web_turn_projection("timing-b")["timing_summary"]["seconds"]["finish"] == 7
    finally:
        db.close()


@pytest.mark.parametrize("fail", [False, True])
def test_execution_wrapper_observes_provider_and_restores_transport(monkeypatch, fail):
    from spark_cli import web_server as server
    now = [10.0]
    turn = server.WebActiveTurn(0, 0, "", False, "wrapped", "starting")
    turn.timing_summary = TurnTiming(clock=lambda: now[0])
    turn.timing_summary.mark("accepted")
    monkeypatch.setattr(server, "_get_web_turn", lambda *_: ("wrapped", turn))
    monkeypatch.setattr(server, "_refresh_web_agent_for_computer_use", lambda *args: None)
    monkeypatch.setattr(server, "_inject_brief_if_present", lambda sid, text: text)
    monkeypatch.setattr(server, "_maybe_capture_codex_usage_limit", lambda *args: None)

    class Agent:
        session_id = "wrapped"

        def _interruptible_streaming_api_call(self, payload):
            assert payload == {"unchanged": "payload"}
            now[0] = 14
            turn.timing_summary.mark("first_token")
            if fail:
                raise ValueError("provider failure")
            return {"final_response": "answer"}

        def run_conversation(self, message):
            now[0] = 12
            return self._interruptible_streaming_api_call({"unchanged": "payload"})

    agent = Agent()
    if fail:
        with pytest.raises(ValueError, match="provider failure"):
            server._run_web_agent_turn(agent, "prompt")
    else:
        assert server._run_web_agent_turn(agent, "prompt")["final_response"] == "answer"
    assert "_interruptible_streaming_api_call" not in vars(agent)
    assert agent._root_run_id is None
    assert turn.timing_summary.summary()["seconds"]["provider_start"] == 2
    assert turn.timing_summary.summary()["seconds"]["first_token"] == 2


@pytest.mark.parametrize("result", [None, {}, {"efficiency": "unknown"}, {"efficiency": {"model_iterations": [None]}}])
def test_unavailable_accounting_cannot_fail_a_turn(result):
    timing = TurnTiming()
    timing.account(result)
    assert timing.summary()["usage"] is None
