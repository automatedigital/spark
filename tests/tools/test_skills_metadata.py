"""Contract tests for profile-safe skill provenance and bundled tombstones."""

from pathlib import Path

from core.spark_constants import get_spark_home


def _write_skill(root: Path, name: str, description: str = "A test skill") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\nInstructions for {name}.\n",
        encoding="utf-8",
    )
    return skill_dir


def test_resolver_keeps_duplicate_names_distinct(monkeypatch, tmp_path):
    local = get_spark_home() / "skills"
    external = tmp_path / "external"
    _write_skill(local, "collision")
    _write_skill(external, "collision", "External copy")

    import agent.skill_utils as skill_utils
    from tools.skills_metadata import iter_skill_records

    monkeypatch.setattr(skill_utils, "get_external_skills_dirs", lambda: [external])
    rows = [row for row in iter_skill_records() if row["name"] == "collision"]

    assert len(rows) == 2
    assert {row["provenance"] for row in rows} == {"local", "external"}
    assert len({row["skill_id"] for row in rows}) == 2
    assert all("/" not in row["skill_id"] for row in rows)
    assert next(row for row in rows if row["provenance"] == "external")["capabilities"]["editable"] is False


def test_bundled_tombstone_survives_sync_and_restore(monkeypatch, tmp_path):
    bundled = tmp_path / "bundled"
    source = _write_skill(bundled, "bundled-demo")
    profile_skills = get_spark_home() / "skills"

    import tools.skills_sync as sync

    monkeypatch.setattr(sync, "SKILLS_DIR", profile_skills)
    monkeypatch.setattr(sync, "MANIFEST_FILE", profile_skills / ".bundled_manifest")
    monkeypatch.setattr(sync, "TOMBSTONE_FILE", profile_skills / ".bundled_tombstones")
    monkeypatch.setattr(sync, "_get_bundled_dir", lambda: bundled)

    first = sync.sync_skills(quiet=True)
    assert "bundled-demo" in first["copied"]
    destination = profile_skills / "bundled-demo"
    assert destination.exists()

    assert sync.tombstone_bundled_skill("bundled-demo")["success"]
    assert not destination.exists()
    sync.sync_skills(quiet=True)
    assert not destination.exists()

    assert sync.restore_bundled_skill("bundled-demo")["success"]
    assert destination.exists()
    assert "bundled-demo" not in sync._read_tombstones()
    assert (destination / "SKILL.md").read_text(encoding="utf-8") == (source / "SKILL.md").read_text(encoding="utf-8")


def test_stale_manifest_does_not_promote_unrelated_local_skill(monkeypatch):
    local = get_spark_home() / "skills"
    _write_skill(local, "stale-entry")
    (local / ".bundled_manifest").write_text("stale-entry:old-hash\n", encoding="utf-8")

    from tools.skills_metadata import iter_skill_records

    row = next(item for item in iter_skill_records() if item["name"] == "stale-entry")
    assert row["provenance"] == "local"
