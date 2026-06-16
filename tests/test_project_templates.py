"""Tests for project starter templates and the create_project route."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from spark_cli import project_templates as pt
from spark_cli.workspace_routes import ProjectCreate, create_project


def test_list_templates_includes_all_ids():
    ids = {t.id for t in pt.list_templates()}
    assert ids == {"scratch", "static", "webapp", "productivity"}


def test_scratch_materializes_no_files(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    written = pt.materialize_template("scratch", target)
    assert written == []
    assert list(target.iterdir()) == []


def test_static_materializes_expected_files(tmp_path):
    written = pt.materialize_template("static", tmp_path)
    assert set(written) == {"index.html", "styles.css", "app.js"}
    assert (tmp_path / "index.html").read_text().strip().startswith("<!doctype html>")
    assert "tailwindcss" in (tmp_path / "index.html").read_text()


def test_webapp_materializes_nested_files(tmp_path):
    written = pt.materialize_template("webapp", tmp_path)
    assert "package.json" in written
    assert "src/main.tsx" in written
    assert "src/components/ui/button.tsx" in written
    assert "src/App.test.tsx" in written
    # nested dirs created
    assert (tmp_path / "src" / "components" / "ui" / "button.tsx").is_file()
    pkg = (tmp_path / "package.json").read_text()
    assert "@tanstack/react-router" in pkg
    assert "vitest" in pkg


def test_productivity_materializes_readme_and_notes(tmp_path):
    written = pt.materialize_template("productivity", tmp_path)
    assert set(written) == {"README.md", "NOTES.md"}
    readme = (tmp_path / "README.md").read_text()
    assert "skill" in readme.lower()
    assert "Phase 4" in readme


def test_materialize_unknown_raises(tmp_path):
    with pytest.raises(KeyError):
        pt.materialize_template("nope", tmp_path)


def test_materialize_does_not_overwrite(tmp_path):
    (tmp_path / "app.js").write_text("KEEP ME")
    written = pt.materialize_template("static", tmp_path)
    assert "app.js" not in written
    assert (tmp_path / "app.js").read_text() == "KEEP ME"


def test_is_valid_template():
    assert pt.is_valid_template("webapp")
    assert not pt.is_valid_template("bogus")


# ── Route-level tests ────────────────────────────────────────────────────────


def test_create_project_scaffolds_static(monkeypatch, tmp_path):
    # SPARK_HOME is already redirected to a temp dir by the autouse fixture;
    # workspace root lives under it.
    result = create_project(ProjectCreate(name="my static site", template="static"))
    assert result["ok"] is True
    assert result["template"] == "static"
    from spark_cli.workspace_routes import _workspace_root

    proj = _workspace_root() / result["slug"]
    assert (proj / "index.html").is_file()
    assert (proj / "app.js").is_file()


def test_create_project_default_is_scratch(monkeypatch, tmp_path):
    result = create_project(ProjectCreate(name="empty proj"))
    assert result["template"] == "scratch"
    from spark_cli.workspace_routes import _workspace_root

    proj = _workspace_root() / result["slug"]
    assert proj.is_dir()
    assert list(proj.iterdir()) == []


def test_create_project_rejects_unknown_template():
    with pytest.raises(HTTPException) as exc:
        create_project(ProjectCreate(name="bad", template="nonsense"))
    assert exc.value.status_code == 400
    assert "template" in str(exc.value.detail).lower()
