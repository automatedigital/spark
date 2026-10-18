"""Explicit local Git worktree isolation for delegated coding work.

This is runtime infrastructure, not a model-facing tool. Never silently downgrade
requested isolation, copy uncommitted parent files, or remove useful child work.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from core.spark_constants import get_spark_home

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}\Z")
_COMMIT = re.compile(r"[a-fA-F0-9]{4,64}\Z")
_GIT_TIMEOUT = 30


class WorktreeIsolationError(RuntimeError):
    """Requested isolation could not be established; no shared-directory fallback."""


@dataclass(frozen=True)
class SubagentWorktree:
    run_id: str
    repository: str
    base_commit: str
    branch: str
    path: str
    active: bool = True
    setup_status: str = "not_requested"
    setup_error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _identity(run_id: str) -> str:
    if not isinstance(run_id, str) or not _ID.fullmatch(run_id):
        raise WorktreeIsolationError("Worktree run ID must contain only letters, digits, '-' and '_'")
    return run_id


def _root() -> Path:
    return get_spark_home() / "subagent-worktrees"


def _metadata_path(run_id: str) -> Path:
    return _root() / f"{_identity(run_id)}.json"


def _git(directory: str | Path, *args: str) -> str:
    # Git's process cwd and arguments are explicit; never change process-global
    # cwd/environment while other agents are running.
    env = dict(os.environ)
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        env.pop(key, None)
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        result = subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", *args],
            cwd=directory, env=env, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=_GIT_TIMEOUT, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WorktreeIsolationError(f"Git worktree inspection failed: {exc}") from exc
    if result.returncode:
        raise WorktreeIsolationError(result.stderr.strip()[:2000] or "Git worktree command failed")
    return result.stdout.strip()


def _save(record: SubagentWorktree) -> None:
    target = _metadata_path(record.run_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Only the worker owning this unique run ID writes its metadata.
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(record.as_dict(), indent=2) + "\n")
    temporary.replace(target)


def get_subagent_worktree(run_id: str) -> SubagentWorktree | None:
    try:
        value = json.loads(_metadata_path(run_id).read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise WorktreeIsolationError(f"Cannot read worktree metadata: {exc}") from exc
    try:
        record = SubagentWorktree(**value)
    except (TypeError, ValueError) as exc:
        raise WorktreeIsolationError("Invalid worktree metadata; retain for inspection") from exc
    if record.run_id != run_id:
        raise WorktreeIsolationError("Worktree ownership mismatch")
    return record


def _run_setup(command: list[str], directory: Path, timeout: int) -> None:
    # Keep verbose setup output off the Python heap, and terminate the process
    # group on timeout before recording that setup no longer owns the checkout.
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(
            command, cwd=directory, stdin=subprocess.DEVNULL, stdout=output,
            stderr=subprocess.STDOUT, start_new_session=os.name != "nt",
        )
        try:
            status = process.wait(timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            if os.name == "nt":
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise
        if status:
            if os.name != "nt":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            output.seek(0, os.SEEK_END)
            output.seek(max(0, output.tell() - 2000))
            detail = output.read().decode("utf-8", errors="replace")
            raise WorktreeIsolationError(f"Setup exited {status}: {detail}")


def create_subagent_worktree(
    parent_cwd: str | Path,
    run_id: str,
    *,
    backend: str = "local",
    base_commit: str | None = None,
    setup_commands: list[list[str]] | None = None,
    setup_timeout: int = 120,
) -> SubagentWorktree:
    """Create a checkout at committed content; setup commands are trusted config.

    Failures retain the worktree and metadata for diagnosis. Setup receives argv
    lists, not shell fragments. This function never merges or edits parent files.
    """
    _identity(run_id)
    if backend != "local":
        raise WorktreeIsolationError(f"Worktree isolation is unsupported for backend {backend!r}")
    try:
        directory = Path(parent_cwd).expanduser().resolve(strict=True)
    except OSError as exc:
        raise WorktreeIsolationError(f"Parent directory is unavailable: {exc}") from exc
    repository = _git(directory, "rev-parse", "--show-toplevel")
    if base_commit is not None and not _COMMIT.fullmatch(base_commit):
        raise WorktreeIsolationError("Base commit must be a hexadecimal commit ID")
    commit = _git(repository, "rev-parse", "--verify", f"{base_commit or 'HEAD'}^{{commit}}")
    branch = f"feat/subagent-{run_id}"
    checkout = _root() / "checkouts" / run_id
    metadata = _metadata_path(run_id)
    if metadata.exists() or checkout.exists():
        raise WorktreeIsolationError("Worktree run already exists; inspect it instead of overwriting")
    if setup_commands is not None and (
        not isinstance(setup_commands, list)
        or any(not isinstance(command, list) or not command
               or any(not isinstance(arg, str) or not arg or "\x00" in arg for arg in command)
               for command in setup_commands)
    ):
        raise WorktreeIsolationError("Setup commands must be non-empty argv lists")
    checkout.parent.mkdir(parents=True, exist_ok=True)
    _git(repository, "worktree", "add", "-b", branch, str(checkout), commit)
    record = SubagentWorktree(run_id, repository, commit, branch, str(checkout))
    try:
        _save(record)
    except OSError as exc:
        raise WorktreeIsolationError(f"Worktree retained at {checkout}; metadata save failed: {exc}") from exc
    if not setup_commands:
        return record
    for command in setup_commands:
        try:
            _run_setup(command, checkout, max(1, min(setup_timeout, 600)))
        except (OSError, subprocess.TimeoutExpired, WorktreeIsolationError) as exc:
            failed = replace(record, active=False, setup_status="failed", setup_error=str(exc)[:2000])
            _save(failed)
            raise WorktreeIsolationError(f"Setup failed; worktree retained at {checkout}: {exc}") from exc
    record = replace(record, setup_status="completed")
    _save(record)
    return record


def finish_subagent_worktree(run_id: str) -> SubagentWorktree:
    """Mark terminal ownership only after the child and its tools have stopped."""
    record = get_subagent_worktree(run_id)
    if record is None:
        raise WorktreeIsolationError("Worktree metadata not found")
    record = replace(record, active=False)
    _save(record)
    return record


def cleanup_subagent_worktree(run_id: str) -> dict[str, Any]:
    """Explicitly remove only a proven inactive, unchanged, uncommitted checkout.

    Never force removal. Keep the branch as an audit pointer even after cleanup;
    a separate deliberate Git action can prune branches. Unknown state is retained.
    """
    record = get_subagent_worktree(run_id)
    if record is None:
        return {"removed": False, "reason": "not_found"}
    if record.active:
        return {"removed": False, "reason": "active", "worktree": record.as_dict()}
    expected_path = (_root() / "checkouts" / _identity(run_id)).resolve()
    if Path(record.path).resolve() != expected_path or record.branch != f"feat/subagent-{run_id}":
        return {"removed": False, "reason": "ownership_mismatch"}
    try:
        # Include ignored files: a venv/build output may still be useful work.
        if _git(record.path, "status", "--porcelain", "--untracked-files=all", "--ignored"):
            return {"removed": False, "reason": "dirty", "worktree": record.as_dict()}
        if _git(record.path, "rev-parse", "HEAD") != record.base_commit:
            return {"removed": False, "reason": "committed", "worktree": record.as_dict()}
        if _git(record.path, "symbolic-ref", "--short", "HEAD") != record.branch:
            return {"removed": False, "reason": "branch_changed", "worktree": record.as_dict()}
        _git(record.repository, "worktree", "remove", record.path)
    except WorktreeIsolationError as exc:
        return {"removed": False, "reason": "inspection_failed", "error": str(exc)}
    _metadata_path(run_id).unlink()
    return {"removed": True, "branch": record.branch, "base_commit": record.base_commit}
