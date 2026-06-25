from pathlib import Path
from unittest.mock import patch


def test_issue_skill_is_discoverable_as_slash_command():
    import agent.skill_commands as skill_commands

    repo_skills = Path(__file__).resolve().parents[2] / "skills"
    skill_commands._skill_commands = {}
    with patch("tools.skills_tool.SKILLS_DIR", repo_skills):
        commands = skill_commands.scan_skill_commands()

    assert "/issue" in commands
    assert commands["/issue"]["name"] == "issue"
    assert "GitHub issue" in commands["/issue"]["description"]
