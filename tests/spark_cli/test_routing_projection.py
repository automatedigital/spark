"""SP24: real durable projections, deterministic routes and config round trips."""
from contextlib import closing
from copy import deepcopy
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.smart_model_routing import resolve_auto_route
from core.spark_state import SessionDB
from spark_cli.model_routes import register_model_routes
from spark_cli.routing_projection import recorded_turn_route, routing_settings, validate_role_settings


@pytest.fixture
def client():
    app = FastAPI()
    register_model_routes(app)
    return TestClient(app)


@pytest.fixture
def config():
    return {"model": {"default": "primary", "provider": "custom:lab", "selection": "auto",
                      "base_url": "http://127.0.0.1:9911/v1", "api_mode": "chat_completions",
                      "custom_metadata": {"keep": True},
                      "auto": {"enabled": True, "context_threshold": 27000, "hysteresis_margin": 3, "custom_policy_metadata": "keep",
                               "roles": {role: {"provider": "custom:lab", "model": role + "-model",
                                                "base_url": "http://127.0.0.1:9911/v1", "fallback": [],
                                                "reasoning_effort": "", "api_mode": "", "custom_role_metadata": "keep"}
                                         for role in ("lead", "balanced", "fast", "subagent")}}},
            "providers": {"lab": {"name": "Lab", "base_url": "http://127.0.0.1:9911/v1", "models": ["fast-model"]}}}


def actual_route(config, prompt, context=None, **kwargs):
    return resolve_auto_route(prompt, {"auto": config["model"]["auto"]},
                              {"model": "primary", "provider": "custom:lab", "api_key": "fixture-secret"},
                              context, **kwargs)


def sp15_summary(route):
    """Use SP15's actual writer contract in SP24's durable endpoint tests."""
    from spark_cli.turn_timing import TurnTiming

    timing = TurnTiming()
    timing.select_route(route)
    return timing.summary()


@pytest.mark.parametrize("prompt,context,role", [
    ("hello", {}, "fast"),
    ("explain this image", {"has_attachments": True}, "balanced"),
    ("delete all production data", {}, "lead"),
])
def test_actual_deterministic_decision_survives_sqlite_refresh(client, config, prompt, context, role):
    route = actual_route(config, prompt, context)
    assert route["routing_decision"]["role"] == role
    with closing(SessionDB()) as db:
        db.ensure_session("routing", source="web", model="primary")
        # This is the SP15 optional outcome contract, injected durably. It is
        # deliberately not a second production writer or an SP15 integration claim.
        db.upsert_web_turn_projection("actual-turn", "routing", {"timing_summary": sp15_summary(route)})
    for _ in range(2):
        result = client.get("/api/model/routing/turns/routing")
        assert result.status_code == 200
        turn = result.json()["turns"][0]
        assert turn["routing_decision"] == sp15_summary(route)["routing_decision"]
        assert turn["role"] == route["role"]
        assert turn["routing_reason"] == route["routing_reason"]
        assert turn["model"] == route["model"]
        assert "fixture-secret" not in result.text


def test_missing_runtime_credentials_explains_actual_primary_fallback(client, config):
    config["model"]["auto"]["roles"]["fast"]["provider"] = "openai"
    with patch("spark_cli.runtime_provider.resolve_runtime_provider", side_effect=RuntimeError("No credentials")):
        route = actual_route(config, "hello")
    assert route["model"] == "primary"
    assert route["routing_reason"] == "auto_fallback:fast:runtime_unavailable"
    result = recorded_turn_route({"turn_id": "t", "session_id": "s", "projection": {"route": route}})
    assert result["routing_reason"] == route["routing_reason"]
    assert result["model"] == "primary"
    assert result["routing_decision"] == route["routing_decision"]
    assert "fixture-secret" not in str(result)


def test_pinned_model_is_never_overridden_by_high_risk_classification(config):
    with patch("agent.smart_model_routing.choose_auto_role", side_effect=AssertionError("must bypass Auto")):
        route = actual_route(config, "delete all production data", explicit_model="my-model")
    result = recorded_turn_route({"turn_id": "t", "session_id": "s", "projection": {"route": route}})
    assert route["model"] == result["model"] == "my-model"
    assert route["pinned"] is True
    assert result["routing_reason"] == "explicit_model_pinned"
    assert result["routing_decision"] is None


def test_absent_decision_is_unknown_and_not_reclassified():
    with patch("agent.smart_model_routing.choose_auto_role", side_effect=AssertionError("no historical inference")):
        result = recorded_turn_route({"turn_id": "t", "session_id": "s", "projection": {"model": "old"}})
    assert result["status"] == "unknown"
    assert result["model"] == "old"
    assert result["routing_reason"] is None
    assert result["routing_decision"] is None


def test_settings_presence_is_not_capability_or_availability(config, monkeypatch):
    from core.spark_constants import get_spark_home

    monkeypatch.setenv("OPENROUTER_API_KEY", "ambient-other-profile-key")
    config["model"]["auto"]["roles"]["fast"]["provider"] = "openrouter"
    assert routing_settings(config)["roles"]["fast"]["credential_presence"] == "not_detected"
    (get_spark_home() / ".env").write_text("OPENROUTER_API_KEY=synthetic-key\n")
    result = routing_settings(config)
    fast = result["roles"]["fast"]
    assert fast["credential_presence"] == "present"
    assert fast["credential_required"] is True
    assert fast["availability"] == "unknown"
    assert set(fast["capabilities"].values()) == {"unknown"}
    assert "synthetic-key" not in str(result)
    assert result["roles"]["lead"]["base_url"] == "http://127.0.0.1:9911/v1"
    assert result["applies_to"] == "future_turn"


def test_config_role_edit_uses_existing_json_schema_and_preserves_custom_settings(config, monkeypatch):
    import spark_cli.web_server as server
    from spark_cli.config import load_config, save_config

    save_config(config)
    monkeypatch.setattr(server, "load_config", load_config)
    app_client = TestClient(server.app)
    response = app_client.get("/api/config")
    assert response.status_code == 200
    editable = response.json()
    assert "model_auto" in app_client.get("/api/config/schema").json()["fields"]
    editable["model_auto"]["roles"]["fast"]["model"] = "edited-custom-model"
    response = app_client.put("/api/config", json={"config": editable})
    assert response.status_code == 200, response.text
    saved = load_config()
    assert saved["model"]["auto"]["roles"]["fast"]["model"] == "edited-custom-model"
    assert saved["model"]["auto"]["context_threshold"] == 27000
    assert saved["model"]["auto"]["hysteresis_margin"] == 3
    assert saved["model"]["custom_metadata"] == {"keep": True}
    assert saved["model"]["base_url"] == config["model"]["base_url"]
    assert saved["providers"] == config["providers"]
    assert "model_auto" not in saved
    assert saved["smart_model_routing"]["auto"] == saved["model"]["auto"]
    assert app_client.get("/api/model/routing").json()["roles"]["fast"]["model"] == "edited-custom-model"


@pytest.mark.parametrize("default", ["", "primary"])
def test_empty_auto_default_retains_endpoint_policy_and_unknown_model_fields(config, default, monkeypatch):
    import spark_cli.web_server as server

    config["model"]["default"] = default
    monkeypatch.setattr(server, "load_config", lambda: deepcopy(config))
    result = server._denormalize_config_from_web(server._normalize_config_for_web(config))
    for key in ("auto", "base_url", "api_mode", "custom_metadata", "selection"):
        assert result["model"][key] == config["model"][key]


@pytest.mark.parametrize("value", [
    {"roles": {"unknown": {}}}, {"roles": {"fast": {"model": "bad\nmodel"}}},
    {"roles": {"fast": {"base_url": "file:///tmp/private"}}},
    {"roles": {"fast": {"provider": "bad\nprovider"}}},
])
def test_role_validation_rejects_invalid_routes(value):
    with pytest.raises(ValueError):
        validate_role_settings(value)


def test_model_picker_writes_pin_and_auto_without_losing_endpoint(client, config):
    from spark_cli.config import load_config, save_config

    save_config(config)
    assert client.put("/api/model/smart", json={"model": "explicit-model"}).status_code == 200
    saved = load_config()
    assert saved["model"]["selection"] == "pinned"
    assert saved["model"]["default"] == "explicit-model"
    assert saved["model"]["base_url"] == config["model"]["base_url"]
    assert client.put("/api/model/smart", json={"model": "auto"}).status_code == 200
    assert load_config()["model"]["selection"] == "auto"
    assert load_config()["model"]["auto"] == config["model"]["auto"]


def test_unknown_session_is_not_fabricated(client):
    assert client.get("/api/model/routing/turns/missing").status_code == 404


def test_route_reader_is_bounded_and_does_not_return_large_transcript_or_runtime(client):
    with closing(SessionDB()) as db:
        db.ensure_session("bounded", source="web", model="primary")
        for index in range(55):
            db.upsert_web_turn_projection(f"turn-{index:03}", "bounded", {
                "messages": "transcript-secret" * 1000,
                "route": {"model": "actual-model", "runtime": {"api_key": "runtime-secret", "provider": "custom:lab"},
                          "routing_reason": "explicit_model_pinned"}})
    response = client.get("/api/model/routing/turns/bounded")
    assert response.status_code == 200
    turns = response.json()["turns"]
    assert len(turns) == 50
    assert turns[0]["turn_id"] == "turn-005"
    assert turns[-1]["turn_id"] == "turn-054"
    assert all(turn["provider"] == "custom:lab" for turn in turns)
    assert "secret" not in response.text


def test_role_projection_does_not_expose_credentials_in_legacy_endpoint(config):
    config["model"]["auto"]["roles"]["fast"]["base_url"] = "https://user:secret@lab.invalid/v1?token=secret"
    result = routing_settings(config)
    assert result["roles"]["fast"]["base_url"] == "https://lab.invalid/v1"
    assert "secret" not in str(result)


def test_actual_web_route_honors_configured_pin_without_calling_classifier(config, monkeypatch):
    import spark_cli.runtime_provider as runtime
    import spark_cli.web_server as server

    config["model"]["selection"] = "pinned"
    config["model"]["auto"]["enabled"] = False
    monkeypatch.setattr(server, "load_config", lambda: deepcopy(config))
    monkeypatch.setattr(runtime, "resolve_runtime_provider", lambda **kwargs: {"provider": "custom:lab"})
    with patch("agent.smart_model_routing.choose_auto_role", side_effect=AssertionError("pin must bypass classification")):
        route = server._resolve_web_turn_route("delete all production data")
    assert route["model"] == "primary"
    assert route["routing_reason"] == "explicit_model_pinned"
    assert route["pinned"] is True


def test_actual_web_route_uses_the_effective_role_mapping(config, monkeypatch):
    import spark_cli.runtime_provider as runtime
    import spark_cli.web_server as server

    monkeypatch.setattr(server, "load_config", lambda: deepcopy(config))
    monkeypatch.setattr(runtime, "resolve_runtime_provider", lambda **kwargs: {"provider": "custom:lab"})
    route = server._resolve_web_turn_route("hello")
    assert route["model"] == "fast-model"
    assert route["routing_decision"]["role"] == "fast"
    assert route["runtime"]["provider"] == "custom:lab"


def test_invalid_role_endpoint_is_rejected_without_saving(config):
    import spark_cli.web_server as server
    from spark_cli.config import load_config, save_config

    save_config(config)
    client = TestClient(server.app)
    editable = client.get("/api/config").json()
    editable["model_auto"]["roles"]["fast"]["base_url"] = "file:///tmp/private"
    response = client.put("/api/config", json={"config": editable})
    assert response.status_code == 400
    assert load_config()["model"]["auto"]["roles"]["fast"]["base_url"] == config["model"]["auto"]["roles"]["fast"]["base_url"]


def test_explicit_web_model_beats_global_auto_even_when_policy_disabled(config, monkeypatch):
    import spark_cli.runtime_provider as runtime
    import spark_cli.web_server as server

    config["model"]["auto"]["enabled"] = False
    monkeypatch.setattr(server, "load_config", lambda: deepcopy(config))
    monkeypatch.setattr(runtime, "resolve_runtime_provider", lambda **kwargs: {"provider": "custom:lab"})
    with patch("agent.smart_model_routing.choose_auto_role", side_effect=AssertionError("must not classify explicit model")):
        route = server._resolve_web_turn_route("delete all production data", explicit_model="chosen")
    assert route["model"] == "chosen"
    assert route["routing_reason"] == "explicit_model_pinned"
