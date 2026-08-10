"""Pure helpers for the durable Spark web conversation projections.

The web server owns lifecycle and persistence.  These helpers keep the
workspace-diff and TodoStore/checkpoint translations deterministic and easy to
test without starting FastAPI or an agent worker.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _file_map(snapshot: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(snapshot, Mapping):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in snapshot.get("files", []) or []:
        if not isinstance(item, Mapping):
            continue
        path = str(item.get("path") or "").strip()
        if path:
            result[path] = dict(item)
    return result


def compute_changed_files(
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Return the files whose project status changed during one turn.

    A file already dirty before the turn is not attributed to the turn unless
    its status/counts change.  A file restored to its baseline is represented
    with ``final: None`` so the UI can explain the reversal.
    """
    if not isinstance(before, Mapping) and not isinstance(after, Mapping):
        return None
    before_files = _file_map(before)
    after_files = _file_map(after)
    changed: list[dict[str, Any]] = []
    for path in sorted(set(before_files) | set(after_files)):
        prior = before_files.get(path)
        final = after_files.get(path)
        if prior == final:
            continue
        changed.append(
            {
                "path": path,
                "before": prior,
                "after": final,
                "status": (
                    str(final.get("status") or "modified")
                    if final
                    else "reverted"
                ),
            }
        )
    return {
        "is_repo": bool(
            (after or {}).get("is_repo", (before or {}).get("is_repo", False))
        ),
        "branch": (after or {}).get("branch") or (before or {}).get("branch"),
        "files": changed,
        "count": len(changed),
    }


def normalize_plan(
    todos: Any,
    *,
    revision: int,
    markdown: str | None = None,
    updated_at: float | None = None,
) -> dict[str, Any]:
    """Normalize TodoStore/checkpoint items into the web plan contract."""
    steps: list[dict[str, str]] = []
    for item in todos if isinstance(todos, list) else []:
        if not isinstance(item, Mapping):
            continue
        step_id = str(item.get("id") or "").strip()
        content = str(item.get("content") or "").strip()
        if not step_id or not content:
            continue
        status = str(item.get("status") or "pending").strip().lower()
        if status not in {"pending", "in_progress", "completed", "cancelled"}:
            status = "pending"
        steps.append({"id": step_id, "content": content, "status": status})
    if not steps:
        status = "empty"
    elif all(step["status"] in {"completed", "cancelled"} for step in steps):
        status = "completed"
    else:
        status = "active"
    payload: dict[str, Any] = {
        "revision": max(1, int(revision)),
        "steps": steps,
        "status": status,
        "markdown": markdown.strip() if isinstance(markdown, str) and markdown.strip() else None,
    }
    if updated_at is not None:
        payload["updated_at"] = float(updated_at)
    return payload
