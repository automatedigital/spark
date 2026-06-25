#!/usr/bin/env python3
"""Seed a synthetic heavy Spark web session for renderer stress testing."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from core.spark_state import SessionDB  # noqa: E402


def build_markdown_blocks() -> str:
    sections: list[str] = ["# Synthetic Heavy Renderer Session\n"]
    for i in range(80):
        sections.append(
            f"## Section {i}\n\n"
            "This paragraph intentionally contains **bold text**, `inline code`, "
            "[a link](https://example.com), and enough words to make wrapping and "
            "virtualized row measurement do real work across many blocks.\n"
        )
    return "\n\n".join(sections)


def build_long_paragraph() -> str:
    return " ".join(
        f"long-paragraph-token-{i}" for i in range(6500)
    )


def build_code_blocks() -> str:
    blocks: list[str] = []
    for i in range(20):
        code = "\n".join(f"def function_{i}_{j}(): return {i + j}" for j in range(80))
        blocks.append(f"```python\n{code}\n```")
    return "\n\n".join(blocks)


def build_table() -> str:
    rows = ["| metric | value | note |", "|---|---:|---|"]
    for i in range(300):
        rows.append(f"| row {i} | {i * 17} | repeated table data for layout testing |")
    return "\n".join(rows)


def build_reasoning() -> str:
    return "\n".join(
        f"Reasoning line {i}: this is diagnostic text that should stay collapsed by default."
        for i in range(1200)
    )


def build_tool_output(name: str) -> str:
    lines = [f"{name} output line {i}: {'x' * 120}" for i in range(1800)]
    return "\n".join(lines)


def seed(session_id: str, history_turns: int = 0) -> None:
    db = SessionDB()
    try:
        db.create_session(session_id, source="web", model="synthetic/heavy")
        for i in range(history_turns):
            db.append_message(session_id, "user", content=f"Earlier synthetic prompt {i}")
            db.append_message(session_id, "assistant", content=f"Earlier synthetic answer {i}")
        db.append_message(session_id, "user", content="Create a renderer stress-test response.")
        db.append_message(
            session_id,
            "assistant",
            content="\n\n".join(
                [
                    build_markdown_blocks(),
                    build_long_paragraph(),
                    build_code_blocks(),
                    build_table(),
                ]
            ),
            reasoning=build_reasoning(),
        )
        for i in range(5):
            db.append_message(
                session_id,
                "tool",
                content=build_tool_output(f"synthetic_tool_{i}"),
                tool_name=f"synthetic_tool_{i}",
                tool_call_id=f"synthetic_tool_call_{i}",
            )
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-id", default="synthetic_heavy_web_session")
    parser.add_argument(
        "--history-turns",
        type=int,
        default=0,
        help="Add this many earlier user/assistant turns so the UI can exercise prepending history.",
    )
    args = parser.parse_args()
    seed(args.session_id, max(0, args.history_turns))
    print(args.session_id)


if __name__ == "__main__":
    main()
