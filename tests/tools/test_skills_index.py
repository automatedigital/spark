"""SP22 discovery must stay bounded and must not run skill setup."""
from pathlib import Path

import pytest

from tools import skills_index, skills_metadata


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    root.mkdir()
    monkeypatch.setattr(skills_metadata, "_roots", lambda: [("local", root)])
    monkeypatch.setattr(skills_metadata, "_load_quality_artifacts", lambda: ({}, {}))
    monkeypatch.setattr(skills_metadata, "_provenance", lambda *args: ("local", None, None))
    skills_index._cache.clear()
    return root


def write_skill(root: Path, name="example", extra="", body="instructions"):
    directory = root / name
    directory.mkdir(exist_ok=True)
    path = directory / "SKILL.md"
    path.write_text(f"---\nname: {name}\ndescription: Short description\n{extra}---\n{body}")
    return path


def test_thousand_skills_never_read_bodies(catalog, monkeypatch):
    for number in range(1000):
        write_skill(catalog, f"skill-{number}", body="BODY" * 10000)
    original_open = Path.open
    reads = []

    class HeaderOnly:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.stream.close()
        def readline(self, size):
            reads.append(size)
            return self.stream.readline(size)

    def guarded_open(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        return HeaderOnly(stream) if path.name == "SKILL.md" else stream

    monkeypatch.setattr(Path, "open", guarded_open)
    rows = skills_index.list_skill_index()
    assert len(rows) == 1000
    assert all("content" not in row and row.get("supporting_file_count") is None for row in rows)
    assert max(reads) <= skills_index.HEADER_LIMIT + 1
    reads.clear()
    assert len(skills_index.list_skill_index(query="skill-999")) == 1
    assert reads == []


def test_external_edit_replacement_deletion_and_refresh(catalog):
    path = write_skill(catalog)
    first = skills_index.list_skill_index()[0]
    path.write_text(path.read_text().replace("Short description", "Changed description"))
    second = skills_index.list_skill_index()[0]
    assert second["description"] == "Changed description"
    assert second["skill_id"] == first["skill_id"]
    assert skills_index.list_skill_index(refresh=True)[0] == second
    path.unlink()
    assert skills_index.list_skill_index() == []


def test_requirements_are_presence_only_and_rechecked(catalog, monkeypatch):
    write_skill(catalog, extra="required_environment_variables: [SP22_SYNTHETIC_SECRET]\nmetadata:\n  spark:\n    requires_tools: [optional-tool]\n")
    monkeypatch.delenv("SP22_SYNTHETIC_SECRET", raising=False)
    row = skills_index.list_skill_index()[0]
    assert row["readiness"] == "missing_requirements"
    monkeypatch.setenv("SP22_SYNTHETIC_SECRET", "never-return-this-value")
    row = skills_index.list_skill_index()[0]
    assert row["readiness"] == "unknown"
    assert "never-return-this-value" not in str(row)
    from spark_cli import skills_config
    monkeypatch.setattr(skills_config, "get_disabled_skills", lambda _: {"example"})
    assert skills_index.list_skill_index()[0]["readiness"] == "disabled"


def test_collision_identity_and_scope(catalog, tmp_path, monkeypatch):
    external = tmp_path / "external"
    external.mkdir()
    write_skill(catalog)
    write_skill(external)
    monkeypatch.setattr(skills_metadata, "_roots", lambda: [("local", catalog), ("external", external)])
    rows = skills_index.list_skill_index()
    assert len({row["skill_id"] for row in rows}) == 2
    assert {row["scope"] for row in rows} == {"profile", "external"}
    assert all(row["duplicate_warning"] for row in rows)
    assert len(skills_index.list_skill_index(scope="profile")) == 1


def test_oversized_header_is_unknown_and_external_link_not_indexed(catalog, tmp_path):
    path = write_skill(catalog)
    path.write_text("---\ndescription: " + "x" * 20000 + "\n---\nbody")
    assert skills_index.read_header(path) == ""
    outside = tmp_path / "outside"
    outside.mkdir()
    write_skill(outside)
    (catalog / "escape").symlink_to(outside / "example", target_is_directory=True)
    assert len(skills_index.list_skill_index()) == 1


def test_cache_fences_root_role_and_profile(catalog, monkeypatch, tmp_path):
    write_skill(catalog)
    first = skills_index.list_skill_index()[0]
    monkeypatch.setattr(skills_metadata, "_roots", lambda: [("external", catalog)])
    monkeypatch.setattr(skills_metadata, "_provenance", lambda *args: ("external", None, None))
    monkeypatch.setenv("SPARK_HOME", str(tmp_path / "second-profile"))
    second = skills_index.list_skill_index()[0]
    assert first["skill_id"] != second["skill_id"]
    assert second["provenance"] == "external"
