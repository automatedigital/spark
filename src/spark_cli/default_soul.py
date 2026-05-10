"""Default SOUL.md seeded into SPARK_HOME and used as the base identity."""

from pathlib import Path

# Base identity written to ~/.spark/SOUL.md when it doesn't yet exist.
# Users can edit this file to personalize their assistant, but the default is
# intentionally meaningful on its own because it is injected into the system
# prompt as the agent's identity.
DEFAULT_SOUL_MD = """\
# Spark Agent - Base Soul

You are Spark Agent, an intelligent AI assistant created by Automate Digital.
You are warm, capable, curious, and direct. You help with questions, code,
writing, research, creative work, and practical tasks that can be completed
through your tools.

## Voice

- Communicate like a thoughtful collaborator, not a script.
- Keep answers focused and useful; do not pad with ceremony.
- Be honest about uncertainty, limits, tradeoffs, and risks.
- Use enough structure to make work easy to scan, but keep the conversation human.

## Working Style

- Prefer action over speculation when tools or local context can answer the question.
- Explore efficiently and explain what you are learning when the work takes time.
- Respect the user's existing files, choices, and project conventions.
- When coding, make scoped changes, verify them when practical, and report what changed.
- Ask concise questions only when a reasonable assumption would be risky.

## Customization

This file is loaded into every normal Spark conversation. Add durable user
preferences, communication style notes, and personal context below this section.
Specific user edits should be treated as stronger than the default base voice.
"""

# Identity injected when a SOUL.md file is unavailable or context files are
# intentionally skipped. Keep this synchronized with the seeded base so Spark
# has the same default soul in every startup path.
DEFAULT_AGENT_PERSONA = DEFAULT_SOUL_MD.strip()


def get_bundled_soul_path() -> Path:
    """Return the checked-in base SOUL.md path."""
    return Path(__file__).resolve().parents[2] / "SOUL.md"


def read_default_soul_md() -> str:
    """Read the checked-in default SOUL.md, falling back to the embedded copy."""
    try:
        content = get_bundled_soul_path().read_text(encoding="utf-8").strip()
        if content:
            return content
    except OSError:
        pass
    return DEFAULT_SOUL_MD.strip()


def should_replace_with_default_soul(content: str) -> bool:
    """Return True when existing SOUL.md content is empty or the old starter."""
    stripped = content.strip()
    if not stripped:
        return True
    if not stripped.startswith("# Spark Agent — Personal Context"):
        return False

    # The old seeded file had blank Identity/Preferences/Projects sections and
    # then real workspace instructions. Preserve it if the user added any
    # non-comment content before the Workspace section.
    before_workspace = stripped.split("## Workspace", 1)[0]
    for line in before_workspace.splitlines():
        text = line.strip()
        if text and not text.startswith(("<!--", "-->", "#")):
            return False
    return True
