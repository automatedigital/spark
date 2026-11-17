"""Guard the conservative fallback and exact-checkout diff used by Python CI."""

import subprocess
import sys

import pytest

from scripts.select_python_ci import changed_paths, main, select_scope


@pytest.mark.parametrize(
    ("paths", "scope"),
    [
        (["docs/README.md", "src/spark_cli/web/src/App.tsx"], "smoke"),
        (["src/cron/jobs.py", "src/spark_cli/web/src/App.tsx", "tests/cron/test_jobs.py"], "cron"),
        (["src/spark_cli/cron_output_routes.py", "src/spark_cli/web/e2e/cron-outputs.mjs"], "cron"),
        (["src/tools/artifact_store.py", "tests/tools/test_artifact_store.py"], "artifacts"),
        (["src/tools/fuzzy_match.py", "tests/tools/test_fuzzy_match.py"], "file-tools"),
        (["src/cron/jobs.py", "src/tools/artifact_store.py"], "full"),
        (["src/cron/jobs.py", "src/core/spark_state.py"], "full"),
        (["src/cron/jobs.py", "tests/conftest.py"], "full"),
        (["src/cron/jobs.py", "scripts/new_module.py"], "full"),
        ([".github/workflows/python-quality.yml"], "full"),
        (["src/spark_cli/web/package-lock.json"], "full"),
        (["pyproject.toml"], "full"),
        ([], "full"),
    ],
)
def test_scope_selection(paths, scope):
    assert select_scope(paths) == scope


def test_scopes_exact_merge_diff_and_sees_both_sides_of_renames(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def git(*args):
        return subprocess.check_output(
            ["git", "-c", "user.name=CI test", "-c", "user.email=ci@example.invalid", *args],
            text=True,
        ).strip()

    git("init", "-b", "main")
    (tmp_path / "shared.py").write_text("value = 1\n", encoding="utf-8")
    git("add", "shared.py")
    git("commit", "-m", "base")
    base = git("rev-parse", "HEAD")

    git("switch", "-c", "feature")
    destination = tmp_path / "src/cron/jobs.py"
    destination.parent.mkdir(parents=True)
    git("mv", "shared.py", str(destination))
    git("commit", "-m", "move shared file into cron")

    git("switch", "main")
    git("merge", "--no-ff", "feature", "-m", "merge fixture")
    shallow = tmp_path / "shallow"
    git("clone", "--depth=2", tmp_path.as_uri(), str(shallow))
    monkeypatch.chdir(shallow)

    paths = changed_paths(base)
    assert set(paths) == {"shared.py", "src/cron/jobs.py"}
    assert select_scope(paths) == "full"
    with pytest.raises(ValueError, match="does not match its base"):
        changed_paths("0" * 40)


@pytest.mark.parametrize("base", ["", "0" * 40])
def test_workflow_output_defaults_to_full_without_a_verified_diff(tmp_path, monkeypatch, base):
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "github-output"
    monkeypatch.setattr(sys, "argv", ["select_python_ci.py", "--base", base, "--output", str(output)])

    main()

    assert output.read_text(encoding="utf-8").splitlines() == ["scope=full", "targets="]
