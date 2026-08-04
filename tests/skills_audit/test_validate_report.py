"""Validation contract for the SKILL-02 evidence report."""

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[2]
REPORT = ROOT / "docs/skills/2026-08-04-skill-02-engineering-overlap-audit.json"
SCHEMA = ROOT / "docs/skills/skill-audit.schema.json"
VALIDATOR = ROOT / "scripts/validate_skill_audit_report.py"


def test_report_is_json_and_matches_checked_in_shape():
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    schema_version = schema["$id"].rsplit("/", 1)[-1].replace(".json", "")
    assert report["schema_version"] == schema_version
    assert report["audit"]["id"] == "SKILL-02"
    assert {row["decision"] for row in report["skills"]} == {
        "keep-external", "improve-bundled", "merge-bundled", "archive-bundled"
    }
    assert len({(row["name"], row["source_kind"]) for row in report["skills"]}) == len(
        report["skills"]
    )


def test_validator_accepts_report():
    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(REPORT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
