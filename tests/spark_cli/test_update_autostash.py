from pathlib import Path
from subprocess import CalledProcessError
from types import SimpleNamespace

import pytest
from spark_cli import config as spark_config
from spark_cli import main as spark_main


def test_stash_local_changes_if_needed_returns_none_when_tree_clean(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[-2:] == ["status", "--porcelain"]:
            return SimpleNamespace(stdout="", returncode=0)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(spark_main.subprocess, "run", fake_run)

    stash_ref = spark_main._stash_local_changes_if_needed(["git"], tmp_path)

    assert stash_ref is None
    assert [cmd[-2:] for cmd, _ in calls] == [["status", "--porcelain"]]


def test_stash_local_changes_if_needed_returns_specific_stash_commit(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[-2:] == ["status", "--porcelain"]:
            return SimpleNamespace(stdout=" M spark_cli/main.py\n?? notes.txt\n", returncode=0)
        if cmd[-2:] == ["ls-files", "--unmerged"]:
            return SimpleNamespace(stdout="", returncode=0)
        if cmd[1:4] == ["stash", "push", "--include-untracked"]:
            return SimpleNamespace(stdout="Saved working directory\n", returncode=0)
        if cmd[-3:] == ["rev-parse", "--verify", "refs/stash"]:
            return SimpleNamespace(stdout="abc123\n", returncode=0)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(spark_main.subprocess, "run", fake_run)

    stash_ref = spark_main._stash_local_changes_if_needed(["git"], tmp_path)

    assert stash_ref == "abc123"
    assert calls[1][0][-2:] == ["ls-files", "--unmerged"]
    assert calls[2][0][1:4] == ["stash", "push", "--include-untracked"]
    assert calls[3][0][-3:] == ["rev-parse", "--verify", "refs/stash"]


def test_resolve_stash_selector_returns_matching_entry(monkeypatch, tmp_path):
    def fake_run(cmd, **kwargs):
        assert cmd == ["git", "stash", "list", "--format=%gd %H"]
        return SimpleNamespace(
            stdout="stash@{0} def456\nstash@{1} abc123\n",
            returncode=0,
        )

    monkeypatch.setattr(spark_main.subprocess, "run", fake_run)

    assert spark_main._resolve_stash_selector(["git"], tmp_path, "abc123") == "stash@{1}"



def test_restore_stashed_changes_prompts_before_applying(monkeypatch, tmp_path, capsys):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[1:3] == ["stash", "apply"]:
            return SimpleNamespace(stdout="applied\n", stderr="", returncode=0)
        if cmd[1:3] == ["diff", "--name-only"]:
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        if cmd[1:3] == ["stash", "list"]:
            return SimpleNamespace(stdout="stash@{1} abc123\n", stderr="", returncode=0)
        if cmd[1:3] == ["stash", "drop"]:
            return SimpleNamespace(stdout="dropped\n", stderr="", returncode=0)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(spark_main.subprocess, "run", fake_run)
    monkeypatch.setattr("builtins.input", lambda: "")

    restored = spark_main._restore_stashed_changes(["git"], tmp_path, "abc123", prompt_user=True)

    assert restored is True
    assert calls[0][0] == ["git", "stash", "apply", "abc123"]
    assert calls[1][0] == ["git", "diff", "--name-only", "--diff-filter=U"]
    assert calls[2][0] == ["git", "stash", "list", "--format=%gd %H"]
    assert calls[3][0] == ["git", "stash", "drop", "stash@{1}"]
    out = capsys.readouterr().out
    assert "Restore local changes now? [Y/n]" in out
    assert "restored on top of the updated codebase" in out
    assert "git diff" in out
    assert "git status" in out


def test_restore_stashed_changes_can_skip_restore_and_keep_stash(monkeypatch, tmp_path, capsys):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(spark_main.subprocess, "run", fake_run)
    monkeypatch.setattr("builtins.input", lambda: "n")

    restored = spark_main._restore_stashed_changes(["git"], tmp_path, "abc123", prompt_user=True)

    assert restored is False
    assert calls == []
    out = capsys.readouterr().out
    assert "Restore local changes now? [Y/n]" in out
    assert "Your changes are still preserved in git stash." in out
    assert "git stash apply abc123" in out


def test_restore_stashed_changes_applies_without_prompt_when_disabled(monkeypatch, tmp_path, capsys):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[1:3] == ["stash", "apply"]:
            return SimpleNamespace(stdout="applied\n", stderr="", returncode=0)
        if cmd[1:3] == ["diff", "--name-only"]:
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        if cmd[1:3] == ["stash", "list"]:
            return SimpleNamespace(stdout="stash@{0} abc123\n", stderr="", returncode=0)
        if cmd[1:3] == ["stash", "drop"]:
            return SimpleNamespace(stdout="dropped\n", stderr="", returncode=0)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(spark_main.subprocess, "run", fake_run)

    restored = spark_main._restore_stashed_changes(["git"], tmp_path, "abc123", prompt_user=False)

    assert restored is True
    assert calls[0][0] == ["git", "stash", "apply", "abc123"]
    assert calls[1][0] == ["git", "diff", "--name-only", "--diff-filter=U"]
    assert calls[2][0] == ["git", "stash", "list", "--format=%gd %H"]
    assert calls[3][0] == ["git", "stash", "drop", "stash@{0}"]
    assert "Restore local changes now?" not in capsys.readouterr().out


def test_reset_generated_web_assets_restores_tracked_bundle_and_cleans_untracked(tmp_path):
    repo = tmp_path
    subprocess = spark_main.subprocess
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)

    web_dist = repo / "src" / "spark_cli" / "web_dist"
    assets = web_dist / "assets"
    assets.mkdir(parents=True)
    index = web_dist / "index.html"
    bundle = assets / "index-new.js"
    index.write_text('<script src="/assets/index-new.js"></script>', encoding="utf-8")
    bundle.write_text("new", encoding="utf-8")
    subprocess.run(["git", "add", "src/spark_cli/web_dist"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "bundle"], cwd=repo, check=True, capture_output=True)

    index.write_text('<script src="/assets/index-old.js"></script>', encoding="utf-8")
    (assets / "index-old.js").write_text("old", encoding="utf-8")

    assert spark_main._reset_generated_web_assets(["git"], repo) is True
    assert index.read_text(encoding="utf-8") == '<script src="/assets/index-new.js"></script>'
    assert bundle.read_text(encoding="utf-8") == "new"
    assert not (assets / "index-old.js").exists()


def test_stash_discards_generated_changes_but_preserves_real_edits(tmp_path):
    repo = tmp_path
    subprocess = spark_main.subprocess
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)

    web_dist = repo / "src" / "spark_cli" / "web_dist"
    web_dist.mkdir(parents=True)
    generated = web_dist / "index.html"
    source = repo / "source.py"
    generated.write_text("current bundle", encoding="utf-8")
    source.write_text("current source", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True)

    generated.write_text("stale bundle", encoding="utf-8")
    source.write_text("local source edit", encoding="utf-8")

    stash_ref = spark_main._stash_local_changes_if_needed(["git"], repo)

    assert stash_ref
    assert generated.read_text(encoding="utf-8") == "current bundle"
    assert source.read_text(encoding="utf-8") == "current source"
    stashed_paths = subprocess.run(
        ["git", "stash", "show", "--name-only", stash_ref],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert "source.py" in stashed_paths
    assert "src/spark_cli/web_dist/index.html" not in stashed_paths


def test_stash_recovers_from_unmerged_generated_web_asset(tmp_path):
    repo = tmp_path
    subprocess = spark_main.subprocess
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)

    web_dist = repo / "src" / "spark_cli" / "web_dist"
    web_dist.mkdir(parents=True)
    index = web_dist / "index.html"
    index.write_text("base bundle", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)

    subprocess.run(["git", "checkout", "-b", "incoming"], cwd=repo, check=True, capture_output=True)
    index.write_text("incoming bundle", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "incoming"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True)
    index.write_text("local bundle", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "local"], cwd=repo, check=True, capture_output=True)
    merge = subprocess.run(
        ["git", "merge", "incoming"], cwd=repo, capture_output=True, text=True
    )
    assert merge.returncode != 0
    assert subprocess.run(
        ["git", "ls-files", "--unmerged"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    stash_ref = spark_main._stash_local_changes_if_needed(["git"], repo)

    assert stash_ref is None
    assert index.read_text(encoding="utf-8") == "local bundle"
    assert not subprocess.run(
        ["git", "ls-files", "--unmerged"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout



def test_print_stash_cleanup_guidance_with_selector(capsys):
    spark_main._print_stash_cleanup_guidance("abc123", "stash@{2}")

    out = capsys.readouterr().out
    assert "Check `git status` first" in out
    assert "git stash list --format='%gd %H %s'" in out
    assert "git stash drop stash@{2}" in out



def test_restore_stashed_changes_keeps_going_when_stash_entry_cannot_be_resolved(monkeypatch, tmp_path, capsys):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[1:3] == ["stash", "apply"]:
            return SimpleNamespace(stdout="applied\n", stderr="", returncode=0)
        if cmd[1:3] == ["diff", "--name-only"]:
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        if cmd[1:3] == ["stash", "list"]:
            return SimpleNamespace(stdout="stash@{0} def456\n", stderr="", returncode=0)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(spark_main.subprocess, "run", fake_run)

    restored = spark_main._restore_stashed_changes(["git"], tmp_path, "abc123", prompt_user=False)

    assert restored is True
    assert calls[0] == (["git", "stash", "apply", "abc123"], {"cwd": tmp_path, "capture_output": True, "text": True})
    assert calls[1] == (["git", "diff", "--name-only", "--diff-filter=U"], {"cwd": tmp_path, "capture_output": True, "text": True})
    assert calls[2] == (["git", "stash", "list", "--format=%gd %H"], {"cwd": tmp_path, "capture_output": True, "text": True, "check": True})
    out = capsys.readouterr().out
    assert "couldn't find the stash entry to drop" in out
    assert "stash was left in place" in out
    assert "Check `git status` first" in out
    assert "git stash list --format='%gd %H %s'" in out
    assert "Look for commit abc123" in out



def test_restore_stashed_changes_keeps_going_when_drop_fails(monkeypatch, tmp_path, capsys):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[1:3] == ["stash", "apply"]:
            return SimpleNamespace(stdout="applied\n", stderr="", returncode=0)
        if cmd[1:3] == ["diff", "--name-only"]:
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        if cmd[1:3] == ["stash", "list"]:
            return SimpleNamespace(stdout="stash@{0} abc123\n", stderr="", returncode=0)
        if cmd[1:3] == ["stash", "drop"]:
            return SimpleNamespace(stdout="", stderr="drop failed\n", returncode=1)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(spark_main.subprocess, "run", fake_run)

    restored = spark_main._restore_stashed_changes(["git"], tmp_path, "abc123", prompt_user=False)

    assert restored is True
    assert calls[3][0] == ["git", "stash", "drop", "stash@{0}"]
    out = capsys.readouterr().out
    assert "couldn't drop the saved stash entry" in out
    assert "drop failed" in out
    assert "Check `git status` first" in out
    assert "git stash list --format='%gd %H %s'" in out
    assert "git stash drop stash@{0}" in out


def test_restore_stashed_changes_always_resets_on_conflict(monkeypatch, tmp_path, capsys):
    """Conflicts always auto-reset (no prompt) and return False, even interactively.

    Leaving conflict markers in source files makes spark unrunnable (SyntaxError).
    The stash is preserved for manual recovery; cmd_update continues normally.
    """
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[1:3] == ["stash", "apply"]:
            return SimpleNamespace(stdout="conflict output\n", stderr="conflict stderr\n", returncode=1)
        if cmd[1:3] == ["diff", "--name-only"]:
            return SimpleNamespace(stdout="spark_cli/main.py\n", stderr="", returncode=0)
        if cmd[1:3] == ["reset", "--hard"]:
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(spark_main.subprocess, "run", fake_run)
    monkeypatch.setattr("builtins.input", lambda: "y")

    result = spark_main._restore_stashed_changes(["git"], tmp_path, "abc123", prompt_user=True)

    assert result is False
    out = capsys.readouterr().out
    assert "Conflicted files:" in out
    assert "spark_cli/main.py" in out
    assert "stashed changes are preserved" in out
    assert "Working tree reset to clean state" in out
    assert "git stash apply abc123" in out
    reset_calls = [c for c, _ in calls if c[1:3] == ["reset", "--hard"]]
    assert len(reset_calls) == 1


def test_restore_stashed_changes_auto_resets_non_interactive(monkeypatch, tmp_path, capsys):
    """Non-interactive mode auto-resets without prompting and returns False
    instead of sys.exit(1) so the update can continue (gateway /update path)."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[1:3] == ["stash", "apply"]:
            return SimpleNamespace(stdout="applied\n", stderr="", returncode=0)
        if cmd[1:3] == ["diff", "--name-only"]:
            return SimpleNamespace(stdout="core.cli.py\n", stderr="", returncode=0)
        if cmd[1:3] == ["reset", "--hard"]:
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(spark_main.subprocess, "run", fake_run)

    result = spark_main._restore_stashed_changes(["git"], tmp_path, "abc123", prompt_user=False)

    assert result is False
    out = capsys.readouterr().out
    assert "Working tree reset to clean state" in out
    reset_calls = [c for c, _ in calls if c[1:3] == ["reset", "--hard"]]
    assert len(reset_calls) == 1


def test_stash_local_changes_if_needed_raises_when_stash_ref_missing(monkeypatch, tmp_path):
    def fake_run(cmd, **kwargs):
        if cmd[-2:] == ["status", "--porcelain"]:
            return SimpleNamespace(stdout=" M spark_cli/main.py\n", returncode=0)
        if cmd[-2:] == ["ls-files", "--unmerged"]:
            return SimpleNamespace(stdout="", returncode=0)
        if cmd[1:4] == ["stash", "push", "--include-untracked"]:
            return SimpleNamespace(stdout="Saved working directory\n", returncode=0)
        if cmd[-3:] == ["rev-parse", "--verify", "refs/stash"]:
            raise CalledProcessError(returncode=128, cmd=cmd)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(spark_main.subprocess, "run", fake_run)

    with pytest.raises(CalledProcessError):
        spark_main._stash_local_changes_if_needed(["git"], Path(tmp_path))


# ---------------------------------------------------------------------------
# Update uses .[all] with fallback to .
# ---------------------------------------------------------------------------

def _setup_update_mocks(monkeypatch, tmp_path):
    """Common setup for cmd_update tests."""
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(spark_main, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(spark_main, "_stash_local_changes_if_needed", lambda *a, **kw: None)
    monkeypatch.setattr(spark_main, "_restore_stashed_changes", lambda *a, **kw: True)
    monkeypatch.setattr(spark_config, "get_missing_env_vars", lambda required_only=True: [])
    monkeypatch.setattr(spark_config, "get_missing_config_fields", lambda: [])
    monkeypatch.setattr(spark_config, "check_config_version", lambda: (5, 5))
    monkeypatch.setattr(spark_config, "migrate_config", lambda **kw: {"env_added": [], "config_added": []})


def test_cmd_update_retries_optional_extras_individually_when_all_fails(monkeypatch, tmp_path, capsys):
    """When .[all] fails, update should keep base deps and retry extras individually."""
    _setup_update_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/uv" if name == "uv" else None)
    monkeypatch.setattr(spark_main, "_load_installable_optional_extras", lambda: ["matrix", "mcp"])

    recorded = []

    def fake_run(cmd, **kwargs):
        recorded.append(cmd)
        if cmd == ["git", "fetch", "origin"]:
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        if cmd == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return SimpleNamespace(stdout="main\n", stderr="", returncode=0)
        if cmd == ["git", "rev-list", "HEAD..origin/main", "--count"]:
            return SimpleNamespace(stdout="1\n", stderr="", returncode=0)
        if cmd == ["git", "pull", "origin", "main"]:
            return SimpleNamespace(stdout="Updating\n", stderr="", returncode=0)
        if cmd == ["/usr/bin/uv", "pip", "install", "-e", ".[all]", "--quiet"]:
            raise CalledProcessError(returncode=1, cmd=cmd)
        if cmd == ["/usr/bin/uv", "pip", "install", "-e", ".", "--quiet"]:
            return SimpleNamespace(returncode=0)
        if cmd == ["/usr/bin/uv", "pip", "install", "-e", ".[matrix]", "--quiet"]:
            raise CalledProcessError(returncode=1, cmd=cmd)
        if cmd == ["/usr/bin/uv", "pip", "install", "-e", ".[mcp]", "--quiet"]:
            return SimpleNamespace(returncode=0)
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(spark_main.subprocess, "run", fake_run)

    spark_main.cmd_update(SimpleNamespace())

    install_cmds = [c for c in recorded if "pip" in c and "install" in c]
    assert install_cmds == [
        ["/usr/bin/uv", "pip", "install", "-e", ".[all]", "--quiet"],
        ["/usr/bin/uv", "pip", "install", "-e", ".", "--quiet"],
        ["/usr/bin/uv", "pip", "install", "-e", ".[matrix]", "--quiet"],
        ["/usr/bin/uv", "pip", "install", "-e", ".[mcp]", "--quiet"],
    ]

    out = capsys.readouterr().out
    assert "retrying extras individually" in out
    assert "Reinstalled optional extras individually: mcp" in out
    assert "Skipped optional extras that still failed: matrix" in out


def test_cmd_update_succeeds_with_extras(monkeypatch, tmp_path):
    """When .[all] succeeds, no fallback should be attempted."""
    _setup_update_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/uv" if name == "uv" else None)

    recorded = []

    def fake_run(cmd, **kwargs):
        recorded.append(cmd)
        if cmd == ["git", "fetch", "origin"]:
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        if cmd == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return SimpleNamespace(stdout="main\n", stderr="", returncode=0)
        if cmd == ["git", "rev-list", "HEAD..origin/main", "--count"]:
            return SimpleNamespace(stdout="1\n", stderr="", returncode=0)
        if cmd == ["git", "pull", "origin", "main"]:
            return SimpleNamespace(stdout="Updating\n", stderr="", returncode=0)
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(spark_main.subprocess, "run", fake_run)

    spark_main.cmd_update(SimpleNamespace())

    install_cmds = [c for c in recorded if "pip" in c and "install" in c]
    assert len(install_cmds) == 1
    assert ".[all]" in install_cmds[0]


# ---------------------------------------------------------------------------
# ff-only fallback to reset --hard on diverged history
# ---------------------------------------------------------------------------

def _make_update_side_effect(
    current_branch="main",
    commit_count="3",
    ff_only_fails=False,
    reset_fails=False,
    fetch_fails=False,
    fetch_stderr="",
):
    """Build a subprocess.run side_effect for cmd_update tests."""
    recorded = []

    def side_effect(cmd, **kwargs):
        recorded.append(cmd)
        joined = " ".join(str(c) for c in cmd)
        if "fetch" in joined and "origin" in joined:
            if fetch_fails:
                return SimpleNamespace(stdout="", stderr=fetch_stderr, returncode=128)
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        if "rev-parse" in joined and "--abbrev-ref" in joined:
            return SimpleNamespace(stdout=f"{current_branch}\n", stderr="", returncode=0)
        if "checkout" in joined and "main" in joined:
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        if "rev-list" in joined:
            return SimpleNamespace(stdout=f"{commit_count}\n", stderr="", returncode=0)
        if "--ff-only" in joined:
            if ff_only_fails:
                return SimpleNamespace(
                    stdout="",
                    stderr="fatal: Not possible to fast-forward, aborting.\n",
                    returncode=128,
                )
            return SimpleNamespace(stdout="Updating abc..def\n", stderr="", returncode=0)
        if "reset" in joined and "--hard" in joined:
            if reset_fails:
                return SimpleNamespace(stdout="", stderr="error: unable to write\n", returncode=1)
            return SimpleNamespace(stdout="HEAD is now at abc123\n", stderr="", returncode=0)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return side_effect, recorded


def test_cmd_update_falls_back_to_reset_when_ff_only_fails(monkeypatch, tmp_path, capsys):
    """When --ff-only fails (diverged history), update resets to origin/{branch}."""
    _setup_update_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/uv" if name == "uv" else None)

    side_effect, recorded = _make_update_side_effect(ff_only_fails=True)
    monkeypatch.setattr(spark_main.subprocess, "run", side_effect)

    spark_main.cmd_update(SimpleNamespace())

    reset_calls = [c for c in recorded if "reset" in c and "--hard" in c]
    assert len(reset_calls) == 1
    assert reset_calls[0] == ["git", "reset", "--hard", "origin/main"]

    out = capsys.readouterr().out
    assert "Fast-forward not possible" in out


def test_cmd_update_no_reset_when_ff_only_succeeds(monkeypatch, tmp_path):
    """When --ff-only succeeds, no reset is attempted."""
    _setup_update_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/uv" if name == "uv" else None)

    side_effect, recorded = _make_update_side_effect()
    monkeypatch.setattr(spark_main.subprocess, "run", side_effect)

    spark_main.cmd_update(SimpleNamespace())

    reset_calls = [c for c in recorded if "reset" in c and "--hard" in c]
    assert len(reset_calls) == 0


# ---------------------------------------------------------------------------
# Non-main branch → auto-checkout main
# ---------------------------------------------------------------------------

def test_cmd_update_switches_to_main_from_feature_branch(monkeypatch, tmp_path, capsys):
    """When on a feature branch, update checks out main before pulling."""
    _setup_update_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/uv" if name == "uv" else None)

    side_effect, recorded = _make_update_side_effect(current_branch="fix/something")
    monkeypatch.setattr(spark_main.subprocess, "run", side_effect)

    spark_main.cmd_update(SimpleNamespace())

    checkout_calls = [c for c in recorded if "checkout" in c and "main" in c]
    assert len(checkout_calls) == 1

    out = capsys.readouterr().out
    assert "fix/something" in out
    assert "switching to main" in out


def test_cmd_update_switches_to_main_from_detached_head(monkeypatch, tmp_path, capsys):
    """When in detached HEAD state, update checks out main before pulling."""
    _setup_update_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/uv" if name == "uv" else None)

    side_effect, recorded = _make_update_side_effect(current_branch="HEAD")
    monkeypatch.setattr(spark_main.subprocess, "run", side_effect)

    spark_main.cmd_update(SimpleNamespace())

    checkout_calls = [c for c in recorded if "checkout" in c and "main" in c]
    assert len(checkout_calls) == 1

    out = capsys.readouterr().out
    assert "detached HEAD" in out


def test_cmd_update_restores_stash_and_branch_when_already_up_to_date(monkeypatch, tmp_path, capsys):
    """When on a feature branch with no updates, stash is restored and branch switched back."""
    _setup_update_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/uv" if name == "uv" else None)

    # Enable stash so it returns a ref
    monkeypatch.setattr(
        spark_main, "_stash_local_changes_if_needed",
        lambda *a, **kw: "abc123deadbeef",
    )
    restore_calls = []
    monkeypatch.setattr(
        spark_main, "_restore_stashed_changes",
        lambda *a, **kw: restore_calls.append(1) or True,
    )

    side_effect, recorded = _make_update_side_effect(
        current_branch="fix/something", commit_count="0",
    )
    monkeypatch.setattr(spark_main.subprocess, "run", side_effect)

    spark_main.cmd_update(SimpleNamespace())

    # Stash should have been restored
    assert len(restore_calls) == 1

    # Should have checked out back to the original branch
    checkout_back = [c for c in recorded if "checkout" in c and "fix/something" in c]
    assert len(checkout_back) == 1

    out = capsys.readouterr().out
    assert "Up to date." in out


def test_cmd_update_syncs_bundled_skills_after_successful_pull(monkeypatch, tmp_path, capsys):
    """After a successful git pull, update should seed new bundled skills."""
    import spark_cli.profiles as profiles
    import tools.skills_sync as skills_sync

    _setup_update_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/uv" if name == "uv" else None)

    sync_calls = []
    profile_syncs = []
    dashboard_home = tmp_path / "dashboard-home"

    def fake_sync_skills(quiet=True):
        sync_calls.append(quiet)
        return {
            "copied": ["design-md", "frontend-design"],
            "updated": [],
            "user_modified": [],
            "cleaned": [],
        }

    monkeypatch.setattr(skills_sync, "sync_skills", fake_sync_skills)
    monkeypatch.setattr(profiles, "get_active_profile_name", lambda: "default")
    monkeypatch.setattr(
        profiles,
        "list_profiles",
        lambda: [
            SimpleNamespace(name="default", path=tmp_path / ".spark"),
            SimpleNamespace(name="dashboard", path=tmp_path / ".spark" / "profiles" / "dashboard"),
        ],
    )
    monkeypatch.setattr(
        profiles,
        "seed_profile_skills",
        lambda path, quiet=True: profile_syncs.append((path, quiet)) or {
            "copied": ["design-md"],
            "updated": ["frontend-design"],
            "user_modified": [],
        },
    )
    monkeypatch.setattr(
        spark_main,
        "_running_dashboard_spark_homes",
        lambda: [dashboard_home],
    )
    # Use commit_count="1" so a pull actually occurs
    side_effect, _recorded = _make_update_side_effect(commit_count="1")
    monkeypatch.setattr(spark_main.subprocess, "run", side_effect)

    spark_main.cmd_update(SimpleNamespace())

    assert sync_calls == [True]
    assert profile_syncs == [
        (tmp_path / ".spark" / "profiles" / "dashboard", True),
        (dashboard_home, True),
    ]


def test_cmd_update_no_checkout_when_already_on_main(monkeypatch, tmp_path):
    """When already on main, no checkout is needed."""
    _setup_update_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/uv" if name == "uv" else None)

    side_effect, recorded = _make_update_side_effect()
    monkeypatch.setattr(spark_main.subprocess, "run", side_effect)

    spark_main.cmd_update(SimpleNamespace())

    checkout_calls = [c for c in recorded if "checkout" in c]
    assert len(checkout_calls) == 0


# ---------------------------------------------------------------------------
# Fetch failure — friendly error messages
# ---------------------------------------------------------------------------

def test_cmd_update_network_error_shows_friendly_message(monkeypatch, tmp_path, capsys):
    """Network failures during fetch show a user-friendly message."""
    _setup_update_mocks(monkeypatch, tmp_path)

    side_effect, _ = _make_update_side_effect(
        fetch_fails=True,
        fetch_stderr="fatal: unable to access 'https://...': Could not resolve host: github.com",
    )
    monkeypatch.setattr(spark_main.subprocess, "run", side_effect)

    with pytest.raises(SystemExit, match="1"):
        spark_main.cmd_update(SimpleNamespace())

    out = capsys.readouterr().out
    assert "Network error" in out


def test_cmd_update_auth_error_shows_friendly_message(monkeypatch, tmp_path, capsys):
    """Auth failures during fetch show a user-friendly message."""
    _setup_update_mocks(monkeypatch, tmp_path)

    side_effect, _ = _make_update_side_effect(
        fetch_fails=True,
        fetch_stderr="fatal: Authentication failed for 'https://...'",
    )
    monkeypatch.setattr(spark_main.subprocess, "run", side_effect)

    with pytest.raises(SystemExit, match="1"):
        spark_main.cmd_update(SimpleNamespace())

    out = capsys.readouterr().out
    assert "Authentication failed" in out


# ---------------------------------------------------------------------------
# reset --hard failure — don't attempt stash restore
# ---------------------------------------------------------------------------

def test_cmd_update_skips_stash_restore_when_reset_fails(monkeypatch, tmp_path, capsys):
    """When reset --hard fails, stash restore is skipped with a helpful message."""
    _setup_update_mocks(monkeypatch, tmp_path)
    # Re-enable stash so it actually returns a ref
    monkeypatch.setattr(
        spark_main, "_stash_local_changes_if_needed",
        lambda *a, **kw: "abc123deadbeef",
    )
    restore_calls = []
    monkeypatch.setattr(
        spark_main, "_restore_stashed_changes",
        lambda *a, **kw: restore_calls.append(1) or True,
    )

    side_effect, _ = _make_update_side_effect(ff_only_fails=True, reset_fails=True)
    monkeypatch.setattr(spark_main.subprocess, "run", side_effect)

    with pytest.raises(SystemExit, match="1"):
        spark_main.cmd_update(SimpleNamespace())

    # Stash restore should NOT have been called
    assert len(restore_calls) == 0

    out = capsys.readouterr().out
    assert "preserved in stash" in out
