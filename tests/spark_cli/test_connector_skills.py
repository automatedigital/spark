"""Tests for connector-to-skill and toolset grants."""

from spark_cli.connector_skills import grant_for


def test_grant_for_merges_declared_and_configured_skills():
    result = grant_for("github", ("github-auth", "custom-github-skill"))

    assert result["skills"][0:2] == ["github-auth", "custom-github-skill"]
    assert result["skills"].count("github-auth") == 1
    assert "github-pr-workflow" in result["skills"]
    assert result["toolsets"] == []


def test_grant_for_includes_cli_toolset():
    result = grant_for("codex")

    assert result == {"skills": ["codex"], "toolsets": ["delegation"]}


def test_grant_for_unknown_connector_uses_declared_skills():
    assert grant_for("unknown-test-connector", ["one", "one", "two"]) == {
        "skills": ["one", "two"],
        "toolsets": [],
    }
