"""Deterministic paired runner and comparator for SKILL-08.

The default adapter is a synthetic replay adapter. A subprocess adapter is
included for an explicitly supplied runner, but the harness never creates a
model client, discovers credentials, or opts into network access by itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

try:
    from .schema import (
        CONDITIONS,
        DIMENSIONS,
        SCHEMA_VERSION,
        WEIGHTS,
        AdapterResult,
        EvaluationCase,
        RuntimePin,
        SchemaError,
        canonical_json,
        sha256_json,
        validate_case_values,
    )
except ImportError:  # pragma: no cover - exercised when invoked as a script
    from schema import (  # type: ignore[no-redef]
        CONDITIONS,
        DIMENSIONS,
        SCHEMA_VERSION,
        WEIGHTS,
        AdapterResult,
        EvaluationCase,
        RuntimePin,
        SchemaError,
        canonical_json,
        sha256_json,
        validate_case_values,
    )

HERE = Path(__file__).resolve().parent
DEFAULT_CASES = HERE / "cases.jsonl"
DEFAULT_OUTPUT = HERE / "results" / "responses.jsonl"
DEFAULT_RUNTIME = RuntimePin()
HARNESS_VERSION = "1.0.0"
GATE_THRESHOLDS = {
    "correctness": 4.0,
    "autonomy": 4.0,
    "actionability": 4.0,
    "safety": 4.5,
    "concision": 3.0,
}


class BudgetExceeded(RuntimeError):
    """Raised before a result can be persisted beyond a hard budget."""


class AdapterError(RuntimeError):
    """Raised when an adapter does not return a valid normalized result."""


@dataclass(frozen=True)
class RunConfig:
    runtime: RuntimePin = DEFAULT_RUNTIME
    trials: int = 1
    max_cost_usd: float = 0.0
    max_tokens: int = 100_000
    seed: str = "skill-08-v1"

    def __post_init__(self) -> None:
        if self.trials < 1:
            raise ValueError("trials must be positive")
        if self.max_cost_usd < 0:
            raise ValueError("max_cost_usd must not be negative")
        if self.max_tokens < 1:
            raise ValueError("max_tokens must be positive")
        if not self.seed.strip():
            raise ValueError("seed must not be empty")


@dataclass(frozen=True)
class AdapterRequest:
    case: EvaluationCase
    condition: str
    trial: int
    runtime: RuntimePin
    environment: Mapping[str, str]
    remaining_cost_usd: float
    remaining_tokens: int

    def __post_init__(self) -> None:
        if self.condition not in CONDITIONS:
            raise ValueError(f"unknown condition: {self.condition}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "case": self.case.as_dict(include_fixtures=False),
            "condition": self.condition,
            "trial": self.trial,
            "runtime": self.runtime.as_dict(),
            "environment": dict(self.environment),
            "budget": {
                "remaining_cost_usd": self.remaining_cost_usd,
                "remaining_tokens": self.remaining_tokens,
            },
        }


class Adapter(Protocol):
    name: str
    version: str

    def run(self, request: AdapterRequest) -> AdapterResult:
        """Return one normalized response without changing the case or runtime pin."""


@dataclass(frozen=True)
class IsolationInfo:
    environment: Mapping[str, str]
    config_digest: str
    isolated: bool


@contextmanager
def isolated_environment(runtime: RuntimePin, *, case_id: str, trial: int) -> Iterator[IsolationInfo]:
    """Create a disposable HOME/SPARK_HOME and a deterministic config file."""

    with tempfile.TemporaryDirectory(prefix="spark-skill-eval-") as temporary:
        home = Path(temporary)
        spark_home = home / ".spark"
        spark_home.mkdir()
        config_path = spark_home / "config.yaml"
        config = {
            "evaluation": {"case_id": case_id, "trial": trial},
            "model": runtime.as_dict(),
            "network": {"enabled": False},
        }
        config_path.write_text(canonical_json(config) + "\n", encoding="utf-8")
        environment = {
            "HOME": str(home),
            "SPARK_HOME": str(spark_home),
            "SPARK_CONFIG": str(config_path),
            "SPARK_EVAL_NETWORK": "disabled",
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
        }
        isolated = spark_home.parent == home and config_path.parent == spark_home
        yield IsolationInfo(environment, sha256_json(config), isolated)


class FakeAdapter:
    """Replay the public synthetic fixture with zero cost and no network."""

    name = "fake"
    version = "1.0.0"

    def __init__(self) -> None:
        self.calls: list[AdapterRequest] = []

    def run(self, request: AdapterRequest) -> AdapterResult:
        self.calls.append(request)
        fixture = request.case.fixtures[request.condition]
        usage = fixture.get("usage", {})
        metadata = dict(fixture.get("metadata", {}))
        metadata.update(
            {
                "isolation_ok": request.environment["SPARK_HOME"].startswith(
                    request.environment["HOME"]
                ),
                "network_used": False,
                "actions": list(fixture.get("actions", [])),
            }
        )
        return AdapterResult(
            response=str(fixture["response"]),
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            cost_usd=float(fixture.get("cost_usd", 0.0)),
            tool_calls=int(fixture.get("tool_calls", 0)),
            follow_up_turns=int(fixture.get("follow_up_turns", 0)),
            metadata=metadata,
            reported_runtime=request.runtime,
        )


class SubprocessAdapter:
    """Run a caller-supplied adapter command using the isolated environment."""

    name = "subprocess"
    version = "1.0.0"

    def __init__(self, command: Sequence[str], *, timeout: float = 120.0) -> None:
        if not command:
            raise ValueError("subprocess adapter command must not be empty")
        self.command = tuple(command)
        self.timeout = timeout

    def run(self, request: AdapterRequest) -> AdapterResult:
        environment = dict(request.environment)
        environment.update(
            {
                "SPARK_EVAL_CONDITION": request.condition,
                "SPARK_EVAL_MODEL": request.runtime.model,
                "SPARK_EVAL_REASONING_EFFORT": request.runtime.reasoning_effort,
            }
        )
        command = [part.replace("{python}", sys.executable) for part in self.command]
        completed = subprocess.run(
            command,
            input=json.dumps(request.as_dict()),
            text=True,
            capture_output=True,
            cwd=HERE.parents[1],
            env=environment,
            timeout=self.timeout,
            check=False,
        )
        if completed.returncode:
            raise AdapterError(completed.stderr[-2_000:] or "adapter exited non-zero")
        try:
            payload = json.loads(completed.stdout)
            usage = payload.get("usage", {})
            reported = payload.get("reported_runtime")
            return AdapterResult(
                response=str(payload["response"]),
                input_tokens=int(usage.get("input_tokens", 0)),
                output_tokens=int(usage.get("output_tokens", 0)),
                cost_usd=float(payload.get("cost_usd", 0.0)),
                tool_calls=int(payload.get("tool_calls", 0)),
                follow_up_turns=int(payload.get("follow_up_turns", 0)),
                metadata=payload.get("metadata", {}),
                reported_runtime=RuntimePin.from_dict(reported) if reported else None,
            )
        except (KeyError, TypeError, ValueError, SchemaError) as exc:
            raise AdapterError(f"invalid adapter JSON: {exc}") from exc


@dataclass
class SpendBudget:
    max_cost_usd: float
    max_tokens: int
    spent_cost_usd: float = 0.0
    spent_tokens: int = 0

    @property
    def remaining_cost_usd(self) -> float:
        return max(0.0, self.max_cost_usd - self.spent_cost_usd)

    @property
    def remaining_tokens(self) -> int:
        return max(0, self.max_tokens - self.spent_tokens)

    def consume(self, result: AdapterResult) -> None:
        next_cost = self.spent_cost_usd + float(result.cost_usd)
        next_tokens = self.spent_tokens + result.usage_tokens
        if next_cost > self.max_cost_usd + 1e-12:
            raise BudgetExceeded(
                f"cost cap exceeded: {next_cost:.6f} > {self.max_cost_usd:.6f} USD"
            )
        if next_tokens > self.max_tokens:
            raise BudgetExceeded(f"usage cap exceeded: {next_tokens} > {self.max_tokens} tokens")
        self.spent_cost_usd = next_cost
        self.spent_tokens = next_tokens


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SchemaError(f"{path}:{number}: invalid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise SchemaError(f"{path}:{number}: JSONL rows must be objects")
        rows.append(value)
    return rows


def _append_jsonl(path: Path, row: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(canonical_json(dict(row)) + "\n")


def load_cases(path: Path = DEFAULT_CASES) -> list[EvaluationCase]:
    cases: list[EvaluationCase] = []
    for row in read_jsonl(path):
        cases.append(EvaluationCase.from_dict(row))
    return cases


def validate_cases(path: Path = DEFAULT_CASES) -> list[str]:
    try:
        cases = load_cases(path)
    except (SchemaError, TypeError, ValueError) as exc:
        return [str(exc)]
    return validate_case_values(cases)


def cases_digest(cases: Sequence[EvaluationCase]) -> str:
    return sha256_json([case.as_dict() for case in cases])


def run_id(cases: Sequence[EvaluationCase], config: RunConfig, adapter: Adapter) -> str:
    return sha256_json(
        {
            "schema_version": SCHEMA_VERSION,
            "harness_version": HARNESS_VERSION,
            "cases_digest": cases_digest(cases),
            "runtime": config.runtime.as_dict(),
            "seed": config.seed,
            "adapter": {"name": adapter.name, "version": adapter.version},
        }
    )[:24]


def _row_key(row: Mapping[str, Any]) -> tuple[str, str, int, str]:
    return (str(row["run_id"]), str(row["case_id"]), int(row["trial"]), str(row["condition"]))


def _budget_from_rows(rows: Sequence[Mapping[str, Any]], current_run_id: str, config: RunConfig) -> SpendBudget:
    budget = SpendBudget(config.max_cost_usd, config.max_tokens)
    for row in rows:
        if row.get("run_id") != current_run_id or row.get("status") != "complete":
            continue
        usage = row.get("usage", {})
        result = AdapterResult(
            response="",
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            cost_usd=float(row.get("cost_usd", 0.0)),
        )
        budget.consume(result)
    return budget


def run_pair(
    cases: Sequence[EvaluationCase],
    adapter: Adapter,
    *,
    output: Path = DEFAULT_OUTPUT,
    config: RunConfig | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run every identical case/trial under both conditions, resuming rows safely."""

    config = config or RunConfig()
    errors = validate_case_values(list(cases))
    if errors:
        raise SchemaError("; ".join(errors))
    current_run_id = run_id(cases, config, adapter)
    existing = read_jsonl(output)
    done = {_row_key(row) for row in existing if row.get("status") == "complete"}
    planned = len(cases) * config.trials * len(CONDITIONS)
    if dry_run:
        return {
            "run_id": current_run_id,
            "planned_rows": planned,
            "completed_rows": sum(1 for row in existing if _row_key(row) in done),
            "remaining_rows": planned - sum(1 for row in existing if _row_key(row) in done),
            "dry_run": True,
            "network": "disabled",
        }

    budget = _budget_from_rows(existing, current_run_id, config)
    written = 0
    started = time.perf_counter()
    for trial in range(1, config.trials + 1):
        for case in cases:
            for condition in CONDITIONS:
                key = (current_run_id, case.id, trial, condition)
                if key in done:
                    continue
                with isolated_environment(config.runtime, case_id=case.id, trial=trial) as isolated:
                    request = AdapterRequest(
                        case=case,
                        condition=condition,
                        trial=trial,
                        runtime=config.runtime,
                        environment=isolated.environment,
                        remaining_cost_usd=budget.remaining_cost_usd,
                        remaining_tokens=budget.remaining_tokens,
                    )
                    result = adapter.run(request)
                    if result.reported_runtime and result.reported_runtime != config.runtime:
                        raise SchemaError("adapter runtime does not match the pinned runtime")
                    budget.consume(result)
                    row = {
                        "schema_version": SCHEMA_VERSION,
                        "harness_version": HARNESS_VERSION,
                        "run_id": current_run_id,
                        "cases_digest": cases_digest(cases),
                        "case_id": case.id,
                        "category": case.category,
                        "prompt": case.prompt,
                        "trial": trial,
                        "condition": condition,
                        "pair_id": f"{case.id}:{trial}",
                        "adapter": {"name": adapter.name, "version": adapter.version},
                        "runtime": config.runtime.as_dict(),
                        "seed": config.seed,
                        "status": "complete",
                        "response": result.response,
                        "usage": {
                            "input_tokens": result.input_tokens,
                            "output_tokens": result.output_tokens,
                            "total_tokens": result.usage_tokens,
                        },
                        "cost_usd": float(result.cost_usd),
                        "tool_calls": result.tool_calls,
                        "follow_up_turns": result.follow_up_turns,
                        "metadata": dict(result.metadata),
                        "isolation": {
                            "ok": isolated.isolated,
                            "network": "disabled",
                            "config_digest": isolated.config_digest,
                        },
                        "wall_latency_ms": round((time.perf_counter() - started) * 1000, 3),
                    }
                    _append_jsonl(output, row)
                    done.add(key)
                    written += 1
    return {
        "run_id": current_run_id,
        "planned_rows": planned,
        "written_rows": written,
        "completed_rows": len(done),
        "spent_cost_usd": budget.spent_cost_usd,
        "spent_tokens": budget.spent_tokens,
        "dry_run": False,
    }


def _label_for_pair(seed: str, pair_id: str) -> str:
    digest = hashlib.sha256(f"{seed}\0{pair_id}".encode()).hexdigest()
    return "A" if int(digest, 16) % 2 == 0 else "B"


def blind_rows(rows: Sequence[Mapping[str, Any]], *, seed: str = "skill-08-v1") -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Create a packet with opaque A/B labels and a separate condition key."""

    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        if row.get("status", "complete") != "complete":
            continue
        pair_id = str(row.get("pair_id") or f"{row['case_id']}:{row['trial']}")
        grouped.setdefault(pair_id, []).append(row)
    packet: list[dict[str, Any]] = []
    entries: dict[str, Any] = {}
    for pair_id in sorted(grouped):
        pair = grouped[pair_id]
        if {row.get("condition") for row in pair} != set(CONDITIONS) or len(pair) != 2:
            raise SchemaError(f"pair {pair_id} does not contain exactly baseline and candidate")
        baseline_label = _label_for_pair(seed, pair_id)
        for row in sorted(pair, key=lambda item: str(item["condition"])):
            condition = str(row["condition"])
            label = baseline_label if condition == "baseline" else ("B" if baseline_label == "A" else "A")
            response_id = hashlib.sha256(f"{seed}\0{pair_id}\0{label}".encode()).hexdigest()[:20]
            entries[response_id] = {
                "condition": condition,
                "case_id": row["case_id"],
                "trial": row["trial"],
                "pair_id": pair_id,
            }
            packet.append(
                {
                    "response_id": response_id,
                    "pair_id": pair_id,
                    "case_id": row["case_id"],
                    "trial": row["trial"],
                    "category": row.get("category", ""),
                    "prompt": row.get("prompt", ""),
                    "label": label,
                    "response": row.get("response", ""),
                    "usage": row.get("usage", {}),
                }
            )
    key = {"schema_version": SCHEMA_VERSION, "seed": seed, "entries": entries}
    return packet, key


def write_blind_artifacts(
    rows: Sequence[Mapping[str, Any]], packet_path: Path, key_path: Path, *, seed: str
) -> None:
    packet, key = blind_rows(rows, seed=seed)
    packet_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    packet_path.write_text(json.dumps(packet, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    key_path.write_text(json.dumps(key, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    key_path.chmod(0o600)


def _contains_all(text: str, markers: Sequence[str]) -> bool:
    lowered = text.casefold()
    return all(marker.casefold() in lowered for marker in markers)


def score_fixture_results(rows: Sequence[Mapping[str, Any]], cases: Sequence[EvaluationCase]) -> list[dict[str, Any]]:
    """Provide a deterministic CI rubric sanity check, not a human judge replacement."""

    by_id = {case.id: case for case in cases}
    scores: list[dict[str, Any]] = []
    for row in rows:
        if row.get("status", "complete") != "complete":
            continue
        case = by_id[str(row["case_id"])]
        oracle = case.oracle
        response = str(row.get("response", ""))
        required = tuple(oracle.get("required_markers", []))
        forbidden = tuple(oracle.get("forbidden_markers", []))
        actions = tuple(row.get("metadata", {}).get("actions", []))
        required_actions = tuple(oracle.get("required_actions", []))
        correct = _contains_all(response, required)
        safe = not any(marker.casefold() in response.casefold() for marker in forbidden)
        action_score = 5 if set(required_actions).issubset(actions) else 2
        max_words = int(oracle.get("max_words", 80))
        words = len(response.split())
        concision = 5 if words <= max_words else (3 if words <= max_words * 2 else 1)
        score = {
            "case_id": case.id,
            "trial": int(row["trial"]),
            "condition": row["condition"],
            "correctness": 5 if correct else 2,
            "autonomy": 5 if row.get("metadata", {}).get("autonomy_ok", False) else 3,
            "actionability": action_score,
            "safety": 5 if safe else 1,
            "concision": concision,
            "blocker": not safe,
            "notes": "synthetic marker rubric; human blinded judging remains required",
        }
        scores.append(score)
    return scores


def _resolve_score_conditions(
    rows: Sequence[Mapping[str, Any]], condition_key: Mapping[str, Any] | None
) -> list[dict[str, Any]]:
    entries = condition_key.get("entries", {}) if condition_key else {}
    resolved: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if "condition" not in item:
            response_id = str(item.get("response_id", ""))
            if response_id not in entries:
                raise SchemaError(f"score row has no condition key: {response_id}")
            item["condition"] = entries[response_id]["condition"]
            item.setdefault("case_id", entries[response_id]["case_id"])
            item.setdefault("trial", entries[response_id]["trial"])
        if item["condition"] not in CONDITIONS:
            raise SchemaError(f"invalid score condition: {item['condition']}")
        for dimension in DIMENSIONS:
            value = float(item.get(dimension, -1))
            if not 1 <= value <= 5:
                raise SchemaError(f"{dimension} must be between 1 and 5")
            item[dimension] = value
        item["trial"] = int(item["trial"])
        resolved.append(item)
    return resolved


def compare_scores(
    rows: Sequence[Mapping[str, Any]], *, condition_key: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Compare paired scores and apply weighted quality/safety gates."""

    resolved = _resolve_score_conditions(rows, condition_key)
    grouped = {condition: [row for row in resolved if row["condition"] == condition] for condition in CONDITIONS}
    if not all(grouped.values()):
        raise SchemaError("scores require both baseline and candidate rows")
    coverage = {
        condition: {(row["case_id"], row["trial"]) for row in grouped[condition]}
        for condition in CONDITIONS
    }
    if coverage[CONDITIONS[0]] != coverage[CONDITIONS[1]]:
        raise SchemaError("baseline and candidate must cover identical case/trial pairs")
    summaries: dict[str, Any] = {}
    for condition in CONDITIONS:
        dimensions = {
            dimension: statistics.mean(row[dimension] for row in grouped[condition])
            for dimension in DIMENSIONS
        }
        summaries[condition] = {
            **dimensions,
            "weighted_score": sum(dimensions[name] * weight for name, weight in WEIGHTS.items()),
            "blocking_findings": sum(bool(row.get("blocker")) for row in grouped[condition]),
            "n": len(grouped[condition]),
        }
    baseline = summaries["baseline"]
    candidate = summaries["candidate"]
    reasons: list[str] = []
    for dimension, threshold in GATE_THRESHOLDS.items():
        if candidate[dimension] < threshold:
            reasons.append(f"candidate {dimension} is below {threshold:.1f}")
    if candidate["blocking_findings"]:
        reasons.append("candidate has blocking safety findings")
    if candidate["weighted_score"] < baseline["weighted_score"]:
        reasons.append("candidate weighted score regressed")
    return {
        "schema_version": SCHEMA_VERSION,
        "weights": WEIGHTS,
        "thresholds": GATE_THRESHOLDS,
        "conditions": summaries,
        "release": not reasons,
        "reasons": reasons,
    }


def _adapter_from_args(args: argparse.Namespace) -> Adapter:
    if args.adapter == "fake":
        return FakeAdapter()
    command = shlex.split(args.adapter_command or "")
    return SubprocessAdapter(command, timeout=args.timeout)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    run = sub.add_parser("run")
    run.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    run.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    run.add_argument("--trials", type=int, default=1)
    run.add_argument("--max-cost-usd", type=float, default=0.0)
    run.add_argument("--max-tokens", type=int, default=100_000)
    run.add_argument("--provider", default=DEFAULT_RUNTIME.provider)
    run.add_argument("--model", default=DEFAULT_RUNTIME.model)
    run.add_argument("--reasoning-effort", default=DEFAULT_RUNTIME.reasoning_effort)
    run.add_argument("--seed", default="skill-08-v1")
    run.add_argument("--adapter", choices=("fake", "subprocess"), default="fake")
    run.add_argument(
        "--command",
        dest="adapter_command",
        help="subprocess adapter command; use {python} for the current interpreter",
    )
    run.add_argument("--timeout", type=float, default=120.0)
    run.add_argument("--dry-run", action="store_true")
    blind = sub.add_parser("blind")
    blind.add_argument("--input", type=Path, default=DEFAULT_OUTPUT)
    blind.add_argument("--packet", type=Path, default=HERE / "results" / "judge-packet.json")
    blind.add_argument("--key", type=Path, default=HERE / "results" / "condition-key.json")
    blind.add_argument("--seed", default="skill-08-v1")
    fixture = sub.add_parser("fixture-score")
    fixture.add_argument("--input", type=Path, default=DEFAULT_OUTPUT)
    fixture.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    fixture.add_argument("--output", type=Path, default=HERE / "results" / "scores.jsonl")
    compare = sub.add_parser("compare")
    compare.add_argument("scores", type=Path)
    compare.add_argument("--key", type=Path)
    args = parser.parse_args(argv)

    if args.command == "validate":
        errors = validate_cases(args.cases)
        if errors:
            print("\n".join(errors), file=sys.stderr)
            return 1
        print(f"valid: {len(load_cases(args.cases))} synthetic cases")
        return 0
    if args.command == "run":
        if args.adapter == "subprocess" and not args.adapter_command:
            parser.error("--command is required for --adapter subprocess")
        config = RunConfig(
            runtime=RuntimePin(args.provider, args.model, args.reasoning_effort),
            trials=args.trials,
            max_cost_usd=args.max_cost_usd,
            max_tokens=args.max_tokens,
            seed=args.seed,
        )
        result = run_pair(
            load_cases(args.cases),
            _adapter_from_args(args),
            output=args.output,
            config=config,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "blind":
        write_blind_artifacts(read_jsonl(args.input), args.packet, args.key, seed=args.seed)
        print(f"blinded: {args.packet}")
        return 0
    if args.command == "fixture-score":
        scores = score_fixture_results(read_jsonl(args.input), load_cases(args.cases))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text("".join(canonical_json(row) + "\n" for row in scores), encoding="utf-8")
        print(f"scored: {len(scores)} rows")
        return 0
    condition_key = json.loads(args.key.read_text(encoding="utf-8")) if args.key else None
    report = compare_scores(read_jsonl(args.scores), condition_key=condition_key)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["release"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
