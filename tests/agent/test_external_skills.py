"""Tests for external skill directories (skills.external_dirs config)."""

import json
import os
from unittest.mock import patch

import pytest


@pytest.fixture
def external_skills_dir(tmp_path):
    """Create a temp dir with a sample external skill."""
    ext_dir = tmp_path / "external-skills"
    skill_dir = ext_dir / "my-external-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: my-external-skill\ndescription: A skill from an external directory\n---\n\n# My External Skill\n\nDo external things.\n"
    )
    return ext_dir


@pytest.fixture
def spark_home(tmp_path):
    """Create a minimal SPARK_HOME with config."""
    home = tmp_path / ".spark"
    home.mkdir()
    (home / "skills").mkdir()
    return home


class TestGetExternalSkillsDirs:
    def test_empty_config(self, spark_home):
        (spark_home / "config.yaml").write_text("skills:\n  external_dirs: []\n")
        with patch.dict(os.environ, {"SPARK_HOME": str(spark_home)}):
            from agent.skill_utils import get_external_skills_dirs
            result = get_external_skills_dirs()
        assert result == []

    def test_nonexistent_dir_skipped(self, spark_home):
        (spark_home / "config.yaml").write_text(
            "skills:\n  external_dirs:\n    - /nonexistent/path\n"
        )
        with patch.dict(os.environ, {"SPARK_HOME": str(spark_home)}):
            from agent.skill_utils import get_external_skills_dirs
            result = get_external_skills_dirs()
        assert result == []

    def test_valid_dir_returned(self, spark_home, external_skills_dir):
        (spark_home / "config.yaml").write_text(
            f"skills:\n  external_dirs:\n    - {external_skills_dir}\n"
        )
        with patch.dict(os.environ, {"SPARK_HOME": str(spark_home)}):
            from agent.skill_utils import get_external_skills_dirs
            result = get_external_skills_dirs()
        assert len(result) == 1
        assert result[0] == external_skills_dir.resolve()

    def test_duplicate_dirs_deduplicated(self, spark_home, external_skills_dir):
        (spark_home / "config.yaml").write_text(
            f"skills:\n  external_dirs:\n    - {external_skills_dir}\n    - {external_skills_dir}\n"
        )
        with patch.dict(os.environ, {"SPARK_HOME": str(spark_home)}):
            from agent.skill_utils import get_external_skills_dirs
            result = get_external_skills_dirs()
        assert len(result) == 1

    def test_local_skills_dir_excluded(self, spark_home):
        local_skills = spark_home / "skills"
        (spark_home / "config.yaml").write_text(
            f"skills:\n  external_dirs:\n    - {local_skills}\n"
        )
        with patch.dict(os.environ, {"SPARK_HOME": str(spark_home)}):
            from agent.skill_utils import get_external_skills_dirs
            result = get_external_skills_dirs()
        assert result == []

    def test_no_config_file(self, spark_home):
        # No config.yaml at all
        with patch.dict(os.environ, {"SPARK_HOME": str(spark_home)}):
            from agent.skill_utils import get_external_skills_dirs
            result = get_external_skills_dirs()
        assert result == []

    def test_string_value_converted_to_list(self, spark_home, external_skills_dir):
        (spark_home / "config.yaml").write_text(
            f"skills:\n  external_dirs: {external_skills_dir}\n"
        )
        with patch.dict(os.environ, {"SPARK_HOME": str(spark_home)}):
            from agent.skill_utils import get_external_skills_dirs
            result = get_external_skills_dirs()
        assert len(result) == 1


class TestGetAllSkillsDirs:
    def test_local_always_first(self, spark_home, external_skills_dir):
        (spark_home / "config.yaml").write_text(
            f"skills:\n  external_dirs:\n    - {external_skills_dir}\n"
        )
        with patch.dict(os.environ, {"SPARK_HOME": str(spark_home)}):
            from agent.skill_utils import get_all_skills_dirs
            result = get_all_skills_dirs()
        assert result[0] == spark_home / "skills"
        assert result[1] == external_skills_dir.resolve()


class TestExternalSkillsInFindAll:
    def test_external_skills_found(self, spark_home, external_skills_dir):
        (spark_home / "config.yaml").write_text(
            f"skills:\n  external_dirs:\n    - {external_skills_dir}\n"
        )
        local_skills = spark_home / "skills"
        with (
            patch.dict(os.environ, {"SPARK_HOME": str(spark_home)}),
            patch("tools.skills_tool.SKILLS_DIR", local_skills),
        ):
            from tools.skills_tool import _find_all_skills
            skills = _find_all_skills()
        names = [s["name"] for s in skills]
        assert "my-external-skill" in names

    def test_local_takes_precedence(self, spark_home, external_skills_dir):
        """If the same skill name exists locally and externally, local wins."""
        local_skills = spark_home / "skills"
        local_skill = local_skills / "my-external-skill"
        local_skill.mkdir(parents=True)
        (local_skill / "SKILL.md").write_text(
            "---\nname: my-external-skill\ndescription: Local version\n---\n\nLocal.\n"
        )
        (spark_home / "config.yaml").write_text(
            f"skills:\n  external_dirs:\n    - {external_skills_dir}\n"
        )
        with (
            patch.dict(os.environ, {"SPARK_HOME": str(spark_home)}),
            patch("tools.skills_tool.SKILLS_DIR", local_skills),
        ):
            from tools.skills_tool import _find_all_skills
            skills = _find_all_skills()
        matching = [s for s in skills if s["name"] == "my-external-skill"]
        assert len(matching) == 1
        assert matching[0]["description"] == "Local version"


class TestExternalSkillView:
    def test_skill_view_finds_external(self, spark_home, external_skills_dir):
        (spark_home / "config.yaml").write_text(
            f"skills:\n  external_dirs:\n    - {external_skills_dir}\n"
        )
        local_skills = spark_home / "skills"
        with (
            patch.dict(os.environ, {"SPARK_HOME": str(spark_home)}),
            patch("tools.skills_tool.SKILLS_DIR", local_skills),
        ):
            from tools.skills_tool import skill_view
            result = json.loads(skill_view("my-external-skill"))
        assert result["success"] is True
        assert "external things" in result["content"]

    def test_external_view_reports_provenance_and_root_supporting_files(
        self, spark_home, external_skills_dir
    ):
        (external_skills_dir / "my-external-skill" / "GUIDE.md").write_text(
            "Supporting instructions."
        )
        (spark_home / "config.yaml").write_text(
            f"skills:\n  external_dirs:\n    - {external_skills_dir}\n"
        )
        local_skills = spark_home / "skills"
        with (
            patch.dict(os.environ, {"SPARK_HOME": str(spark_home)}),
            patch("tools.skills_tool.SKILLS_DIR", local_skills),
        ):
            from tools.skills_tool import skill_view

            result = json.loads(skill_view("my-external-skill"))
            supporting = result["linked_files"]["supporting"]
            guide = json.loads(skill_view("my-external-skill", "GUIDE.md"))

        assert result["provenance"] == "external"
        assert result["capabilities"]["editable"] is False
        assert result["capabilities"]["removal_mode"] == "detach"
        assert "GUIDE.md" in supporting
        assert guide["success"] is True
        assert guide["content"] == "Supporting instructions."

    def test_external_skills_are_discoverable_without_local_profile_directory(
        self, spark_home, external_skills_dir, tmp_path
    ):
        model_skill = external_skills_dir / "model-skill"
        model_skill.mkdir()
        (model_skill / "SKILL.md").write_text(
            "---\nname: model-skill\ndescription: Model-visible\n---\n"
        )
        user_skill = external_skills_dir / "user-only"
        user_skill.mkdir()
        (user_skill / "SKILL.md").write_text(
            "---\nname: user-only\ndescription: User slash only\n"
            "disable-model-invocation: true\n---\n"
        )
        (spark_home / "config.yaml").write_text(
            f"skills:\n  external_dirs:\n    - {external_skills_dir}\n"
        )
        missing_local = tmp_path / "profile-skills-not-created"
        with (
            patch.dict(os.environ, {"SPARK_HOME": str(spark_home)}),
            patch("tools.skills_tool.SKILLS_DIR", missing_local),
        ):
            from tools.skills_tool import skills_list

            result = json.loads(skills_list())

        names = {skill["name"] for skill in result["skills"]}
        assert "model-skill" in names
        assert "user-only" not in names

    def test_external_skill_can_be_disabled_then_detached_without_editing_source(
        self, spark_home, external_skills_dir, monkeypatch, tmp_path
    ):
        skill_dir = external_skills_dir / "my-external-skill"
        missing_local = tmp_path / "profile-skills-not-created"
        config_path = spark_home / "config.yaml"

        config_path.write_text(
            f"skills:\n  external_dirs:\n    - {external_skills_dir}\n  disabled: []\n"
        )
        with (
            patch.dict(os.environ, {"SPARK_HOME": str(spark_home)}),
            patch("tools.skills_tool.SKILLS_DIR", missing_local),
        ):
            from agent.skill_commands import scan_skill_commands

            assert "/my-external-skill" in scan_skill_commands()

            config_path.write_text(
                f"skills:\n  external_dirs:\n    - {external_skills_dir}\n"
                "  disabled:\n    - my-external-skill\n"
            )
            assert "/my-external-skill" not in scan_skill_commands()

            # Detaching removes only the configured root from discovery.  The
            # externally installed source remains untouched on disk.
            config_path.write_text("skills:\n  external_dirs: []\n  disabled: []\n")
            assert "/my-external-skill" not in scan_skill_commands()

        assert (skill_dir / "SKILL.md").exists()
