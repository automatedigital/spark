#!/usr/bin/env python3
"""Run mypy as a ratchet against the checked-in baseline.

The baseline stores current error budgets by file and mypy error code. The
default check allows existing debt to remain but fails if any file/error-code
bucket increases, or if the strict subset regresses.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = REPO_ROOT / "scripts" / "mypy_baseline.json"
MYPY_TARGETS = ("src/agent/", "src/spark_cli/")
STRICT_TARGETS = ("src/core/run_agent/iteration_budget.py",)
MYPY_FLAGS = ("--show-error-codes", "--no-error-summary", "--no-pretty")
ERROR_RE = re.compile(
    r"^(?P<path>.+?):(?P<line>\d+)(?::\d+)?: error: .*?(?:\s+\[(?P<code>[\w-]+)\])?$"
)
ERROR_NO_LINE_RE = re.compile(
    r"^(?P<path>.+?): error: .*?(?:\s+\[(?P<code>[\w-]+)\])?$"
)


def _mypy_command(*args: str) -> list[str]:
    return [sys.executable, "-m", "mypy", *MYPY_FLAGS, *args]


def _run(command: list[str]) -> tuple[int, str]:
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    output = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
    return result.returncode, output


def _parse_counts(output: str) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for line in output.splitlines():
        match = ERROR_RE.match(line) or ERROR_NO_LINE_RE.match(line)
        if not match:
            continue
        path = match.group("path")
        code = match.group("code") or "no-code"
        counts.setdefault(path, {})
        counts[path][code] = counts[path].get(code, 0) + 1
    return counts


def _total_errors(counts: dict[str, dict[str, int]]) -> int:
    return sum(sum(code_counts.values()) for code_counts in counts.values())


def _sorted_counts(counts: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    return {
        path: dict(sorted(code_counts.items()))
        for path, code_counts in sorted(counts.items())
    }


def _baseline_payload(counts: dict[str, dict[str, int]]) -> dict[str, Any]:
    return {
        "version": 1,
        "description": (
            "Current mypy debt for src/agent/ and src/spark_cli/, counted by file "
            "and mypy error code. Regenerate intentionally with "
            "`python scripts/mypy_ratchet.py --update`."
        ),
        "mypy_command": [*MYPY_FLAGS, *MYPY_TARGETS],
        "strict_targets": list(STRICT_TARGETS),
        "total_errors": _total_errors(counts),
        "files": _sorted_counts(counts),
    }


def _load_baseline(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        print(f"Missing mypy baseline: {path}", file=sys.stderr)
        print("Create it with: python scripts/mypy_ratchet.py --update", file=sys.stderr)
        raise SystemExit(2)
    if not isinstance(data, dict) or not all(isinstance(key, str) for key in data):
        print(f"Invalid baseline shape in {path}", file=sys.stderr)
        raise SystemExit(2)
    return dict(data)


def _write_baseline(path: Path, counts: dict[str, dict[str, int]]) -> None:
    path.write_text(json.dumps(_baseline_payload(counts), indent=2, sort_keys=True) + "\n")
    print(f"Updated {path.relative_to(REPO_ROOT)} with {_total_errors(counts)} mypy errors.")


def _check_strict_subset() -> bool:
    command = _mypy_command("--strict", *STRICT_TARGETS)
    returncode, output = _run(command)
    if returncode == 0:
        print("Strict mypy subset passed: " + ", ".join(STRICT_TARGETS))
        return True
    print("Strict mypy subset failed.", file=sys.stderr)
    print(output, file=sys.stderr)
    return False


def _collect_current_counts() -> tuple[int, str, dict[str, dict[str, int]]]:
    command = _mypy_command(*MYPY_TARGETS)
    returncode, output = _run(command)
    counts = _parse_counts(output)
    if returncode not in (0, 1):
        print(output, file=sys.stderr)
        raise SystemExit(returncode)
    if returncode != 0 and not counts:
        print("mypy failed but no parseable errors were found.", file=sys.stderr)
        print(output, file=sys.stderr)
        raise SystemExit(returncode)
    return returncode, output, counts


def _check_ratchet(baseline_path: Path, current: dict[str, dict[str, int]]) -> bool:
    baseline = _load_baseline(baseline_path)
    allowed = baseline.get("files", {})
    if not isinstance(allowed, dict):
        print(f"Invalid baseline shape in {baseline_path}", file=sys.stderr)
        return False

    violations: list[tuple[str, str, int, int]] = []
    for path, code_counts in sorted(current.items()):
        allowed_for_path = allowed.get(path, {})
        if not isinstance(allowed_for_path, dict):
            allowed_for_path = {}
        for code, count in sorted(code_counts.items()):
            budget = allowed_for_path.get(code, 0)
            if not isinstance(budget, int):
                budget = 0
            if count > budget:
                violations.append((path, code, count, budget))

    if violations:
        print("mypy ratchet failed: error budgets increased.", file=sys.stderr)
        for path, code, count, budget in violations[:25]:
            print(f"  {path} [{code}]: {count} > {budget}", file=sys.stderr)
        if len(violations) > 25:
            print(f"  ... and {len(violations) - 25} more increases", file=sys.stderr)
        print("Fix the new errors or intentionally refresh the baseline.", file=sys.stderr)
        return False

    baseline_total = int(baseline.get("total_errors", 0))
    current_total = _total_errors(current)
    print(f"mypy ratchet passed: {current_total} errors <= baseline {baseline_total}.")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline",
        type=Path,
        default=DEFAULT_BASELINE,
        help="Path to the mypy baseline JSON.",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Regenerate the baseline from current mypy output.",
    )
    parser.add_argument(
        "--skip-strict",
        action="store_true",
        help="Skip the strict subset check.",
    )
    args = parser.parse_args()

    baseline_path = args.baseline if args.baseline.is_absolute() else REPO_ROOT / args.baseline
    _, _, counts = _collect_current_counts()

    if args.update:
        _write_baseline(baseline_path, counts)
        if not args.skip_strict and not _check_strict_subset():
            return 1
        return 0

    ok = _check_ratchet(baseline_path, counts)
    if not args.skip_strict:
        ok = _check_strict_subset() and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
