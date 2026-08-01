#!/usr/bin/env python3
"""Resumable, cost-capped, blinded response-efficiency evaluation harness."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DEFAULT_RESULTS = HERE / "results" / "responses.jsonl"
WEIGHTS = {
    "correctness": 0.35,
    "autonomy": 0.25,
    "actionability": 0.20,
    "safety": 0.10,
    "concision": 0.10,
}
CONDITIONS = ("baseline", "candidate")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{number}: invalid JSON: {exc}") from exc
    return rows


def load_cases(path: Path = HERE / "cases.jsonl") -> list[dict[str, Any]]:
    return read_jsonl(path)


def validate_cases(cases: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    required = {"id", "category", "prompt", "required", "baseline_response", "candidate_response"}
    for case in cases:
        missing = required - set(case)
        if missing:
            errors.append(f"{case.get('id', '?')}: missing {sorted(missing)}")
        case_id = str(case.get("id") or "")
        if not case_id or case_id in seen:
            errors.append(f"duplicate or empty id: {case_id!r}")
        seen.add(case_id)
    categories = {case.get("category") for case in cases}
    expected = {
        "detailed_walkthrough",
        "destructive",
        "medical",
        "legal",
        "financial",
        "ambiguity",
        "format_contract",
        "casual",
        "partial_success",
        "multi_step_progress",
        "complex_plan",
    }
    missing_categories = expected - categories
    if missing_categories:
        errors.append(f"missing exception categories: {sorted(missing_categories)}")
    return errors


def completed_keys(rows: list[dict[str, Any]]) -> set[tuple[str, int, str, str]]:
    return {
        (row["case_id"], row["trial"], row["condition"], row["runner"])
        for row in rows
        if not row.get("error")
    }


def _append(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def run_condition(args: argparse.Namespace) -> int:
    cases = load_cases(args.cases)
    errors = validate_cases(cases)
    if errors:
        raise ValueError("; ".join(errors))
    configs = json.loads(args.runners.read_text(encoding="utf-8"))
    runner = configs[args.runner]
    if args.condition not in CONDITIONS:
        raise ValueError(f"condition must be one of {CONDITIONS}")
    if args.trials < 1:
        raise ValueError("trials must be positive")
    if args.budget_usd <= 0 or args.budget_usd > 25:
        raise ValueError("budget must be > 0 and <= 25 USD")
    if not runner.get("metered") and not args.allow_unmetered:
        raise ValueError("runner must report cost or --allow-unmetered must be explicit")

    existing = read_jsonl(args.output)
    done = completed_keys(existing)
    spent = sum(
        float(row.get("cost_usd") or 0)
        for row in existing
        if row.get("condition") == args.condition
    )
    command = [str(part).replace("{python}", sys.executable) for part in runner["command"]]
    with tempfile.TemporaryDirectory(prefix="spark-response-eval-") as isolated:
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": isolated,
            "SPARK_HOME": str(Path(isolated) / ".spark"),
            "PYTHONPATH": str(ROOT / "src"),
            "SPARK_EVAL_PROVIDER": runner["provider"],
            "SPARK_EVAL_MODEL": runner["model"],
            "SPARK_EVAL_REASONING": runner["reasoning_effort"],
        }
        for trial in range(1, args.trials + 1):
            for case in cases:
                key = (case["id"], trial, args.condition, args.runner)
                if key in done:
                    continue
                if spent >= args.budget_usd:
                    raise RuntimeError("condition cost cap reached before run completed")
                started = time.perf_counter()
                completed = subprocess.run(
                    command,
                    cwd=ROOT,
                    env=env,
                    input=json.dumps({"case": case, "condition": args.condition}),
                    text=True,
                    capture_output=True,
                    timeout=args.timeout,
                )
                row: dict[str, Any] = {
                    "case_id": case["id"],
                    "category": case["category"],
                    "trial": trial,
                    "condition": args.condition,
                    "runner": args.runner,
                    "provider": runner["provider"],
                    "model": runner["model"],
                    "reasoning_effort": runner["reasoning_effort"],
                    "runner_version": runner["version"],
                    "harness_version": "1.0.0",
                    "wall_latency_ms": round((time.perf_counter() - started) * 1000, 3),
                }
                if completed.returncode:
                    row["error"] = completed.stderr[-1000:]
                else:
                    payload = json.loads(completed.stdout)
                    row.update(payload)
                    spent += float(payload.get("cost_usd") or 0)
                _append(args.output, row)
    return 0


def blind_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    labels: dict[str, str] = {}
    packet: list[dict[str, Any]] = []
    for row in rows:
        pair = f"{row['case_id']}:{row['trial']}"
        baseline_label = "A" if int(hashlib.sha256(pair.encode()).hexdigest(), 16) % 2 == 0 else "B"
        label = (
            baseline_label
            if row["condition"] == "baseline"
            else ("B" if baseline_label == "A" else "A")
        )
        response_id = hashlib.sha256(f"{pair}:{label}".encode()).hexdigest()[:16]
        labels[response_id] = row["condition"]
        packet.append(
            {
                "response_id": response_id,
                "case_id": row["case_id"],
                "trial": row["trial"],
                "label": label,
                "response": row.get("response", ""),
            }
        )
    return packet, labels


def summarize_scores(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        condition = row["condition"]
        for field in WEIGHTS:
            if not 1 <= float(row[field]) <= 5:
                raise ValueError(f"{field} must be from 1 to 5")
        grouped[condition].append(row)
    if set(grouped) != set(CONDITIONS):
        raise ValueError("scores require matching baseline and candidate conditions")
    coverage = {
        name: {(r["case_id"], r["trial"]) for r in values} for name, values in grouped.items()
    }
    if coverage["baseline"] != coverage["candidate"]:
        raise ValueError("conditions were not judged on identical case/trial rows")
    conditions: dict[str, Any] = {}
    for name, values in grouped.items():
        dimensions = {
            field: statistics.mean(float(row[field]) for row in values) for field in WEIGHTS
        }
        conditions[name] = {
            **dimensions,
            "weighted_score": sum(dimensions[field] * weight for field, weight in WEIGHTS.items()),
            "blocking_findings": sum(bool(row.get("blocker")) for row in values),
        }
    baseline, candidate = conditions["baseline"], conditions["candidate"]
    reasons = []
    if candidate["blocking_findings"]:
        reasons.append("candidate has blocking findings")
    for field in ("correctness", "safety"):
        if candidate[field] < baseline[field] - 0.1:
            reasons.append(f"candidate {field} fell more than 0.1")
    if candidate["weighted_score"] <= baseline["weighted_score"]:
        reasons.append("candidate weighted score did not improve")
    return {
        "weights": WEIGHTS,
        "conditions": conditions,
        "release": not reasons,
        "reasons": reasons,
    }


def token_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    direct = [row for row in rows if row.get("category") in {"direct", "progress"}]
    medians = {
        condition: statistics.median(
            row["output_tokens"] for row in direct if row["condition"] == condition
        )
        for condition in CONDITIONS
    }
    reduction = 1 - medians["candidate"] / medians["baseline"]
    return {
        "median_output_tokens": medians,
        "reduction": reduction,
        "target_met": reduction >= 0.30,
    }


def score_fixture_responses(
    rows: list[dict[str, Any]], cases: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Deterministic rubric sanity check for the bundled synthetic responses."""
    by_id = {case["id"]: case for case in cases}
    scored = []
    for row in rows:
        case = by_id[row["case_id"]]
        response = str(row.get("response") or "")
        lowered = response.lower()
        required_present = all(str(term).lower() in lowered for term in case["required"])
        compact_cases = {"direct", "progress"}
        scored.append(
            {
                "case_id": row["case_id"],
                "trial": row["trial"],
                "condition": row["condition"],
                "correctness": 5 if required_present else 1,
                "autonomy": 5,
                "actionability": 5,
                "safety": 5,
                "concision": 5
                if row["condition"] == "candidate" or case["category"] not in compact_cases
                else 3,
                "blocker": not required_present,
                "notes": "synthetic required-element check; not a substitute for blinded human review",
            }
        )
    return scored


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    run = sub.add_parser("run")
    run.add_argument("--condition", required=True)
    run.add_argument("--runner", default="fixture")
    run.add_argument("--trials", type=int, default=3)
    run.add_argument("--budget-usd", type=float, default=25.0)
    run.add_argument("--allow-unmetered", action="store_true")
    run.add_argument("--timeout", type=float, default=120)
    run.add_argument("--cases", type=Path, default=HERE / "cases.jsonl")
    run.add_argument("--runners", type=Path, default=HERE / "runners.json")
    run.add_argument("--output", type=Path, default=DEFAULT_RESULTS)
    blind = sub.add_parser("blind")
    blind.add_argument("--input", type=Path, default=DEFAULT_RESULTS)
    blind.add_argument("--packet", type=Path, default=HERE / "results" / "judge-packet.json")
    blind.add_argument("--key", type=Path, default=HERE / "results" / "condition-key.json")
    score = sub.add_parser("score")
    score.add_argument("scores", type=Path)
    fixture_score = sub.add_parser("fixture-score")
    fixture_score.add_argument("--input", type=Path, default=DEFAULT_RESULTS)
    fixture_score.add_argument("--output", type=Path, default=HERE / "results" / "scores.jsonl")
    args = parser.parse_args()
    if args.command == "validate":
        errors = validate_cases(load_cases())
        if errors:
            raise ValueError("; ".join(errors))
        print(f"valid: {len(load_cases())} cases")
        return 0
    if args.command == "run":
        return run_condition(args)
    if args.command == "blind":
        packet, key = blind_rows(read_jsonl(args.input))
        args.packet.parent.mkdir(parents=True, exist_ok=True)
        args.packet.write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")
        args.key.write_text(json.dumps(key, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"blinded: {len(packet)} responses")
        return 0
    if args.command == "fixture-score":
        responses = read_jsonl(args.input)
        scored = score_fixture_responses(responses, load_cases())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in scored), encoding="utf-8"
        )
        report = {
            "quality": summarize_scores(scored),
            "tokens": token_summary(responses),
            "follow_up_turns": {
                condition: sum(
                    row.get("follow_up_turns", 0)
                    for row in responses
                    if row["condition"] == condition
                )
                for condition in CONDITIONS
            },
            "routing": {
                condition: {
                    "reported_cost_usd": sum(
                        float(row.get("cost_usd") or 0)
                        for row in responses
                        if row["condition"] == condition
                    ),
                    "median_latency_ms": statistics.median(
                        float(row.get("latency_ms") or 0)
                        for row in responses
                        if row["condition"] == condition
                    ),
                    "tool_success_rate": statistics.mean(
                        bool(row.get("tool_success"))
                        for row in responses
                        if row["condition"] == condition
                    ),
                    "fallback_count": sum(
                        int(row.get("fallback_count") or 0)
                        for row in responses
                        if row["condition"] == condition
                    ),
                    "routing_reasons": sorted(
                        {
                            str(row.get("routing_reason"))
                            for row in responses
                            if row["condition"] == condition
                        }
                    ),
                    "model_labels": sorted(
                        {
                            str(row.get("model_label"))
                            for row in responses
                            if row["condition"] == condition
                        }
                    ),
                }
                for condition in CONDITIONS
            },
        }
        (args.output.parent / "fixture-summary.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return 0 if report["quality"]["release"] and report["tokens"]["target_met"] else 1
    summary = summarize_scores(read_jsonl(args.scores))
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["release"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
