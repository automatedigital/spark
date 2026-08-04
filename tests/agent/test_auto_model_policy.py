from agent.smart_model_routing import (
    RequestClass,
    RequestContext,
    choose_auto_role,
    classify_routing_signals,
    resolve_auto_target,
    resolve_turn_route,
)


def _config():
    return {
        "policy": "auto",
        "enabled": True,
        "hysteresis_margin": 2,
        "context_threshold": 24_000,
        "roles": {
            "lead": {"provider": "acct", "model": "lead", "reasoning_effort": "high", "fallback": ["balanced"]},
            "balanced": {"provider": "acct", "model": "balanced", "reasoning_effort": "medium", "fallback": ["fast"]},
            "fast": {"provider": "acct", "model": "fast", "reasoning_effort": "low", "fallback": ["balanced"]},
            "subagent": {"provider": "acct", "model": "child", "reasoning_effort": "high", "fallback": ["balanced"]},
        },
    }


def _catalog():
    return [
        {"provider": "acct", "model": "lead", "reasoning_efforts": ["medium", "high"]},
        {"provider": "acct", "model": "balanced", "reasoning_efforts": ["low", "medium"]},
        {"provider": "acct", "model": "fast", "reasoning_efforts": ["low"]},
        {"provider": "acct", "model": "child", "reasoning_efforts": ["high"]},
    ]


def test_signals_cover_class_tools_context_attachments_risk_duration_and_choice():
    signals = classify_routing_signals(
        "please update the project",
        {
            "task_class": RequestClass.ACTION_CHANGE.value,
            "tool_need": True,
            "context_tokens": 30_000,
            "has_attachments": True,
            "risk": "high",
            "duration": "long",
            "explicit_model": "acct/lead",
        },
    )

    assert signals.task_class == RequestClass.ACTION_CHANGE.value
    assert signals.tool_need is True
    assert signals.context_tokens == 30_000
    assert signals.has_attachments is True
    assert signals.risk == "high"
    assert signals.duration == "long"
    assert signals.explicit_choice == "acct/lead"


def test_high_risk_cannot_downgrade_and_adjacent_turns_use_hysteresis():
    sticky = choose_auto_role("what time is it?", {"previous_role": "balanced"}, hysteresis_margin=4)
    assert sticky.role == "balanced"
    assert sticky.reason == "sticky_hysteresis"

    high_risk = choose_auto_role(
        "delete the production records",
        RequestContext(previous_role="fast"),
    )
    assert high_risk.role == "lead"
    assert high_risk.reason == "high_risk_floor"


def test_role_resolution_requires_catalog_availability_and_uses_fallbacks():
    policy = _config()
    assert resolve_auto_target(policy, "lead", [{"provider": "other", "model": "unrelated"}]) is None
    resolved = resolve_auto_target(
        {**policy, "roles": {**policy["roles"], "lead": {**policy["roles"]["lead"], "model": "missing", "fallback": ["balanced"]}}},
        "lead",
        _catalog(),
    )
    assert resolved is not None
    assert resolved["role"] == "balanced"
    assert resolved["model"] == "balanced"


def test_auto_route_pins_explicit_choice_and_resolves_independent_subagent_role(monkeypatch):
    primary = {"model": "primary", "provider": "acct", "api_key": "key"}
    pinned = resolve_turn_route(
        "what time is it?",
        _config(),
        primary,
        {"explicit_model": "user-selected"},
        available_catalog=_catalog(),
    )
    assert pinned["model"] == "user-selected"
    assert pinned["pinned"] is True
    assert pinned["routing_reason"] == "explicit_model_pinned"

    monkeypatch.setattr(
        "spark_cli.runtime_provider.resolve_runtime_provider",
        lambda **kwargs: {"provider": "acct", "api_key": "key", "base_url": "", "api_mode": "responses"},
    )
    child = resolve_turn_route(
        "run the long delegated task",
        _config(),
        primary,
        {"is_subagent": True, "duration": "long"},
        available_catalog=_catalog(),
    )
    assert child["role"] == "subagent"
    assert child["model"] == "child"
