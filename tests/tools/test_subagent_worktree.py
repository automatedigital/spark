"""Exercise worktree ownership against real temporary Git repositories."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from core.spark_constants import get_spark_home
from tools.subagent_worktree import (
    WorktreeIsolationError,
    cleanup_subagent_worktree,
    create_subagent_worktree,
    finish_subagent_worktree,
    get_subagent_worktree,
)


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


@pytest.fixture
def repo(tmp_path):
    directory = tmp_path / "parent repo"
    directory.mkdir()
    git(directory, "init", "-q")
    git(directory, "config", "user.email", "fixture@example.invalid")
    git(directory, "config", "user.name", "Fixture")
    (directory / "same.txt").write_text("committed baseline\n")
    git(directory, "add", "same.txt")
    git(directory, "commit", "-qm", "fixture baseline")
    return directory


def test_parallel_children_get_committed_baseline_without_changing_parent(repo):
    (repo / "same.txt").write_text("parent unsaved work\n")
    (repo / "untracked.txt").write_text("parent only")
    git(repo, "add", "same.txt")
    original_status = git(repo, "status", "--porcelain")
    first = create_subagent_worktree(repo, "child-one")
    second = create_subagent_worktree(repo, "child-two")
    assert first.path != second.path
    for record in (first, second):
        assert (Path(record.path) / "same.txt").read_text() == "committed baseline\n"
        assert not (Path(record.path) / "untracked.txt").exists()
        assert git(record.path, "rev-parse", "HEAD") == record.base_commit
    (Path(first.path) / "same.txt").write_text("first child")
    (Path(second.path) / "same.txt").write_text("second child")
    assert (repo / "same.txt").read_text() == "parent unsaved work\n"
    assert git(repo, "status", "--porcelain") == original_status
    assert get_subagent_worktree("child-one") == first


def test_cleanup_requires_terminal_and_clean_and_preserves_commit(repo):
    record = create_subagent_worktree(repo, "clean-child")
    assert cleanup_subagent_worktree(record.run_id)["reason"] == "active"
    finish_subagent_worktree(record.run_id)
    result = cleanup_subagent_worktree(record.run_id)
    assert result["removed"] is True
    assert not Path(record.path).exists()
    assert get_subagent_worktree(record.run_id) is None
    assert git(repo, "rev-parse", record.branch) == record.base_commit

    record = create_subagent_worktree(repo, "committed-child")
    (Path(record.path) / "same.txt").write_text("useful child work")
    git(record.path, "commit", "-qam", "child result")
    finish_subagent_worktree(record.run_id)
    assert cleanup_subagent_worktree(record.run_id)["reason"] == "committed"
    assert Path(record.path).exists()


def test_cleanup_preserves_dirty_ignored_and_changed_branch(repo):
    record = create_subagent_worktree(repo, "dirty-child")
    (Path(record.path) / "precious.txt").write_text("untracked result")
    finish_subagent_worktree(record.run_id)
    assert cleanup_subagent_worktree(record.run_id)["reason"] == "dirty"
    (Path(record.path) / "precious.txt").unlink()
    git(record.path, "switch", "-qc", "feat/other-child-work")
    assert cleanup_subagent_worktree(record.run_id)["reason"] == "branch_changed"
    assert Path(record.path).exists()


def test_unsupported_backend_and_invalid_identity_do_not_fall_back(repo):
    before = git(repo, "worktree", "list", "--porcelain")
    for backend in ("ssh", "docker", "modal"):
        with pytest.raises(WorktreeIsolationError, match="unsupported"):
            create_subagent_worktree(repo, "remote-child", backend=backend)
    for identifier in ("../escape", "-option", "child/branch", "", "x" * 100):
        with pytest.raises(WorktreeIsolationError, match="run ID"):
            create_subagent_worktree(repo, identifier)
    with pytest.raises(WorktreeIsolationError, match="hexadecimal"):
        create_subagent_worktree(repo, "bad-commit", base_commit="--upload-pack=unsafe")
    assert git(repo, "worktree", "list", "--porcelain") == before


def test_collision_does_not_overwrite_existing_checkout_or_branch(repo):
    record = create_subagent_worktree(repo, "existing")
    (Path(record.path) / "result").write_text("retain")
    with pytest.raises(WorktreeIsolationError, match="already exists"):
        create_subagent_worktree(repo, "existing")
    assert (Path(record.path) / "result").read_text() == "retain"
    git(repo, "branch", "feat/subagent-collision")
    with pytest.raises(WorktreeIsolationError):
        create_subagent_worktree(repo, "collision")
    assert not (get_spark_home() / "subagent-worktrees/checkouts/collision").exists()


def test_setup_failure_and_success_record_actual_child_directory(repo):
    with pytest.raises(WorktreeIsolationError, match="Setup failed; worktree retained"):
        create_subagent_worktree(repo, "failed-setup", setup_commands=[
            [sys.executable, "-c", "from pathlib import Path; Path('setup-evidence').write_text('kept'); raise SystemExit(7)"]
        ])
    failed = get_subagent_worktree("failed-setup")
    assert failed.setup_status == "failed"
    assert failed.active is False
    assert (Path(failed.path) / "setup-evidence").read_text() == "kept"
    assert cleanup_subagent_worktree(failed.run_id)["reason"] == "dirty"

    good = create_subagent_worktree(repo, "good-setup", setup_commands=[
        [sys.executable, "-c", "from pathlib import Path; Path('setup-result').write_text(str(Path.cwd()))"]
    ])
    assert good.setup_status == "completed"
    assert (Path(good.path) / "setup-result").read_text() == good.path
    assert not (repo / "setup-result").exists()


def test_cleanup_retains_on_inspection_failure_or_metadata_mismatch(repo):
    record = create_subagent_worktree(repo, "inspect-child")
    finish_subagent_worktree(record.run_id)
    git(repo, "worktree", "lock", record.path)
    assert cleanup_subagent_worktree(record.run_id)["reason"] == "inspection_failed"
    assert Path(record.path).exists()
    target = get_spark_home() / "subagent-worktrees/inspect-child.json"
    value = json.loads(target.read_text())
    value["path"] = str(repo)
    target.write_text(json.dumps(value))
    assert cleanup_subagent_worktree(record.run_id)["reason"] == "ownership_mismatch"
    assert (repo / "same.txt").exists()


def test_profile_boundaries_and_non_git_fail_explicitly(repo, tmp_path, monkeypatch):
    record = create_subagent_worktree(repo, "profile-child")
    monkeypatch.setenv("SPARK_HOME", str(tmp_path / "other-profile"))
    assert get_subagent_worktree(record.run_id) is None
    plain = tmp_path / "not-git"
    plain.mkdir()
    with pytest.raises(WorktreeIsolationError):
        create_subagent_worktree(plain, "not-git-child")
