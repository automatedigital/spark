from agent.smart_model_routing import (
    RequestClass,
    build_response_envelope,
    classify_request,
    merge_route_request_overrides,
    resolve_turn_route,
)


def test_all_request_classes_and_risk_gates_are_local():
    samples = {
        "What time is it?": RequestClass.DIRECT_ANSWER,
        "Give me a progress update": RequestClass.STATUS_PROGRESS,
        "Implement this change": RequestClass.ACTION_CHANGE,
        "Diagnose why it is failing": RequestClass.DIAGNOSIS,
        "Explain how this works": RequestClass.EXPLANATION,
        "Compare A versus B": RequestClass.COMPARISON_OPTIONS,
        "Review this plan": RequestClass.PLAN_REVIEW,
        "Delete all records": RequestClass.HIGH_STAKES,
        "Return exactly JSON": RequestClass.FORMAT_CONTRACT,
    }
    assert {classify_request(text) for text in samples} == set(samples.values())
    for text, expected in samples.items():
        assert classify_request(text) == expected


def test_explicit_detail_and_format_override_compact_defaults():
    detailed = build_response_envelope("Explain in detail with a step-by-step walkthrough")
    assert detailed.verbosity == "detailed"
    assert detailed.soft_output_max_tokens >= 4096
    formatted = build_response_envelope("Return exactly JSON matching this schema")
    assert formatted.verbosity == "preserve_user"
    assert "requested_format" in formatted.required_response_elements


def test_capability_routing_keeps_attachments_recovery_and_ambiguity_on_smart_model():
    cfg = {"enabled": True, "cheap_model": {"provider": "openrouter", "model": "fast"}}
    primary = {"provider": "openrouter", "model": "smart", "base_url": "https://example.test/v1"}
    for context in ({"has_attachments": True}, {"recovery_turn": True}, {"ambiguous": True}, {"long_context": True}):
        route = resolve_turn_route("hello", cfg, primary, context)
        assert route["model"] == "smart"
        assert route["routing_reason"].startswith("smart_required")


def test_internal_soft_cap_does_not_replace_service_tier():
    route = {
        "runtime": {"provider": "openai-codex"},
        "routing_reason": "simple_turn",
        "response_envelope": {
            "request_class": "direct_answer",
            "soft_output_max_tokens": 384,
            "reasoning_effort": "low",
        },
    }
    merged = merge_route_request_overrides(route, {"service_tier": "priority"})
    assert merged["request_overrides"] == {
        "service_tier": "priority",
        "_soft_max_output_tokens": 384,
        "_budget_reasoning_effort": "low",
        "_routing_reason": "simple_turn",
        "_request_class": "direct_answer",
    }


def test_agent_consumes_internal_budget_fields_without_sending_them():
    from core.run_agent import AIAgent

    agent = object.__new__(AIAgent)
    agent.max_tokens = 1000
    agent.reasoning_config = None
    agent.request_overrides = {
        "service_tier": "priority",
        "_soft_max_output_tokens": 384,
        "_budget_reasoning_effort": "low",
        "_routing_reason": "simple_turn",
        "_request_class": "direct_answer",
    }
    assert agent._effective_max_tokens() == 384
    assert agent.request_overrides == {"service_tier": "priority"}
    assert agent._routing_reason == "simple_turn"
    assert agent._request_class == "direct_answer"
    assert agent._effective_reasoning_config() == {"enabled": True, "effort": "low"}

    agent.reasoning_config = {"enabled": True, "effort": "high"}
    assert agent._effective_reasoning_config()["effort"] == "high"


def test_response_style_and_caps_are_independently_configurable():
    from spark_cli.config import DEFAULT_CONFIG

    assert DEFAULT_CONFIG["_config_version"] >= 28
    assert DEFAULT_CONFIG["response_budget"] == {
        "style_enabled": True,
        "soft_output_caps": True,
    }
