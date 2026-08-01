#!/usr/bin/env python3
"""Capture repeatable fixture counters without calling an external model."""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from agent.efficiency_metrics import measure_request  # noqa: E402
from core.runtime_metrics import reset, snapshot  # noqa: E402
from core.spark_state import SessionDB  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
os.environ["SPARK_EFFICIENCY_METRICS"] = "1"


def _rows(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _expand_messages(case: dict) -> list[dict]:
    value = case["messages"]
    if isinstance(value, list):
        return value
    spec = value["generator"]
    messages: list[dict] = []
    for turn in range(1, int(spec["turns"]) + 1):
        messages.extend(
            [
                {"role": "user", "content": spec["user_template"].format(n=turn)},
                {"role": "assistant", "content": spec["assistant_template"].format(n=turn)},
            ]
        )
        if turn % int(spec.get("tool_every", 0) or 10**9) == 0:
            messages.append(
                {
                    "role": "tool",
                    "content": "Synthetic bounded tool result",
                    "tool_call_id": f"t{turn}",
                }
            )
    return messages


def _import_ms(module: str) -> float:
    command = [
        sys.executable,
        "-c",
        f"import importlib,time; s=time.perf_counter(); importlib.import_module({module!r}); print((time.perf_counter()-s)*1000)",
    ]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=True)
    return float(result.stdout.strip().splitlines()[-1])


def _p95(values: list[float]) -> float:
    return sorted(values)[max(0, math.ceil(len(values) * 0.95) - 1)]


def capture(trials: int = 3) -> dict:
    manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    cases = _rows(FIXTURES / manifest["cases_file"])
    raw: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="spark-efficiency-baseline-") as tmp:
        for case in cases:
            messages = _expand_messages(case)
            for trial in range(1, trials + 1):
                reset()
                started = time.perf_counter()
                accounting = measure_request(messages, case.get("tools"))
                db = SessionDB(Path(tmp) / f"{case['id']}-{trial}.db")
                try:
                    db.create_session(f"{case['id']}-{trial}", "fixture", "deterministic-replay-v1")
                    db.append_message(f"{case['id']}-{trial}", "user", content="Synthetic fixture")
                finally:
                    db.close()
                elapsed_ms = (time.perf_counter() - started) * 1000
                encoded_bytes = len(json.dumps(messages, separators=(",", ":")).encode("utf-8"))
                web_expected = {}
                if case.get("web_fixture"):
                    path = ROOT / "src/spark_cli/web/e2e/fixtures" / case["web_fixture"]
                    web_expected = json.loads(path.read_text(encoding="utf-8"))["expected"]
                raw.append(
                    {
                        "case_id": case["id"],
                        "workload": case["workload"],
                        "trial": trial,
                        "provider": manifest["pinned_runtime"]["provider"],
                        "model": manifest["pinned_runtime"]["model"],
                        "reasoning_effort": manifest["pinned_runtime"]["reasoning_effort"],
                        "elapsed_ms": round(elapsed_ms, 3),
                        "json_snapshot_bytes": encoded_bytes,
                        "request": accounting.__dict__,
                        "runtime": snapshot()["counters"],
                        "web_expected": web_expected,
                    }
                )
    import_trials = [_import_ms("core.run_agent") for _ in range(trials)]
    cli_startup_trials = [_import_ms("spark_cli.main") for _ in range(trials)]
    summaries = []
    for case in cases:
        rows = [row for row in raw if row["case_id"] == case["id"]]
        summaries.append(
            {
                "case_id": case["id"],
                "elapsed_ms_median": round(statistics.median(row["elapsed_ms"] for row in rows), 3),
                "elapsed_ms_p95": round(_p95([row["elapsed_ms"] for row in rows]), 3),
                "prompt_tokens_median": statistics.median(
                    row["request"]["estimated_prompt_tokens"] for row in rows
                ),
                "snapshot_bytes_median": statistics.median(
                    row["json_snapshot_bytes"] for row in rows
                ),
            }
        )
    return {
        "report_version": "1.0.0",
        "fixture_version": manifest["fixture_version"],
        "pinned_runtime": manifest["pinned_runtime"],
        "trials_per_fixture": trials,
        "raw_trials": raw,
        "summary": summaries,
        "import_core_run_agent_ms": {
            "raw": [round(value, 3) for value in import_trials],
            "median": round(statistics.median(import_trials), 3),
            "p95": round(_p95(import_trials), 3),
        },
        "import_spark_cli_main_ms": {
            "raw": [round(value, 3) for value in cli_startup_trials],
            "median": round(statistics.median(cli_startup_trials), 3),
            "p95": round(_p95(cli_startup_trials), 3),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.trials < 3:
        parser.error("--trials must be at least 3")
    report = capture(args.trials)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
