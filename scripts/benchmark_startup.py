#!/usr/bin/env python3
"""Measure Spark's cold ``core.run_agent`` import in fresh processes."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PROBE = (
    "import json,resource,sys,time;"
    "started=time.perf_counter();import core.run_agent;elapsed=time.perf_counter()-started;"
    "rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss;"
    "rss_kib=rss/1024 if sys.platform=='darwin' else rss;"
    "print(json.dumps({'seconds':elapsed,'modules':len(sys.modules),'rss_kib':rss_kib}))"
)


def measure(trials: int) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    rows = []
    for _ in range(trials):
        result = subprocess.run(
            [sys.executable, "-c", PROBE],
            cwd=ROOT,
            env=env,
            check=True,
            text=True,
            capture_output=True,
            timeout=30,
        )
        rows.append(json.loads(result.stdout))
    seconds = [row["seconds"] for row in rows]
    return {
        "target": "import core.run_agent",
        "trials": rows,
        "median_seconds": statistics.median(seconds),
        "p95_seconds": sorted(seconds)[max(0, round(0.95 * len(seconds)) - 1)],
        "median_modules": statistics.median(row["modules"] for row in rows),
        "median_rss_kib": statistics.median(row["rss_kib"] for row in rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--assert-median", type=float)
    args = parser.parse_args()
    report = measure(max(1, args.trials))
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.assert_median is not None and report["median_seconds"] > args.assert_median:
        print(
            f"startup median {report['median_seconds']:.4f}s exceeds {args.assert_median:.4f}s",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
