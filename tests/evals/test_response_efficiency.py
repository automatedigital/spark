import importlib.util
from argparse import Namespace
from pathlib import Path

MODULE_PATH = Path(__file__).parents[2] / "evals" / "response_efficiency" / "run.py"
SPEC = importlib.util.spec_from_file_location("response_efficiency_run", MODULE_PATH)
run = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(run)


def test_cases_cover_all_exceptions():
    assert run.validate_cases(run.load_cases()) == []


def test_blind_packet_does_not_expose_conditions():
    rows = [
        {"case_id": "direct", "trial": 1, "condition": "baseline", "response": "long"},
        {"case_id": "direct", "trial": 1, "condition": "candidate", "response": "short"},
    ]
    packet, key = run.blind_rows(rows)
    assert {row["label"] for row in packet} == {"A", "B"}
    assert all("condition" not in row for row in packet)
    assert set(key.values()) == {"baseline", "candidate"}


def test_weighted_quality_gate_and_token_target():
    scores = []
    for condition, concision in (("baseline", 3), ("candidate", 5)):
        scores.append(
            {
                "case_id": "direct",
                "trial": 1,
                "condition": condition,
                "correctness": 5,
                "autonomy": 5,
                "actionability": 5,
                "safety": 5,
                "concision": concision,
                "blocker": False,
            }
        )
    assert run.summarize_scores(scores)["release"] is True
    token_rows = [
        {"category": "direct", "condition": "baseline", "output_tokens": 100},
        {"category": "progress", "condition": "baseline", "output_tokens": 80},
        {"category": "direct", "condition": "candidate", "output_tokens": 30},
        {"category": "progress", "condition": "candidate", "output_tokens": 25},
    ]
    assert run.token_summary(token_rows)["target_met"] is True


def test_score_rejects_mismatched_coverage():
    base = {
        "trial": 1,
        "correctness": 5,
        "autonomy": 5,
        "actionability": 5,
        "safety": 5,
        "concision": 4,
        "blocker": False,
    }
    rows = [
        {**base, "case_id": "a", "condition": "baseline"},
        {**base, "case_id": "b", "condition": "candidate"},
    ]
    try:
        run.summarize_scores(rows)
    except ValueError as exc:
        assert "identical" in str(exc)
    else:
        raise AssertionError("mismatched coverage should fail")


def test_runner_is_isolated_pinned_and_resumable(tmp_path):
    output = tmp_path / "responses.jsonl"
    args = Namespace(
        cases=run.HERE / "cases.jsonl",
        runners=run.HERE / "runners.json",
        runner="fixture",
        condition="baseline",
        trials=1,
        budget_usd=1.0,
        allow_unmetered=False,
        timeout=10,
        output=output,
    )
    assert run.run_condition(args) == 0
    first = run.read_jsonl(output)
    assert len(first) == len(run.load_cases())
    assert all(row["isolated_user_config"] for row in first)
    assert {
        (row["provider"], row["model"], row["reasoning_effort"], row["runner_version"])
        for row in first
    } == {("fixture", "deterministic-replay-v1", "medium", "1.0.0")}
    assert run.run_condition(args) == 0
    assert run.read_jsonl(output) == first
