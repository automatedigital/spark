import json
from pathlib import Path

import pytest

from evals.skills.runner import (
    BudgetExceeded,
    FakeAdapter,
    RunConfig,
    SpendBudget,
    blind_rows,
    compare_scores,
    load_cases,
    read_jsonl,
    run_pair,
    score_fixture_results,
    write_blind_artifacts,
)
from evals.skills.schema import AdapterResult, RuntimePin, SchemaError


def test_fake_pair_is_pinned_isolated_and_identical(tmp_path: Path):
    output = tmp_path / "responses.jsonl"
    adapter = FakeAdapter()
    config = RunConfig(trials=2)

    summary = run_pair(load_cases(), adapter, output=output, config=config)
    rows = read_jsonl(output)

    assert summary["written_rows"] == 28
    assert len(rows) == 28
    assert {row["condition"] for row in rows} == {"baseline", "candidate"}
    assert {
        tuple(sorted(row["runtime"].items()))
        for row in rows
    } == {
        (
            ("model", "skill-eval-fixture-v1"),
            ("provider", "fixture"),
            ("reasoning_effort", "medium"),
        )
    }
    assert {row["cases_digest"] for row in rows} == {rows[0]["cases_digest"]}
    assert all(row["isolation"]["ok"] for row in rows)
    assert all(row["isolation"]["network"] == "disabled" for row in rows)
    assert all(request.environment["SPARK_EVAL_NETWORK"] == "disabled" for request in adapter.calls)


def test_resume_does_not_call_adapter_again(tmp_path: Path):
    output = tmp_path / "responses.jsonl"
    cases = load_cases()
    adapter = FakeAdapter()
    config = RunConfig(trials=1)

    run_pair(cases, adapter, output=output, config=config)
    first_rows = read_jsonl(output)
    first_call_count = len(adapter.calls)
    summary = run_pair(cases, adapter, output=output, config=config)

    assert len(adapter.calls) == first_call_count
    assert summary["written_rows"] == 0
    assert read_jsonl(output) == first_rows


def test_resume_can_extend_trial_count(tmp_path: Path):
    output = tmp_path / "responses.jsonl"
    cases = load_cases()
    adapter = FakeAdapter()

    run_pair(cases, adapter, output=output, config=RunConfig(trials=1))
    summary = run_pair(cases, adapter, output=output, config=RunConfig(trials=2))

    assert summary["written_rows"] == 14
    assert len(read_jsonl(output)) == 28


def test_dry_run_plans_without_adapter_calls_or_output(tmp_path: Path):
    output = tmp_path / "responses.jsonl"
    adapter = FakeAdapter()

    result = run_pair(load_cases(), adapter, output=output, dry_run=True)

    assert result["dry_run"] is True
    assert result["planned_rows"] == 14
    assert result["remaining_rows"] == 14
    assert adapter.calls == []
    assert not output.exists()


def test_budget_is_hard_and_persisted_rows_remain_resumable(tmp_path: Path):
    class MeteredAdapter(FakeAdapter):
        def run(self, request):
            result = super().run(request)
            return AdapterResult(
                response=result.response,
                input_tokens=1,
                output_tokens=1,
                cost_usd=0.60,
                metadata=result.metadata,
                reported_runtime=result.reported_runtime,
            )

    output = tmp_path / "responses.jsonl"
    with pytest.raises(BudgetExceeded, match="cost cap"):
        run_pair(
            load_cases(),
            MeteredAdapter(),
            output=output,
            config=RunConfig(max_cost_usd=1.0),
        )

    rows = read_jsonl(output)
    assert len(rows) == 1
    assert rows[0]["cost_usd"] == 0.6


def test_blind_packet_separates_opaque_labels_from_condition_key(tmp_path: Path):
    rows = [
        {"case_id": "case-a", "trial": 1, "pair_id": "case-a:1", "condition": "baseline", "response": "a"},
        {"case_id": "case-a", "trial": 1, "pair_id": "case-a:1", "condition": "candidate", "response": "b"},
    ]

    packet, key = blind_rows(rows, seed="test-seed")

    assert {item["label"] for item in packet} == {"A", "B"}
    assert all("condition" not in item for item in packet)
    assert set(key["entries"][item["response_id"]]["condition"] for item in packet) == {
        "baseline",
        "candidate",
    }
    packet_path = tmp_path / "judge-packet.json"
    key_path = tmp_path / "condition-key.json"
    write_blind_artifacts(rows, packet_path, key_path, seed="test-seed")
    assert json.loads(packet_path.read_text())[0].get("condition") is None
    assert set(json.loads(key_path.read_text())["entries"]) == {
        item["response_id"] for item in packet
    }


def test_blinding_rejects_unpaired_rows():
    with pytest.raises(SchemaError, match="exactly"):
        blind_rows(
            [{"case_id": "case-a", "trial": 1, "condition": "baseline", "response": "a"}]
        )


def test_fixture_scores_apply_all_weighted_quality_and_safety_gates():
    scores = score_fixture_results(read_jsonl(_run_fixture_rows()), load_cases())

    report = compare_scores(scores)

    assert report["release"] is True
    assert report["conditions"]["candidate"]["weighted_score"] > report["conditions"]["baseline"]["weighted_score"]
    assert report["conditions"]["candidate"]["blocking_findings"] == 0


def test_compare_rejects_missing_pair_coverage():
    base = {
        "case_id": "a",
        "trial": 1,
        "correctness": 5,
        "autonomy": 5,
        "actionability": 5,
        "safety": 5,
        "concision": 5,
        "blocker": False,
    }
    with pytest.raises(SchemaError, match="identical"):
        compare_scores([{**base, "condition": "baseline"}, {**base, "case_id": "b", "condition": "candidate"}])


def test_compare_applies_safety_blocker_and_floor():
    rows = []
    for condition in ("baseline", "candidate"):
        rows.append(
            {
                "case_id": "a",
                "trial": 1,
                "condition": condition,
                "correctness": 5,
                "autonomy": 5,
                "actionability": 5,
                "safety": 1 if condition == "candidate" else 5,
                "concision": 5,
                "blocker": condition == "candidate",
            }
        )

    report = compare_scores(rows)

    assert report["release"] is False
    assert any("safety" in reason for reason in report["reasons"])
    assert any("blocking" in reason for reason in report["reasons"])


def test_adapter_runtime_drift_is_rejected(tmp_path: Path):
    class DriftAdapter(FakeAdapter):
        def run(self, request):
            result = super().run(request)
            return AdapterResult(
                response=result.response,
                reported_runtime=RuntimePin("fixture", "wrong-model", "high"),
            )

    with pytest.raises(SchemaError, match="pinned runtime"):
        run_pair(load_cases(), DriftAdapter(), output=tmp_path / "out.jsonl")


def test_spend_budget_rejects_token_overage():
    budget = SpendBudget(max_cost_usd=1, max_tokens=3)

    budget.consume(AdapterResult(response="ok", input_tokens=1, output_tokens=2))
    with pytest.raises(BudgetExceeded, match="usage cap"):
        budget.consume(AdapterResult(response="too much", input_tokens=1))


def _run_fixture_rows() -> Path:
    """Create a small temporary JSONL artifact through the public CLI contract."""

    import tempfile

    handle = tempfile.NamedTemporaryFile(prefix="skill-eval-", suffix=".jsonl", delete=False)
    handle.close()
    path = Path(handle.name)
    run_pair(load_cases(), FakeAdapter(), output=path)
    return path
