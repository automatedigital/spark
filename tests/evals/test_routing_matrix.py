"""Deterministic, synthetic coverage for the adaptive routing contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agent.smart_model_routing import (
    build_response_envelope,
    resolve_turn_route,
)

FIXTURE_PATH = Path(__file__).parent / "routing" / "routing_matrix_v1.json"
REQUIRED_SCENARIOS = {
    "direct_answer",
    "ui_work",
    "debugging",
    "planning",
    "research",
    "long_child",
    "safety_destructive_high_stakes",
    "recovery",
    "explicit_pin",
    "hysteresis",
    "unavailable_fallback",
}
REQUIRED_EXPECTED_FIELDS = {"request_class", "model_tier", "reasoning_effort", "tool_needed"}


def load_matrix() -> dict[str, Any]:
    with FIXTURE_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def validate_matrix(matrix: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if matrix.get("matrix_version") != "1.0.0":
        errors.append("matrix_version must be 1.0.0")
    if matrix.get("contract") != "agent.smart_model_routing":
        errors.append("contract must identify the public routing module")
    if matrix.get("privacy") != "synthetic-only" or matrix.get("live_calls") is not False:
        errors.append("routing matrix must be synthetic-only and live-call free")

    cases = matrix.get("cases")
    if not isinstance(cases, list) or not cases:
        return errors + ["cases must be a non-empty list"]

    ids: set[str] = set()
    scenarios: set[str] = set()
    for index, case in enumerate(cases):
        prefix = f"cases[{index}]"
        if not isinstance(case, dict):
            errors.append(f"{prefix} must be an object")
            continue
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            errors.append(f"{prefix}.case_id must be a non-empty string")
        elif case_id in ids:
            errors.append(f"duplicate case_id: {case_id}")
        else:
            ids.add(case_id)
        scenario = case.get("scenario")
        if not isinstance(scenario, str) or not scenario:
            errors.append(f"{prefix}.scenario must be a non-empty string")
        else:
            scenarios.add(scenario)

        request = case.get("request")
        if not isinstance(request, dict):
            errors.append(f"{prefix}.request must be an object")
        elif scenario not in {"hysteresis"} and not isinstance(request.get("message"), str):
            errors.append(f"{prefix}.request.message must be a string")

        expected = case.get("expected")
        if not isinstance(expected, dict):
            errors.append(f"{prefix}.expected must be an object")
        elif scenario not in {"hysteresis", "unavailable_fallback"}:
            missing = REQUIRED_EXPECTED_FIELDS - expected.keys()
            errors.extend(f"{prefix}.expected missing {field}" for field in sorted(missing))

    errors.extend(f"missing required scenario: {scenario}" for scenario in sorted(REQUIRED_SCENARIOS - scenarios))
    return errors


MATRIX = load_matrix()
CASES = MATRIX["cases"]


def test_routing_matrix_schema_is_deterministic_and_complete():
    assert validate_matrix(MATRIX) == []


def test_routing_matrix_has_unique_synthetic_case_ids():
    case_ids = [case["case_id"] for case in CASES]
    assert len(case_ids) == len(set(case_ids))
    assert all(case["case_id"].isascii() for case in CASES)


@pytest.mark.parametrize("case", [case for case in CASES if "request_class" in case["expected"]], ids=lambda case: case["case_id"])
def test_response_envelope_matches_pinned_public_expectation(case: dict[str, Any]):
    request = case["request"]
    envelope = build_response_envelope(request["message"], request.get("context"))
    expected = case["expected"]

    assert envelope.request_class == expected["request_class"]
    assert envelope.model_tier == expected["model_tier"]
    assert envelope.reasoning_effort == expected["reasoning_effort"]
    assert envelope.tool_needed is expected["tool_needed"]
    if "routing_reason" in expected:
        assert envelope.routing_reason == expected["routing_reason"]
    for blocker in expected.get("required_blockers", []):
        assert blocker in envelope.routing_reason
    if "explicit_user_override" in expected:
        assert envelope.explicit_user_override is expected["explicit_user_override"]


def _fixture_runtime(**_: Any) -> dict[str, Any]:
    return {
        "provider": "fixture",
        "api_mode": "fixture",
        "base_url": "",
        "command": "",
        "args": [],
    }


def test_explicit_pin_stays_on_primary_route():
    case = next(case for case in CASES if case["scenario"] == "explicit_pin")
    request = case["request"]
    route = resolve_turn_route(request["message"], request["routing_config"], request["primary"])

    assert route["model"] == case["expected"]["route_model"]
    assert route["routing_reason"] == case["expected"]["route_routing_reason"]
    assert route["response_envelope"]["explicit_user_override"] is True


def test_hysteresis_fixture_is_stable_for_repeated_fast_routes(monkeypatch: pytest.MonkeyPatch):
    case = next(case for case in CASES if case["scenario"] == "hysteresis")
    monkeypatch.setattr("spark_cli.runtime_provider.resolve_runtime_provider", _fixture_runtime)
    request = case["request"]
    routes = [
        resolve_turn_route(message, request["routing_config"], request["primary"], request["context"])
        for message in case["sequence"]
    ]

    assert len({route["signature"] for route in routes}) == 1
    assert all(route["routing_reason"] == case["expected"]["route_routing_reason"] for route in routes)


def test_unavailable_fast_route_falls_back_to_primary(monkeypatch: pytest.MonkeyPatch):
    case = next(case for case in CASES if case["scenario"] == "unavailable_fallback")
    request = case["request"]

    def unavailable_runtime(**_: Any) -> dict[str, Any]:
        raise RuntimeError("synthetic fixture provider unavailable")

    monkeypatch.setattr("spark_cli.runtime_provider.resolve_runtime_provider", unavailable_runtime)
    route = resolve_turn_route(request["message"], request["routing_config"], request["primary"])

    assert route["model"] == case["expected"]["route_model"]
    assert route["routing_reason"] == case["expected"]["route_routing_reason"]
