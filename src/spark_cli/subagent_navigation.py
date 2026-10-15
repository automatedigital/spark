"""Verified, profile-local destinations for explicitly activated child navigation.

No execution, setup, cleanup, or cross-profile discovery. A project is only a
workspace symlink to an already owned Git worktree, matching local-folder import.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from core.spark_constants import get_spark_home
from tools.subagent_worktree import (
    SubagentWorktree,
    WorktreeIsolationError,
    _git,
    get_subagent_worktree,
)


class NavigationUnavailable(ValueError):
    """The stored reference no longer establishes a safe destination."""


def _verified_worktree(run: dict[str, Any]) -> SubagentWorktree:
    supplied = run.get("worktree")
    if not isinstance(supplied, dict):
        raise NavigationUnavailable("This child has no recorded isolated worktree.")
    try:
        record = get_subagent_worktree(run["id"])
        if record is None:
            raise NavigationUnavailable("Worktree ownership is unavailable in this profile.")
        if any(not isinstance(getattr(record, key), str) for key in
               ("run_id", "repository", "base_commit", "branch", "path", "setup_status")):
            raise NavigationUnavailable("Worktree ownership metadata is invalid.")
        if not re.fullmatch(r"[a-fA-F0-9]{4,64}", record.base_commit):
            raise NavigationUnavailable("The worktree base commit cannot be verified.")
        # Snapshots are references, not authority to open arbitrary supplied paths.
        for key in ("run_id", "repository", "base_commit", "branch", "path", "setup_status"):
            if supplied.get(key) != getattr(record, key):
                raise NavigationUnavailable("Worktree references do not match this profile's ownership record.")
        expected = get_spark_home() / "subagent-worktrees" / "checkouts" / run["id"]
        checkout = Path(record.path)
        if not checkout.is_absolute() or checkout.is_symlink() or checkout.resolve() != expected.resolve():
            raise NavigationUnavailable("Worktree path is outside its owned checkout.")
        if not checkout.is_dir():
            raise NavigationUnavailable("The recorded worktree checkout is no longer available.")
        if record.branch != f"feat/subagent-{run['id']}":
            raise NavigationUnavailable("Worktree branch ownership cannot be verified.")
        repository = Path(record.repository)
        if not repository.is_absolute() or not repository.is_dir():
            raise NavigationUnavailable("The worktree repository is no longer available.")
        if Path(_git(checkout, "rev-parse", "--show-toplevel")).resolve() != checkout.resolve():
            raise NavigationUnavailable("The recorded path is not the worktree root.")
        if _git(checkout, "symbolic-ref", "--short", "HEAD") != record.branch:
            raise NavigationUnavailable("The checkout has changed branches; its recorded destination is unavailable.")
        _git(repository, "cat-file", "-e", f"{record.base_commit}^{{commit}}")
        # Worktree registration and common Git storage must agree. No write Git
        # commands or status refresh: active workers/dirty files remain untouched.
        entries = _git(repository, "worktree", "list", "--porcelain", "-z").split("\0\0")
        fields = {"worktree " + str(checkout.resolve()), "branch refs/heads/" + record.branch}
        if not any(fields.issubset(set(entry.split("\0"))) for entry in entries):
            raise NavigationUnavailable("This checkout is not registered to its recorded repository.")
        common = Path(_git(checkout, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve()
        owner_common = Path(_git(repository, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve()
        if common != owner_common:
            raise NavigationUnavailable("The checkout belongs to another repository.")
        return record
    except NavigationUnavailable:
        raise
    except (WorktreeIsolationError, OSError, TypeError, ValueError) as exc:
        raise NavigationUnavailable("The recorded local Git worktree could not be verified.") from exc


def _project_slug(record: SubagentWorktree) -> str:
    digest = hashlib.sha256((record.run_id + "\0" + record.path).encode()).hexdigest()[:12]
    return f"subagent-{record.run_id[:48]}-{digest}"


def _project_entry(record: SubagentWorktree) -> Path:
    entry = get_spark_home() / "workspace" / _project_slug(record)
    if entry.is_symlink():
        if entry.resolve() != Path(record.path).resolve():
            raise NavigationUnavailable("The worktree project name is already linked to another folder.")
    elif entry.exists():
        raise NavigationUnavailable("The worktree project name is already in use.")
    return entry


def navigation_destinations(run: dict[str, Any], parent_session_ids: list[str]) -> dict[str, Any]:
    from core.kanban_db import task_references_for_sessions

    references = task_references_for_sessions(parent_session_ids)
    if len({ref["id"] for ref in references}) == 1:
        task = {"supported": True, "reason": None, **references[0]}
    else:
        task = {"supported": False, "reason": (
            "Several board tasks reference this conversation; a unique task destination is unavailable."
            if references else "No linked board task is available in this profile. Assignments in other profiles cannot be opened here."
        )}
    try:
        record = _verified_worktree(run)
        _project_entry(record)
        worktree = {"supported": True, "reason": None, "project_slug": _project_slug(record),
                    "path": record.path, "branch": record.branch}
    except NavigationUnavailable as exc:
        worktree = {"supported": False, "reason": str(exc)}
    return {"schema_version": 1, "subagent_id": run["id"], "task": task, "worktree": worktree}


def open_worktree_project(run: dict[str, Any]) -> dict[str, Any]:
    record = _verified_worktree(run)
    entry = _project_entry(record)
    # Atomically create only the link. A lost acknowledgement is safe to retry:
    # an existing matching symlink is the receipt; every other collision refuses.
    if not entry.is_symlink():
        entry.parent.mkdir(parents=True, exist_ok=True)
        try:
            entry.symlink_to(record.path, target_is_directory=True)
        except FileExistsError:
            _project_entry(record)
        except OSError as exc:
            raise NavigationUnavailable("The worktree project could not be linked.") from exc
    return {"ok": True, "subagent_id": run["id"], "project_slug": entry.name}
