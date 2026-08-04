from pathlib import Path

import pytest

from evals.skills.runner import (
    DEFAULT_CASES,
    GATE_THRESHOLDS,
    RunConfig,
    cases_digest,
    load_cases,
    validate_cases,
)
from evals.skills.schema import CASE_CATEGORIES, CONDITIONS, DIMENSIONS, WEIGHTS, RuntimePin


def test_public_fixture_corpus_is_complete_and_synthetic():
    cases = load_cases(DEFAULT_CASES)

    assert validate_cases(DEFAULT_CASES) == []
    assert {case.category for case in cases} == CASE_CATEGORIES
    assert all(case.privacy == "synthetic" for case in cases)
    assert all(set(case.fixtures) == set(CONDITIONS) for case in cases)


def test_runtime_pin_and_weighted_gate_contract_are_explicit():
    pin = RuntimePin("fixture", "skill-eval-fixture-v1", "medium")

    assert pin.as_dict() == {
        "provider": "fixture",
        "model": "skill-eval-fixture-v1",
        "reasoning_effort": "medium",
    }
    assert set(WEIGHTS) == set(DIMENSIONS)
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)
    assert GATE_THRESHOLDS["safety"] > GATE_THRESHOLDS["concision"]


def test_case_digest_is_order_sensitive_only_to_case_content():
    cases = load_cases(DEFAULT_CASES)

    assert cases_digest(cases) == cases_digest(list(cases))
    assert cases_digest(cases) != cases_digest(list(reversed(cases)))


def test_invalid_case_path_is_reported_without_network_or_runtime_imports(tmp_path: Path):
    invalid = tmp_path / "cases.jsonl"
    invalid.write_text('{"id":"bad"}\n', encoding="utf-8")

    errors = validate_cases(invalid)

    assert errors
    assert "fixtures" in errors[0] or "unknown case category" in errors[0]


def test_run_config_rejects_unbounded_or_empty_settings():
    with pytest.raises(ValueError, match="max_cost"):
        RunConfig(max_cost_usd=-1)
    with pytest.raises(ValueError, match="trials"):
        RunConfig(trials=0)
    with pytest.raises(ValueError, match="seed"):
        RunConfig(seed=" ")
