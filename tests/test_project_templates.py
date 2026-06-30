"""Tests for project starter templates and the create_project route."""

from __future__ import annotations

import shutil

import pytest
from fastapi import HTTPException

from spark_cli import project_templates as pt
from spark_cli.workspace_routes import ProjectCreate, create_project, list_project_templates


def test_list_templates_includes_all_ids():
    ids = {t.id for t in pt.list_templates()}
    assert ids == {
        "scratch",
        "static",
        "webapp",
        "productivity",
        "astro",
        "eleventy",
        "nextjs",
        "sveltekit",
        "nuxt",
        "docs_workspace",
        "research_workspace",
        "knowledge_base",
        "design_system",
        "brand_kit",
        "hyperframes",
        "remotion",
        "ffmpeg",
    }


def test_template_metadata_groups_supported_starters():
    templates = {t.id: t for t in pt.list_templates()}
    assert templates["webapp"].project_type == "web_application"
    assert templates["webapp"].recommended is True
    assert templates["webapp"].available is True
    assert "react" in templates["webapp"].recommended_skills
    assert templates["nextjs"].available is True
    assert templates["design_system"].project_type == "design_project"
    assert templates["design_system"].recommended is True
    assert "frontend-design" in templates["design_system"].recommended_skills


def test_all_non_scratch_templates_materialize_files(tmp_path):
    for template in pt.list_templates():
        if template.id == "scratch":
            continue
        target = tmp_path / template.id
        target.mkdir()
        written = pt.materialize_template(template.id, target)
        assert written, template.id
        assert all((target / rel).exists() for rel in written)


def test_project_templates_route_returns_wizard_metadata():
    result = list_project_templates()
    assert {group["id"] for group in result["project_types"]} >= {
        "blank",
        "static_website",
        "web_application",
        "design_project",
        "productivity_workspace",
        "video_project",
    }
    webapp = next(template for template in result["templates"] if template["id"] == "webapp")
    assert webapp["project_type"] == "web_application"
    assert webapp["recommended"] is True
    assert webapp["available"] is True
    assert "recommended_skills" in webapp


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
    assert "gws-docs" in readme


def test_design_system_materializes_design_workspace(tmp_path):
    written = pt.materialize_template("design_system", tmp_path)
    assert "design/brief.md" in written
    assert "design/tokens.json" in written
    assert "design/components.md" in written
    assert "index.html" in written
    assert (tmp_path / "design" / "tokens.json").is_file()
    assert "frontend-design" in pt.get_template("design_system").recommended_skills


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
    assert pt.is_valid_template("nextjs")
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


def test_create_project_accepts_wizard_payload():
    result = create_project(
        ProjectCreate(
            name="wizard web app",
            project_type="web_application",
            starter_stack="webapp",
            package_manager="pnpm",
            init_git=False,
            ai_skills_mode="recommended",
            dev_tools=["prettier", "vscode_config"],
            integrations=["docker"],
        )
    )
    assert result["ok"] is True
    assert result["template"] == "webapp"
    assert result["starter_stack"] == "webapp"
    assert result["project_type"] == "web_application"
    assert "project_metadata" in result["applied_options"]
    assert "ai_skills" in result["applied_options"]
    assert "prettier" in result["applied_options"]
    assert "vscode_config" in result["applied_options"]
    assert "docker" in result["applied_options"]

    from spark_cli.workspace_routes import _workspace_root

    proj = _workspace_root() / result["slug"]
    assert (proj / ".spark-project.json").is_file()
    agents = (proj / "AGENTS.md").read_text()
    assert "`react`" in agents
    assert "`typescript`" in agents
    assert (proj / ".prettierrc").is_file()
    assert (proj / ".vscode" / "settings.json").is_file()
    assert (proj / "Dockerfile").is_file()


def test_create_project_accepts_new_starter_stack():
    result = create_project(
        ProjectCreate(
            name="next app",
            project_type="web_application",
            starter_stack="nextjs",
            init_git=False,
        )
    )
    assert result["template"] == "nextjs"

    from spark_cli.workspace_routes import _workspace_root

    proj = _workspace_root() / result["slug"]
    assert (proj / "app" / "page.tsx").is_file()


def test_create_project_accepts_design_project_options():
    result = create_project(
        ProjectCreate(
            name="design lab",
            project_type="design_project",
            starter_stack="design_system",
            init_git=False,
            dev_tools=["design_tokens", "brand_kit", "figma_notes"],
            integrations=["figma"],
        )
    )
    assert result["template"] == "design_system"
    assert result["project_type"] == "design_project"
    assert "design_tokens" in result["applied_options"]
    assert "brand_kit" in result["applied_options"]
    assert "figma_notes" in result["applied_options"]

    from spark_cli.workspace_routes import _workspace_root

    proj = _workspace_root() / result["slug"]
    assert (proj / "design" / "tokens.json").is_file()
    assert (proj / "brand" / "kit.md").is_file()
    assert (proj / "design" / "figma-handoff.md").is_file()
    agents = (proj / "AGENTS.md").read_text()
    assert "`frontend-design`" in agents
    assert "`figma`" in agents


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_create_project_can_initialize_git_with_commit():
    result = create_project(
        ProjectCreate(
            name="git project",
            starter_stack="static",
            project_type="static_website",
            init_git=True,
            initial_commit=True,
        )
    )
    assert "init_git" in result["applied_options"]
    assert "initial_commit" in result["applied_options"]

    from spark_cli.workspace_routes import _workspace_root

    proj = _workspace_root() / result["slug"]
    assert (proj / ".git").is_dir()
