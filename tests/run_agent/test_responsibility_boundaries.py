from types import SimpleNamespace

import pytest

from core.run_agent.persistence import apply_user_message_override
from core.run_agent.provider_payloads import normalize_responses_tool
from core.run_agent.response_normalization import normalize_visible_text
from core.run_agent.retry_policy import RetryState
from core.run_agent.turn_orchestration import reset_turn_state


def test_provider_tool_payload_normalization_is_pure():
    original = {
        "type": "function",
        "name": "  read_file ",
        "description": 42,
        "strict": 1,
        "parameters": {"type": "object"},
    }
    normalized = normalize_responses_tool(original, 0)
    assert normalized == {
        "type": "function",
        "name": "read_file",
        "description": "42",
        "strict": True,
        "parameters": {"type": "object"},
    }
    assert original["name"] == "  read_file "


def test_provider_tool_payload_reports_indexed_contract_error():
    with pytest.raises(ValueError, match=r"tools\[3\].*valid name"):
        normalize_responses_tool(
            {"type": "function", "name": "", "parameters": {}}, 3
        )


def test_persistence_override_only_changes_target_user_message():
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "api"}]
    assert apply_user_message_override(messages, 1, "stored") is True
    assert messages[1]["content"] == "stored"
    assert apply_user_message_override(messages, 0, "bad") is False


def test_response_normalization_and_retry_state():
    assert normalize_visible_text("  a\n\t b  ") == "a b"
    state = RetryState(maximum=2)
    assert state.exhausted is False
    assert state.record_failure() == 1
    assert state.record_failure() == 2
    assert state.exhausted is True


def test_turn_orchestrator_resets_only_turn_scoped_fields():
    agent = SimpleNamespace(max_iterations=7, session_value="preserved")
    reset_turn_state(agent)
    assert agent._invalid_tool_retries == 0
    assert agent._unicode_sanitization_passes == 0
    assert agent.session_value == "preserved"
