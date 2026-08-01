import json
from types import SimpleNamespace

from agent.efficiency_metrics import (
    EfficiencyRecorder,
    ModelIterationAccounting,
    estimate_response_tokens,
    measure_request,
)


def test_request_buckets_are_reconciled_and_content_free(tmp_path):
    messages = [
        {"role": "system", "content": "stable"},
        {"role": "user", "content": "question\nINJECTED"},
        {"role": "tool", "content": "bounded result", "tool_call_id": "t1"},
    ]
    result = measure_request(messages, [{"type": "function", "function": {"name": "read"}}], injected_context="INJECTED")
    assert result.estimated_prompt_tokens == sum((
        result.system_prompt_tokens, result.conversation_tokens,
        result.injected_context_tokens, result.tool_result_tokens, result.schema_tokens,
    ))
    output = tmp_path / "metrics.jsonl"
    recorder = EfficiencyRecorder("s1", output)
    recorder.record_model_iteration(ModelIterationAccounting(
        version="1.0", session_id="s1", iteration=1, provider="fixture", model="fixed",
        api_mode="chat", request_latency_ms=1, system_prompt_tokens=1,
        conversation_tokens=2, injected_context_tokens=1, tool_result_tokens=1,
        schema_tokens=1, prompt_tokens=6, cache_read_tokens=0, cache_write_tokens=0,
        output_tokens=2, reasoning_tokens=0, usage_source="provider", estimator_delta_tokens=0,
    ))
    payload = output.read_text()
    assert "question" not in payload and "bounded result" not in payload
    assert json.loads(payload)["usage_source"] == "provider"


def test_estimator_only_output_counts_visible_text():
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="a concise visible answer"))]
    )
    assert estimate_response_tokens(response) > 0


def test_agent_result_exposes_provider_reconciled_iteration(monkeypatch):
    from tests.run_agent.test_context_token_tracking import _anthropic_resp, _make_agent

    agent = _make_agent(
        monkeypatch,
        "anthropic_messages",
        "anthropic",
        lambda: _anthropic_resp(500, 20, cache_read=30, cache_creation=10),
    )
    result = agent.run_conversation("synthetic question")
    rows = result["efficiency"]["model_iterations"]
    assert len(rows) == 1
    assert rows[0]["usage_source"] == "provider"
    assert rows[0]["prompt_tokens"] == 540
    assert rows[0]["output_tokens"] == 20
    assert isinstance(rows[0]["estimator_delta_tokens"], int)


def test_db_runtime_report_is_machine_readable_and_content_free(monkeypatch, tmp_path):
    from core.runtime_metrics import reset, snapshot
    from core.spark_state import SessionDB

    monkeypatch.setenv("SPARK_EFFICIENCY_METRICS", "1")
    reset()
    db = SessionDB(tmp_path / "state.db")
    try:
        db.create_session("synthetic-session", "fixture")
        db.append_message("synthetic-session", "user", content="private synthetic marker")
    finally:
        db.close()
    report = snapshot()
    assert report["counters"]["db_write_transactions"] == 2
    assert report["counters"]["db_bytes_growth"] > 0
    assert "private synthetic marker" not in json.dumps(report)
