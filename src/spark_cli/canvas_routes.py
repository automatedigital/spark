"""FastAPI routes for the Canvas (infinite canvas / node graph) feature.

Canvases are stored as JSON documents in two scopes:

- **global**  → ``get_spark_home()/canvases/<id>.canvas.json``
- **project** → ``get_spark_home()/workspace/<slug>/<id>.canvas.json`` (visible in the
  project's file tree, so they show up alongside ordinary files)

A canvas document looks like::

    {
        "id": "my-board",
        "name": "My Board",
        "scope": "global" | "project",
        "slug": "<project-slug>" | null,
        "nodes": [...],
        "edges": [...],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "version": 1,
        "updatedAt": "2026-06-03T12:00:00Z"
    }
"""

from __future__ import annotations

import errno
import hashlib
import json
import logging
import os
import queue as _queue
import re
import stat
import tempfile
import threading as _threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO, cast

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from spark_cli.config import get_spark_home
from spark_cli.workspace_routes import _SLUG_RE, _project_dir, _workspace_root

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/canvases", tags=["canvases"])

_CANVAS_EXT = ".canvas.json"
# Canvas ids double as filenames; keep them filesystem-safe and human-friendly.
_CANVAS_ID_RE = re.compile(r"^[a-zA-Z0-9_\- ]{1,80}$")
_MAX_CANVAS_NODES = 1000
_MAX_CANVAS_EDGES = 3000
_MAX_CANVAS_BYTES = 5 * 1024 * 1024


def _global_dir() -> Path:
    d = get_spark_home() / "canvases"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _check_id(canvas_id: str) -> str:
    if not _CANVAS_ID_RE.match(canvas_id):
        raise HTTPException(status_code=400, detail=f"Invalid canvas id: {canvas_id!r}")
    return canvas_id


def _scope_dir(scope: str, slug: str | None) -> Path:
    if scope == "global":
        return _global_dir()
    if scope == "project":
        if not slug:
            raise HTTPException(status_code=400, detail="Project scope requires a slug")
        if not _SLUG_RE.match(slug):
            raise HTTPException(status_code=400, detail=f"Invalid project name: {slug!r}")
        return _project_dir(slug)
    raise HTTPException(status_code=400, detail=f"Unknown scope: {scope!r}")


def _canvas_path(scope: str, slug: str | None, canvas_id: str) -> Path:
    _check_id(canvas_id)
    # Project roots may intentionally be symlinks. Resolve only the owner, never
    # the final filename: replace/unlink must act on our lexical destination.
    path = _scope_dir(scope, slug).resolve() / f"{canvas_id}{_CANVAS_EXT}"
    _canvas_stat(path)
    return path


def _canvas_stat(path: Path) -> os.stat_result | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise HTTPException(status_code=400, detail="Canvas must be a regular file, not a symlink")
    return info


@contextmanager
def _canvas_reader(path: Path) -> Iterator[TextIO]:
    # O_NOFOLLOW closes the check/open race on POSIX. On platforms without it,
    # verify the opened identity against lstat before reading any bytes.
    _canvas_stat(path)
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise HTTPException(status_code=400, detail="Canvas must not be a symlink") from exc
        raise
    with os.fdopen(fd, encoding="utf-8") as fh:
        current = _canvas_stat(path)
        opened = os.fstat(fh.fileno())
        if current is None or not stat.S_ISREG(opened.st_mode) or (
            opened.st_dev, opened.st_ino
        ) != (current.st_dev, current.st_ino):
            raise HTTPException(status_code=400, detail="Canvas changed while opening")
        yield fh


def _canvas_lock_path(path: Path) -> Path:
    # Directory identity covers symlink, case and Unicode-normalization aliases
    # without depending on the spelling returned by resolve(). Canvas IDs are
    # ASCII: conservatively fold filenames on every filesystem. Case-distinct
    # files may serialize, but their data paths remain distinct. Never use the
    # canvas inode: it changes on atomic replace and is absent after deletion.
    owner = path.parent.stat()
    identity = f"{owner.st_dev}:{owner.st_ino}:{path.name.casefold()}"
    key = hashlib.sha256(os.fsencode(identity)).hexdigest()
    directory = get_spark_home() / "canvas-locks"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{key}.lock"


@contextmanager
def _canvas_lock(path: Path) -> Iterator[None]:
    """Serialize API access across threads/processes, including after deletion.

    Keep the profile metadata inode: unlinking it would let waiters lock a retired file
    while new requests acquire a different lock for the same canonical canvas.
    """
    with _canvas_lock_path(path).open("a+b") as lock:
        if os.name == "nt":
            import msvcrt

            if os.fstat(lock.fileno()).st_size == 0:
                lock.write(b"\0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)  # type: ignore[attr-defined]
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _revision(path: Path) -> str:
    info = _canvas_stat(path)
    if info is None:
        raise FileNotFoundError(path)
    return str(info.st_mtime_ns)


def _summary(path: Path, scope: str, slug: str | None) -> dict[str, Any]:
    canvas_id = path.name[: -len(_CANVAS_EXT)]
    name = canvas_id
    error: str | None = None
    try:
        with _canvas_reader(path) as fh:
            doc = json.load(fh)
        name = doc.get("name") or canvas_id
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 — a corrupt file shouldn't break the listing
        error = "Failed to read canvas JSON"
    info = _canvas_stat(path)
    if info is None:
        raise FileNotFoundError(path)
    summary = {
        "id": canvas_id,
        "name": name,
        "scope": scope,
        "slug": slug,
        "updatedAt": datetime.fromtimestamp(info.st_mtime, tz=UTC).isoformat(),
        "revision": _revision(path),
    }
    if error:
        summary["error"] = error
    return summary


def _append_summary(canvases: list[dict[str, Any]], path: Path, scope: str, slug: str | None) -> None:
    try:
        with _canvas_lock(path):
            canvases.append(_summary(path, scope, slug))
    except (HTTPException, FileNotFoundError):
        # Unsafe entries and files removed during enumeration are not canvases.
        return


class CanvasDoc(BaseModel):
    id: str
    name: str
    scope: str = "global"
    slug: str | None = None
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    viewport: dict[str, Any] = Field(default_factory=lambda: {"x": 0, "y": 0, "zoom": 1})
    version: int = 1
    updatedAt: str | None = None
    revision: str | None = None
    expectedRevision: str | None = None


def _validate_canvas_doc(scope: str, slug: str | None, doc: CanvasDoc) -> None:
    if doc.scope != scope:
        raise HTTPException(status_code=400, detail="Canvas document scope does not match URL scope")
    expected_slug = slug if scope == "project" else None
    if doc.slug != expected_slug:
        raise HTTPException(status_code=400, detail="Canvas document slug does not match URL slug")
    if len(doc.nodes) > _MAX_CANVAS_NODES:
        raise HTTPException(status_code=400, detail=f"Canvas has too many nodes (max {_MAX_CANVAS_NODES})")
    if len(doc.edges) > _MAX_CANVAS_EDGES:
        raise HTTPException(status_code=400, detail=f"Canvas has too many edges (max {_MAX_CANVAS_EDGES})")

    node_ids: set[str] = set()
    for node in doc.nodes:
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id:
            raise HTTPException(status_code=400, detail="Every canvas node must have a non-empty string id")
        if node_id in node_ids:
            raise HTTPException(status_code=400, detail=f"Duplicate canvas node id: {node_id!r}")
        node_ids.add(node_id)

    for edge in doc.edges:
        source = edge.get("source")
        target = edge.get("target")
        if source not in node_ids:
            raise HTTPException(status_code=400, detail=f"Canvas edge references missing source node: {source!r}")
        if target not in node_ids:
            raise HTTPException(status_code=400, detail=f"Canvas edge references missing target node: {target!r}")


@router.get("")
def list_canvases() -> dict[str, Any]:
    """List every saved canvas across the global store and all projects."""
    canvases: list[dict[str, Any]] = []

    global_dir = _global_dir()
    for path in sorted(global_dir.glob(f"*{_CANVAS_EXT}")):
        _append_summary(canvases, path, "global", None)

    workspace = _workspace_root()
    for project in sorted(p for p in workspace.iterdir() if p.is_dir()):
        if project.name == "files" or not _SLUG_RE.match(project.name):
            continue
        for path in sorted(project.glob(f"*{_CANVAS_EXT}")):
            _append_summary(canvases, path, "project", project.name)

    return {"canvases": canvases}


@router.get("/global/{canvas_id}")
def get_global_canvas(canvas_id: str) -> dict[str, Any]:
    return _read_canvas("global", None, canvas_id)


@router.put("/global/{canvas_id}")
def put_global_canvas(canvas_id: str, doc: CanvasDoc) -> dict[str, Any]:
    return _write_canvas("global", None, canvas_id, doc)


@router.delete("/global/{canvas_id}")
def delete_global_canvas(canvas_id: str) -> dict[str, Any]:
    return _delete_canvas("global", None, canvas_id)


@router.get("/project/{slug}/{canvas_id}")
def get_project_canvas(slug: str, canvas_id: str) -> dict[str, Any]:
    return _read_canvas("project", slug, canvas_id)


@router.put("/project/{slug}/{canvas_id}")
def put_project_canvas(slug: str, canvas_id: str, doc: CanvasDoc) -> dict[str, Any]:
    return _write_canvas("project", slug, canvas_id, doc)


@router.delete("/project/{slug}/{canvas_id}")
def delete_project_canvas(slug: str, canvas_id: str) -> dict[str, Any]:
    return _delete_canvas("project", slug, canvas_id)


def _read_canvas(scope: str, slug: str | None, canvas_id: str) -> dict[str, Any]:
    path = _canvas_path(scope, slug, canvas_id)
    with _canvas_lock(path):
        if _canvas_stat(path) is None:
            raise HTTPException(status_code=404, detail=f"Canvas not found: {canvas_id!r}")
        try:
            with _canvas_reader(path) as fh:
                doc = json.load(fh)
                revision = str(os.fstat(fh.fileno()).st_mtime_ns)
            doc["revision"] = revision
            return cast("dict[str, Any]", doc)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Failed to read canvas: {exc}") from exc


def _write_canvas(scope: str, slug: str | None, canvas_id: str, doc: CanvasDoc) -> dict[str, Any]:
    path = _canvas_path(scope, slug, canvas_id)
    _validate_canvas_doc(scope, slug, doc)
    payload = doc.model_dump()
    payload["id"] = canvas_id
    payload["scope"] = scope
    payload["slug"] = slug
    payload["updatedAt"] = datetime.now(tz=UTC).isoformat()
    payload.pop("expectedRevision", None)
    payload.pop("revision", None)
    serialized = json.dumps(payload, indent=2)
    if len(serialized.encode("utf-8")) > _MAX_CANVAS_BYTES:
        raise HTTPException(
            status_code=400, detail=f"Canvas document is too large (max {_MAX_CANVAS_BYTES} bytes)"
        )
    with _canvas_lock(path):
        current_revision = _revision(path) if _canvas_stat(path) is not None else None
        if doc.expectedRevision and doc.expectedRevision != current_revision:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "revision_conflict",
                    "message": "Canvas was modified since it was loaded",
                    "currentRevision": current_revision,
                },
            )
        tmp: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as fh:
                tmp = Path(fh.name)
                fh.write(serialized)
            # Preserve distinct revisions even on coarse filesystem clocks.
            if current_revision is not None and tmp.stat().st_mtime_ns <= int(current_revision):
                stamp = max(time.time_ns(), int(current_revision) + 1)
                os.utime(tmp, ns=(stamp, stamp))
            _canvas_stat(path)
            tmp.replace(path)
            revision = _revision(path)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Failed to write canvas: {exc}") from exc
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
        return {
            "ok": True,
            "id": canvas_id,
            "scope": scope,
            "slug": slug,
            "updatedAt": payload["updatedAt"],
            "revision": revision,
        }


def _delete_canvas(scope: str, slug: str | None, canvas_id: str) -> dict[str, Any]:
    path = _canvas_path(scope, slug, canvas_id)
    with _canvas_lock(path):
        if _canvas_stat(path) is None:
            raise HTTPException(status_code=404, detail=f"Canvas not found: {canvas_id!r}")
        try:
            path.unlink()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Failed to delete canvas: {exc}") from exc
        return {"ok": True, "deleted": canvas_id}


# ── Widget interaction (canvas → agent) ──────────────────────────────────────
# A click on an interactive canvas widget is delivered to a per-widget queue;
# the agent's `canvas_await` tool blocks on it and gets the value as its result.
_interaction_queues: dict[str, _queue.Queue[str]] = {}
_interaction_lock = _threading.Lock()


def _interaction_key(scope: str, slug: str | None, canvas_id: str, widget_id: str) -> str:
    return f"{scope}:{slug or ''}:{canvas_id}:{widget_id}"


def _interaction_queue(key: str) -> _queue.Queue[str]:
    with _interaction_lock:
        q = _interaction_queues.get(key)
        if q is None:
            q = _queue.Queue(maxsize=8)
            _interaction_queues[key] = q
        return q


def submit_interaction(scope: str, slug: str | None, canvas_id: str, widget_id: str, value: str) -> None:
    _interaction_queue(_interaction_key(scope, slug, canvas_id, widget_id)).put(value)


def wait_for_interaction(scope: str, slug: str | None, canvas_id: str, widget_id: str, timeout: float) -> str | None:
    try:
        return _interaction_queue(_interaction_key(scope, slug, canvas_id, widget_id)).get(timeout=timeout)
    except _queue.Empty:
        return None


class InteractBody(BaseModel):
    scope: str = "global"
    slug: str | None = None
    canvas_id: str
    widget_id: str
    value: str


@router.post("/interact")
def canvas_interact(body: InteractBody) -> dict[str, Any]:
    """Receive a click from an interactive canvas widget and queue it for the agent."""
    submit_interaction(body.scope, body.slug, body.canvas_id, body.widget_id, body.value)
    try:
        from spark_cli.web_server import _publish_event

        _publish_event("canvas.interaction", {"canvas_id": body.canvas_id, "widget_id": body.widget_id, "value": body.value})
    except Exception:
        _log.debug("Ignoring error in canvas_interact()", exc_info=True)
    return {"ok": True}


def register_canvas_routes(app) -> None:
    app.include_router(router)
