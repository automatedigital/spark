#!/usr/bin/env python3
"""Validate the checked-in SKILL-02 audit report without third-party packages."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import NoReturn


DECISIONS = {"keep-external", "improve-bundled", "merge-bundled", "archive-bundled"}
SOURCES = {"external_installed", "spark_bundled", "codex_bundled"}
REQUIRED_SKILL_FIELDS = {
    "name", "capability", "source_kind", "source_path", "trigger", "steps",
    "references", "completion_criteria", "invocation", "size", "usage",
    "provenance", "license", "eval_coverage", "overlaps", "decision", "rationale",
}


def fail(message: str) -> NoReturn:
    raise ValueError(message)


def validate(report: dict) -> None:
    if report.get("schema_version") != "skill-audit.v1":
        fail("schema_version must be skill-audit.v1")
    audit = report.get("audit")
    if not isinstance(audit, dict):
        fail("audit must be an object")
    for key in ("id", "date", "branch", "base_commit", "scope", "read_only_roots"):
        if key not in audit:
            fail(f"audit.{key} is required")
    if audit["id"] != "SKILL-02":
        fail("audit.id must be SKILL-02")
    try:
        date.fromisoformat(audit["date"])
    except (TypeError, ValueError) as exc:
        fail(f"audit.date is not ISO date: {exc}")
    measurement = report.get("measurement")
    if not isinstance(measurement, dict):
        fail("measurement must be an object")
    for key in (
        "byte_definition", "index_definition", "token_estimator", "usage_source",
        "content_eval_status",
    ):
        if not measurement.get(key):
            fail(f"measurement.{key} is required")

    skills = report.get("skills")
    if not isinstance(skills, list) or not skills:
        fail("skills must be a non-empty array")
    identities: set[tuple[str, str]] = set()
    decisions: set[str] = set()
    for index, skill in enumerate(skills):
        if not isinstance(skill, dict):
            fail(f"skills[{index}] must be an object")
        missing = REQUIRED_SKILL_FIELDS - skill.keys()
        if missing:
            fail(f"skills[{index}] missing {sorted(missing)}")
        name = skill["name"]
        identity = (name, skill["source_kind"])
        if not isinstance(name, str) or not name or identity in identities:
            fail(f"skills[{index}] has a missing or duplicate name")
        identities.add(identity)
        if skill["source_kind"] not in SOURCES:
            fail(f"skills[{index}].source_kind is invalid")
        if skill["decision"] not in DECISIONS:
            fail(f"skills[{index}].decision is invalid")
        decisions.add(skill["decision"])
        for key in ("steps", "references", "completion_criteria", "overlaps"):
            if not isinstance(skill[key], list):
                fail(f"skills[{index}].{key} must be an array")
        invocation = skill["invocation"]
        if invocation.get("policy") not in {"user_invoked", "model_invoked", "both"}:
            fail(f"skills[{index}].invocation.policy is invalid")
        if not isinstance(invocation.get("user_invocable"), bool) or not isinstance(
            invocation.get("model_invocable"), bool
        ):
            fail(f"skills[{index}].invocation booleans are required")
        size = skill["size"]
        for key in (
            "skill_md_bytes", "skill_md_lines", "index_entry_bytes",
            "estimated_index_tokens",
        ):
            if not isinstance(size.get(key), int) or size[key] < 0:
                fail(f"skills[{index}].size.{key} must be a non-negative integer")
        if not isinstance(skill["eval_coverage"].get("runtime"), list):
            fail(f"skills[{index}].eval_coverage.runtime must be an array")
    if decisions != DECISIONS:
        fail(f"report must exercise all four decisions; got {sorted(decisions)}")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} REPORT.json", file=sys.stderr)
        return 2
    path = Path(argv[1])
    try:
        validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"invalid skill audit report: {exc}", file=sys.stderr)
        return 1
    print(f"valid skill audit report: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
