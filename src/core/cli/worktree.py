"""Git worktree isolation helpers for the Spark CLI.

Extracted from core/cli/__init__.py (Phase 3). These manage the isolated git
worktree an agent instance runs in (#652): setup, cleanup, and pruning of stale
worktrees/branches. ``_active_worktree`` tracks the current worktree for atexit
cleanup; use ``set_active_worktree`` to update it from outside this module.
"""

from __future__ import annotations

import logging
import os
import shutil
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)


def set_active_worktree(info: dict[str, str] | None) -> None:
    """Record the active worktree (used by main() after setup)."""
    global _active_worktree
    _active_worktree = info


# Tracks the active worktree for cleanup on exit
_active_worktree: dict[str, str] | None = None


def _git_repo_root() -> str | None:
    """Return the git repo root for CWD, or None if not in a repo."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _path_is_within_root(path: Path, root: Path) -> bool:
    """Return True when a resolved path stays within the expected root."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _setup_worktree(repo_root: str = None) -> dict[str, str] | None:
    """Create an isolated git worktree for this CLI session.

    Returns a dict with worktree metadata on success, None on failure.
    The dict contains: path, branch, repo_root.
    """
    import subprocess

    repo_root = repo_root or _git_repo_root()
    if not repo_root:
        print(
            "\033[31mERROR: --worktree requires being inside a git repository.\033[0m"
        )
        print("  cd into your project repo first, then run spark -w")
        return None

    short_id = uuid.uuid4().hex[:8]
    wt_name = f"spark-{short_id}"
    branch_name = f"spark/{wt_name}"

    worktrees_dir = Path(repo_root) / ".worktrees"
    worktrees_dir.mkdir(parents=True, exist_ok=True)

    wt_path = worktrees_dir / wt_name

    # Ensure .worktrees/ is in .gitignore
    gitignore = Path(repo_root) / ".gitignore"
    _ignore_entry = ".worktrees/"
    try:
        existing = gitignore.read_text() if gitignore.exists() else ""
        if _ignore_entry not in existing.splitlines():
            with open(gitignore, "a") as f:
                if existing and not existing.endswith("\n"):
                    f.write("\n")
                f.write(f"{_ignore_entry}\n")
    except Exception as e:
        logger.debug("Could not update .gitignore: %s", e)

    # Create the worktree
    try:
        result = subprocess.run(
            ["git", "worktree", "add", str(wt_path), "-b", branch_name, "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=repo_root,
        )
        if result.returncode != 0:
            print(
                f"\033[31mERROR: Failed to create worktree: {result.stderr.strip()}\033[0m"
            )
            return None
    except Exception as e:
        print(f"\033[31mERROR: Failed to create worktree: {e}\033[0m")
        return None

    # Copy files listed in .worktreeinclude (gitignored files the agent needs)
    include_file = Path(repo_root) / ".worktreeinclude"
    if include_file.exists():
        try:
            repo_root_resolved = Path(repo_root).resolve()
            wt_path_resolved = wt_path.resolve()
            for line in include_file.read_text().splitlines():
                entry = line.strip()
                if not entry or entry.startswith("#"):
                    continue
                src = Path(repo_root) / entry
                dst = wt_path / entry
                # Prevent path traversal and symlink escapes: both the resolved
                # source and the resolved destination must stay inside their
                # expected roots before any file or symlink operation happens.
                try:
                    src_resolved = src.resolve(strict=False)
                    dst_resolved = dst.resolve(strict=False)
                except (OSError, ValueError):
                    logger.debug("Skipping invalid .worktreeinclude entry: %s", entry)
                    continue
                if not _path_is_within_root(src_resolved, repo_root_resolved):
                    logger.warning(
                        "Skipping .worktreeinclude entry outside repo root: %s", entry
                    )
                    continue
                if not _path_is_within_root(dst_resolved, wt_path_resolved):
                    logger.warning(
                        "Skipping .worktreeinclude entry that escapes worktree: %s",
                        entry,
                    )
                    continue
                if src.is_file():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(src), str(dst))
                elif src.is_dir():
                    # Symlink directories (faster, saves disk)
                    if not dst.exists():
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        os.symlink(str(src_resolved), str(dst))
        except Exception as e:
            logger.debug("Error copying .worktreeinclude entries: %s", e)

    info = {
        "path": str(wt_path),
        "branch": branch_name,
        "repo_root": repo_root,
    }

    print(f"\033[32mOK: Worktree created:\033[0m {wt_path}")
    print(f"  Branch: {branch_name}")

    return info


def _cleanup_worktree(info: dict[str, str] = None) -> None:
    """Remove a worktree and its branch on exit.

    Preserves the worktree only if it has unpushed commits (real work
    that hasn't been pushed to any remote).  Uncommitted changes alone
    (untracked files, test artifacts) are not enough to keep it - agent
    work lives in commits/PRs, not the working tree.
    """
    global _active_worktree
    info = info or _active_worktree
    if not info:
        return

    import subprocess

    wt_path = info["path"]
    branch = info["branch"]
    repo_root = info["repo_root"]

    if not Path(wt_path).exists():
        return

    # Check for unpushed commits - commits reachable from HEAD but not
    # from any remote branch.  These represent real work the agent did
    # but didn't push.
    has_unpushed = False
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "HEAD", "--not", "--remotes"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=wt_path,
        )
        has_unpushed = bool(result.stdout.strip())
    except Exception:
        has_unpushed = True  # Assume unpushed on error - don't delete

    if has_unpushed:
        print(
            f"\n\033[33mWARN Worktree has unpushed commits, keeping: {wt_path}\033[0m"
        )
        print(f"  To clean up manually: git worktree remove --force {wt_path}")
        _active_worktree = None
        return

    # Remove worktree (even if working tree is dirty - uncommitted
    # changes without unpushed commits are just artifacts)
    try:
        subprocess.run(
            ["git", "worktree", "remove", wt_path, "--force"],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=repo_root,
        )
    except Exception as e:
        logger.debug("Failed to remove worktree: %s", e)

    # Delete the branch
    try:
        subprocess.run(
            ["git", "branch", "-D", branch],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=repo_root,
        )
    except Exception as e:
        logger.debug("Failed to delete branch %s: %s", branch, e)

    _active_worktree = None
    print(f"\033[32mOK: Worktree cleaned up: {wt_path}\033[0m")


def _prune_stale_worktrees(repo_root: str, max_age_hours: int = 24) -> None:
    """Remove stale worktrees and orphaned branches on startup.

    Age-based tiers:
    - Under max_age_hours (24h): skip - session may still be active.
    - 24h–72h: remove if no unpushed commits.
    - Over 72h: force remove regardless (nothing should sit this long).

    Also prunes orphaned `.spark/*`` and ``pr-*`` local branches that
    have no corresponding worktree.
    """
    import subprocess
    import time

    worktrees_dir = Path(repo_root) / ".worktrees"
    if not worktrees_dir.exists():
        _prune_orphaned_branches(repo_root)
        return

    now = time.time()
    soft_cutoff = now - (max_age_hours * 3600)  # 24h default
    hard_cutoff = now - (max_age_hours * 3 * 3600)  # 72h default

    for entry in worktrees_dir.iterdir():
        if not entry.is_dir() or not entry.name.startswith("spark-"):
            continue

        # Check age
        try:
            mtime = entry.stat().st_mtime
            if mtime > soft_cutoff:
                continue  # Too recent - skip
        except Exception:
            continue

        force = mtime <= hard_cutoff  # Over 72h - force remove

        if not force:
            # 24h–72h tier: only remove if no unpushed commits
            try:
                result = subprocess.run(
                    ["git", "log", "--oneline", "HEAD", "--not", "--remotes"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    cwd=str(entry),
                )
                if result.stdout.strip():
                    continue  # Has unpushed commits - skip
            except Exception:
                continue  # Can't check - skip

        # Safe to remove
        try:
            branch_result = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=str(entry),
            )
            branch = branch_result.stdout.strip()

            subprocess.run(
                ["git", "worktree", "remove", str(entry), "--force"],
                capture_output=True,
                text=True,
                timeout=15,
                cwd=repo_root,
            )
            if branch:
                subprocess.run(
                    ["git", "branch", "-D", branch],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    cwd=repo_root,
                )
            logger.debug("Pruned stale worktree: %s (force=%s)", entry.name, force)
        except Exception as e:
            logger.debug("Failed to prune worktree %s: %s", entry.name, e)

    _prune_orphaned_branches(repo_root)


def _prune_orphaned_branches(repo_root: str) -> None:
    """Delete local `"spark/spark-*`` and ``pr-*`` branches with no worktree.

    These are auto-generated by ``spark -w`` sessions and PR review
    workflows respectively.  Once their worktree is gone they serve no
    purpose and just accumulate.
    """
    import subprocess

    try:
        result = subprocess.run(
            ["git", "branch", "--format=%(refname:short)"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=repo_root,
        )
        if result.returncode != 0:
            return
        all_branches = [
            b.strip() for b in result.stdout.strip().split("\n") if b.strip()
        ]
    except Exception:
        return

    # Collect branches that are actively checked out in a worktree
    active_branches: set = set()
    try:
        wt_result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=repo_root,
        )
        for line in wt_result.stdout.split("\n"):
            if line.startswith("branch refs/heads/"):
                active_branches.add(line.split("branch refs/heads/", 1)[-1].strip())
    except Exception:
        return  # Can't determine active branches - bail

    # Also protect the currently checked-out branch and main
    try:
        head_result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=repo_root,
        )
        current = head_result.stdout.strip()
        if current:
            active_branches.add(current)
    except Exception:
        pass
    active_branches.add("main")

    orphaned = [
        b
        for b in all_branches
        if b not in active_branches
        and (b.startswith("spark/spark-") or b.startswith("pr-"))
    ]

    if not orphaned:
        return

    # Delete in batches
    for i in range(0, len(orphaned), 50):
        batch = orphaned[i : i + 50]
        try:
            subprocess.run(
                ["git", "branch", "-D"] + batch,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=repo_root,
            )
        except Exception as e:
            logger.debug("Failed to prune orphaned branches: %s", e)

    logger.debug("Pruned %d orphaned branches", len(orphaned))

