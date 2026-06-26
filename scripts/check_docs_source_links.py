#!/usr/bin/env python3
"""Check docs/building backticked source paths still exist."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOC_ROOT = REPO_ROOT / "docs" / "building"
SOURCE_PREFIXES = (
    "agent/",
    "core/",
    "cron/",
    "environments/",
    "gateway/",
    "plugins/",
    "scripts/",
    "spark_cli/",
    "src/",
    "tests/",
    "tools/",
)
CODE_SPAN_RE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")


def _candidate_paths(text: str) -> set[str]:
    paths: set[str] = set()
    for match in CODE_SPAN_RE.finditer(text):
        token = match.group(1).strip().strip(".,;:")
        if (
            "<" in token
            or ">" in token
            or "your-" in token
            or token.startswith(("tools/your_", "gateway/platforms/new", "tests/gateway/test_new"))
        ):
            continue
        if " " in token or not token.startswith(SOURCE_PREFIXES):
            continue
        paths.add(token)
    return paths


def _exists(path_text: str) -> bool:
    normalized = path_text.split("#", 1)[0].rstrip("/")
    candidates = [normalized, f"src/{normalized}"]
    if "*" in normalized:
        return any(list(REPO_ROOT.glob(candidate)) for candidate in candidates)
    return any((REPO_ROOT / candidate).exists() for candidate in candidates)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "docs_root",
        nargs="?",
        default=str(DEFAULT_DOC_ROOT),
        help="Documentation directory to scan.",
    )
    args = parser.parse_args()

    docs_root = Path(args.docs_root)
    if not docs_root.is_absolute():
        docs_root = REPO_ROOT / docs_root
    failures: list[tuple[Path, str]] = []

    for doc in sorted(docs_root.rglob("*.md")):
        text = doc.read_text(encoding="utf-8")
        for path_text in sorted(_candidate_paths(text)):
            if not _exists(path_text):
                failures.append((doc.relative_to(REPO_ROOT), path_text))

    if failures:
        for doc, path_text in failures:
            print(f"{doc}: missing source path `{path_text}`", file=sys.stderr)
        return 1
    print(f"Checked docs source paths under {docs_root.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
