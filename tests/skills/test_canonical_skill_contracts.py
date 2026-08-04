"""Focused contracts for SKILL-07's canonical overlap decisions."""

from pathlib import Path

from agent.skill_utils import parse_frontmatter

ROOT = Path(__file__).parents[2]


def _frontmatter(relative_path: str) -> dict:
    content = (ROOT / relative_path).read_text(encoding="utf-8")
    frontmatter, _ = parse_frontmatter(content)
    return frontmatter


def _spark_metadata(relative_path: str) -> dict:
    return _frontmatter(relative_path)["metadata"]["spark"]


def test_canonical_overlaps_have_one_owner_and_explicit_alternatives():
    canonical = {
        "systematic-debugging": (
            "skills/software-development/systematic-debugging/SKILL.md",
            "diagnosing-bugs",
        ),
        "test-driven-development": (
            "skills/software-development/test-driven-development/SKILL.md",
            "tdd",
        ),
        "writing-plans": (
            "skills/software-development/writing-plans/SKILL.md",
            "wayfinder",
        ),
        "requesting-code-review": (
            "skills/software-development/requesting-code-review/SKILL.md",
            "code-review",
        ),
        "github-code-review": (
            "skills/github/github-code-review/SKILL.md",
            "code-review",
        ),
        "subagent-driven-development": (
            "skills/software-development/subagent-driven-development/SKILL.md",
            "handoff",
        ),
    }

    for name, (path, alternative) in canonical.items():
        metadata = _spark_metadata(path)
        assert metadata["canonical"] is True, name
        assert alternative in metadata["external_alternatives"], name


def test_plan_is_a_mode_alias_of_writing_plans():
    writing_metadata = _spark_metadata(
        "skills/software-development/writing-plans/SKILL.md"
    )
    plan_metadata = _spark_metadata("skills/software-development/plan/SKILL.md")

    assert "plan" in writing_metadata["aliases"]
    assert plan_metadata["canonical_skill"] == "writing-plans"
    assert plan_metadata["alias_of"] == "writing-plans"


def test_provider_adapters_point_to_the_canonical_dispatcher():
    for provider in ("claude-code", "codex", "opencode"):
        metadata = _spark_metadata(f"skills/autonomous-ai-agents/{provider}/SKILL.md")
        assert "subagent-driven-development" in metadata["related_skills"], provider


def test_canonical_content_contains_the_new_boundaries():
    debugging = (
        ROOT / "skills/software-development/systematic-debugging/SKILL.md"
    ).read_text()
    tdd = (
        ROOT / "skills/software-development/test-driven-development/SKILL.md"
    ).read_text()

    assert "deterministic, red-capable feedback loop" in debugging
    assert "one fast, unattended command" in debugging
    assert "public seam" in tdd
    assert "vertical slice" in tdd
