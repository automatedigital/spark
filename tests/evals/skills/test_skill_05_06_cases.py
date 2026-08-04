"""Deterministic SKILL-05/06 content-evaluation corpus checks."""

from pathlib import Path

from evals.skills.runner import (
    FakeAdapter,
    RunConfig,
    cases_digest,
    compare_scores,
    load_cases,
    read_jsonl,
    run_pair,
    score_fixture_results,
    validate_cases,
)


CASES = Path(__file__).parents[3] / "evals" / "skills" / "cases.skill-05-06.jsonl"
SKILLS = {
    "wayfinder",
    "grill-me",
    "grill-with-docs",
    "research",
    "prototype",
    "codebase-design",
    "domain-modeling",
}


def test_skill_05_06_corpus_is_complete_and_synthetic():
    cases = load_cases(CASES)

    assert validate_cases(CASES) == []
    assert len(cases) == 21
    assert {case.oracle["skill"] for case in cases} == SKILLS
    assert all(case.privacy == "synthetic" for case in cases)
    assert all(case.fixtures["baseline"]["cost_usd"] == 0.0 for case in cases)
    assert all(case.fixtures["candidate"]["cost_usd"] == 0.0 for case in cases)


def test_each_skill_covers_trigger_autonomy_and_artifact_quality():
    cases = load_cases(CASES)

    by_skill = {
        skill: [case for case in cases if case.oracle["skill"] == skill]
        for skill in SKILLS
    }
    assert all(len(skill_cases) == 3 for skill_cases in by_skill.values())
    for skill_cases in by_skill.values():
        evaluations = [case.oracle["evaluation"] for case in skill_cases]
        assert {item["trigger_precision"] for item in evaluations}
        assert {item["autonomy_boundary"] for item in evaluations}
        assert {item["artifact_quality"] for item in evaluations}


def test_corpus_explicitly_covers_github_and_spark_architecture_contracts():
    cases = load_cases(CASES)
    github_cases = [case for case in cases if case.oracle["evaluation"]["github_rules"]]
    architecture_cases = [
        case for case in cases if case.oracle["evaluation"]["architecture_contract"]
    ]

    assert {case.oracle["skill"] for case in github_cases} == {"wayfinder"}
    assert len(github_cases) == 1
    assert len(architecture_cases) >= 5
    assert any(
        "CONTEXT.md" in case.prompt and "docs/adr" in case.prompt
        for case in architecture_cases
    )
    assert any("GitHub" in case.prompt for case in github_cases)
    assert any("prompt_index_cost" == case.category for case in cases)


def test_skill_05_06_fixture_pair_is_comparable_and_candidate_is_better(tmp_path: Path):
    cases = load_cases(CASES)
    output = tmp_path / "responses.jsonl"
    summary = run_pair(
        cases,
        FakeAdapter(),
        output=output,
        config=RunConfig(trials=2, seed="skill-05-06-v1"),
    )
    rows = read_jsonl(output)
    scores = score_fixture_results(rows, cases)
    report = compare_scores(scores)

    assert summary["written_rows"] == 84
    assert summary["spent_cost_usd"] == 0.0
    assert summary["spent_tokens"] > 0
    assert len(rows) == 84
    assert report["release"] is True
    candidate_score = report["conditions"]["candidate"]["weighted_score"]
    baseline_score = report["conditions"]["baseline"]["weighted_score"]
    assert candidate_score > baseline_score
    assert report["conditions"]["candidate"]["blocking_findings"] == 0
    assert cases_digest(cases) == rows[0]["cases_digest"]


def test_user_only_prompt_cost_cases_are_excluded_from_index_fixture():
    cases = load_cases(CASES)
    user_only = [
        case
        for case in cases
        if case.oracle["evaluation"]["prompt_cost"] == "user_only_not_indexed"
    ]

    assert {case.oracle["skill"] for case in user_only} == {
        "wayfinder",
        "grill-me",
        "grill-with-docs",
    }
    assert all(
        case.fixtures["candidate"]["metadata"].get("prompt_indexed") is False
        for case in user_only
    )
    candidate_tokens = sum(
        case.fixtures["candidate"]["usage"]["input_tokens"] for case in user_only
    )
    baseline_tokens = sum(
        case.fixtures["baseline"]["usage"]["input_tokens"] for case in user_only
    )
    assert candidate_tokens < baseline_tokens
