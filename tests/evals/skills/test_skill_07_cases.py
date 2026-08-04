"""Deterministic SKILL-07 bundled-rewrite evaluation corpus checks."""

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


CASES = Path(__file__).parents[3] / "evals" / "skills" / "cases.skill-07.jsonl"
GROUPS = {
    "systematic-debugging": 3,
    "test-driven-development": 3,
    "writing-plans": 3,
    "requesting-code-review": 2,
    "github-code-review": 1,
    "subagent-driven-development": 3,
}


def test_skill_07_corpus_is_complete_synthetic_and_zero_cost():
    cases = load_cases(CASES)

    assert validate_cases(CASES) == []
    assert len(cases) == 15
    assert {case.oracle["skill"] for case in cases} == set(GROUPS)
    assert all(case.privacy == "synthetic" for case in cases)
    assert all(case.fixtures[condition]["cost_usd"] == 0.0 for case in cases for condition in ("baseline", "candidate"))
    assert all(case.fixtures["candidate"]["metadata"]["network_used"] is False for case in cases)


def test_skill_07_covers_each_requested_boundary():
    cases = load_cases(CASES)
    by_skill = {skill: [case for case in cases if case.oracle["skill"] == skill] for skill in GROUPS}

    assert {skill: len(items) for skill, items in by_skill.items()} == GROUPS
    assert any("red-capable" in case.oracle["required_markers"] for case in cases)
    assert any("vertical slice" in case.oracle["required_markers"] for case in cases)
    assert any(case.oracle["evaluation"]["related_boundary"] == "plan_alias" for case in cases)
    assert any(case.oracle["evaluation"]["related_boundary"] == "github_review_is_external_pr" for case in cases)
    assert any(case.oracle["evaluation"]["related_boundary"] == "codex_claude_opencode_adapters" for case in cases)
    assert {case.category for case in cases} >= {"discovery", "direct_invocation", "isolation", "provenance", "prompt_index_cost", "safety", "persistent_stop"}


def test_skill_07_two_trial_pair_beats_baseline_without_blockers(tmp_path: Path):
    cases = load_cases(CASES)
    output = tmp_path / "responses.jsonl"
    summary = run_pair(
        cases,
        FakeAdapter(),
        output=output,
        config=RunConfig(trials=2, seed="skill-07-v1"),
    )
    rows = read_jsonl(output)
    scores = score_fixture_results(rows, cases)
    report = compare_scores(scores)

    assert summary["written_rows"] == 60
    assert summary["spent_cost_usd"] == 0.0
    assert summary["spent_tokens"] > 0
    assert len(rows) == 60
    assert report["release"] is True
    assert report["conditions"]["candidate"]["weighted_score"] > report["conditions"]["baseline"]["weighted_score"]
    assert report["conditions"]["candidate"]["blocking_findings"] == 0
    assert cases_digest(cases) == rows[0]["cases_digest"]
