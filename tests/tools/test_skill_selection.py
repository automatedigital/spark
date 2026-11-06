from pathlib import Path
from unittest.mock import patch

import pytest

from agent.skill_commands import build_selected_skill_message
from tools import skills_index, skills_metadata


def skill(root, body="INSTRUCTION", name="collision"):
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Test\nsetup: touch forbidden\n---\n{body}")
    return directory


def test_project_collision_selected_body_only_and_no_setup(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    project = tmp_path / "project"
    skill(profile, "PROFILE")
    selected_dir = skill(project / ".agents/skills", "PROJECT")
    monkeypatch.setattr(skills_metadata, "get_skills_dir", lambda: profile)
    monkeypatch.setattr(skills_metadata, "_external_dirs", lambda: [])
    monkeypatch.setattr(skills_metadata, "_load_quality_artifacts", lambda: ({}, {}))
    rows = skills_index.list_skill_index(project_root=project)
    assert {r["scope"] for r in rows} == {"profile", "project"}
    assert len({r["skill_id"] for r in rows}) == 2
    row = next(r for r in rows if r["scope"] == "project")
    assert row["location"].startswith("project://")
    assert row["provenance_detail"]["source"] == "project"
    original = Path.read_text

    def selected_only(path, *args, **kwargs):
        if path.name == "SKILL.md":
            assert path == selected_dir / "SKILL.md"
        return original(path, *args, **kwargs)

    with patch.object(Path, "read_text", selected_only), patch("tools.skills_tool.skill_view", side_effect=AssertionError("setup path")), patch("agent.skill_commands._inject_skill_config", side_effect=AssertionError("secret path")):
        message = build_selected_skill_message(row["skill_id"], row["revision"], project_root=project)
    assert "PROJECT" in message and "PROFILE" not in message
    assert str(selected_dir.resolve()) in message
    assert not (tmp_path / "forbidden").exists()
    with pytest.raises(ValueError):
        build_selected_skill_message(row["skill_id"], row["revision"])
    (selected_dir / "SKILL.md").write_text("changed")
    with pytest.raises(ValueError):
        build_selected_skill_message(row["skill_id"], row["revision"], project_root=project)


def test_project_escape_not_discovered(tmp_path, monkeypatch):
    project = tmp_path / "project"
    (project / ".agents").mkdir(parents=True)
    outside = tmp_path / "outside"
    skill(outside)
    (project / ".agents/skills").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(skills_metadata, "get_skills_dir", lambda: tmp_path / "empty")
    monkeypatch.setattr(skills_metadata, "_external_dirs", lambda: [])
    assert skills_index.list_skill_index(project_root=project) == []


def test_removed_builtin_remains_discoverable_beside_name_collision(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    profile.mkdir()
    bundled = tmp_path / "bundled"
    skill(bundled)
    external = tmp_path / "external"
    skill(external)
    monkeypatch.setattr(skills_metadata, "get_skills_dir", lambda: profile)
    monkeypatch.setattr(skills_metadata, "_external_dirs", lambda: [external])
    monkeypatch.setattr(skills_metadata, "_bundled_root", lambda: bundled)
    monkeypatch.setattr(skills_metadata, "_tombstones", lambda: {"collision"})
    rows = skills_index.list_skill_index()
    assert len(rows) == 2
    removed = next(row for row in rows if row.get("removed"))
    assert removed["capabilities"]["restorable"]
    assert removed["skill_id"] != next(row for row in rows if not row.get("removed"))["skill_id"]
