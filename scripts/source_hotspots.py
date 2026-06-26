#!/usr/bin/env python3
"""Report the largest tracked source files while excluding generated outputs."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".jsx",
    ".json",
    ".md",
    ".py",
    ".pyi",
    ".rs",
    ".toml",
    ".ts",
    ".tsx",
    ".yaml",
    ".yml",
}
EXCLUDED_PREFIXES = (
    "graphify-out/",
    "src/spark_cli/web/src-tauri/target/",
    "src/spark_cli/web/src-tauri/resources/",
    "src/spark_cli/web_dist/",
    "src/spark_cli/web/dist/",
)


def _git_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    )
    names = result.stdout.decode().split("\0")
    return [Path(name) for name in names if name]


def _is_source_file(path: Path, suffixes: set[str]) -> bool:
    normalized = path.as_posix()
    if any(normalized.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
        return False
    return path.suffix in suffixes


def _measure(path: Path) -> dict[str, Any]:
    absolute = REPO_ROOT / path
    data = absolute.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="ignore")
    return {
        "path": path.as_posix(),
        "lines": text.count("\n") + (0 if text.endswith("\n") or not text else 1),
        "bytes": len(data),
    }


def _format_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No source files matched."
    path_width = max(len("path"), *(len(str(row["path"])) for row in rows))
    lines = [f"{'lines':>8} {'bytes':>10}  {'path':<{path_width}}"]
    lines.append(f"{'-' * 8} {'-' * 10}  {'-' * path_width}")
    for row in rows:
        lines.append(f"{row['lines']:>8} {row['bytes']:>10}  {row['path']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=30, help="Number of files to show.")
    parser.add_argument(
        "--suffix",
        action="append",
        dest="suffixes",
        help="File suffix to include. May be repeated. Defaults to common source suffixes.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a table.")
    args = parser.parse_args()

    suffixes = set(args.suffixes or DEFAULT_SUFFIXES)
    suffixes = {suffix if suffix.startswith(".") else f".{suffix}" for suffix in suffixes}
    rows = [
        _measure(path)
        for path in _git_files()
        if _is_source_file(path, suffixes)
    ]
    rows.sort(key=lambda row: (row["lines"], row["bytes"], row["path"]), reverse=True)
    selected = rows[: max(args.limit, 0)]

    if args.json:
        print(json.dumps({"files": selected}, indent=2))
    else:
        print(_format_table(selected))
        print()
        print(
            "Excluded generated outputs: "
            + ", ".join(prefix.rstrip("/") for prefix in EXCLUDED_PREFIXES)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
