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
    assert all(row["duplicate_warning"] == "Duplicate skill name across: external_installed, profile_local" for row in rows)


def test_quality_metadata_uses_checked_in_artifacts_without_machine_paths(monkeypatch, tmp_path):
    external = tmp_path / "external"
    _write_skill(external, "wayfinder", "Maps the next decision.")
    (external / "wayfinder" / "SKILL.md").write_text(
        "---\nname: wayfinder\ndescription: Maps the next decision.\n"
        "disable-model-invocation: true\n---\n\nRun directly.\n",
        encoding="utf-8",
    )
    (external / "wayfinder" / "references").mkdir()
    (external / "wayfinder" / "references" / "notes.md").write_text("supporting", encoding="utf-8")

    import agent.skill_utils as skill_utils
    from tools.skills_metadata import iter_skill_records

    monkeypatch.setattr(skill_utils, "get_external_skills_dirs", lambda: [external])
    row = next(item for item in iter_skill_records() if item["name"] == "wayfinder")

    assert row["provenance"] == "external"
    assert row["source"] == "external_installed"
    assert row["invocation_type"] == "user_invoked"
    assert row["index_token_cost"] == 0
    assert row["supporting_file_count"] == 1
    assert row["eval_status"] == "fixture-only"
    assert row["eval_date"] == "2026-08-04"
    assert "writing-plans" in (row["overlap_warning"] or "")
    assert "/Users/" not in str(row)


def test_duplicate_source_audit_entries_select_by_runtime_provenance(tmp_path):
    from tools.skills_metadata import _quality_metadata

    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    artifacts = (
        {
            "grill-with-docs": [
                {
                    "source_kind": "external_installed",
                    "overlaps": ["external-overlap"],
                    "eval_coverage": {"runtime": []},
                    "_audit_date": "2026-08-04",
                },
                {
                    "source_kind": "spark_bundled",
                    "overlaps": ["bundled-overlap"],
                    "eval_coverage": {"runtime": ["tests/example.py"]},
                    "_audit_date": "2026-08-04",
                },
            ]
        },
        {"grill-with-docs": ("fixture-only", "2026-08-04")},
    )
    frontmatter = {
        "name": "grill-with-docs",
        "description": "Ask better questions.",
    }

    external = _quality_metadata(
        "grill-with-docs", frontmatter, "external", skill_dir, artifacts=artifacts
    )
    bundled = _quality_metadata(
        "grill-with-docs", frontmatter, "bundled", skill_dir, artifacts=artifacts
    )

    assert external["source"] == "external_installed"
    assert external["overlap_warnings"] == ["external-overlap"]
    assert bundled["source"] == "spark_bundled"
    assert bundled["overlap_warnings"] == ["bundled-overlap"]
    assert bundled["eval_status"] == "fixture-only"


def test_inventory_loads_quality_artifacts_once(monkeypatch):
    import tools.skills_metadata as metadata

    original = metadata._load_quality_artifacts
    calls = 0

    def counted_load():
        nonlocal calls
        calls += 1
        return original()

    monkeypatch.setattr(metadata, "_load_quality_artifacts", counted_load)
    metadata.iter_skill_records()

    assert calls == 1


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
