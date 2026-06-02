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

import json
import logging
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from spark_cli.config import get_spark_home
from spark_cli.workspace_routes import _SLUG_RE, _project_dir, _workspace_root

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/canvases", tags=["canvases"])

_CANVAS_EXT = ".canvas.json"
# Canvas ids double as filenames; keep them filesystem-safe and human-friendly.
_CANVAS_ID_RE = re.compile(r"^[a-zA-Z0-9_\- ]{1,80}$")


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
    return _scope_dir(scope, slug) / f"{canvas_id}{_CANVAS_EXT}"


def _summary(path: Path, scope: str, slug: str | None) -> dict[str, Any]:
    canvas_id = path.name[: -len(_CANVAS_EXT)]
    name = canvas_id
    try:
        with path.open(encoding="utf-8") as fh:
            doc = json.load(fh)
        name = doc.get("name") or canvas_id
    except Exception:  # noqa: BLE001 — a corrupt file shouldn't break the listing
        pass
    return {
        "id": canvas_id,
        "name": name,
        "scope": scope,
        "slug": slug,
        "updatedAt": datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat(),
    }


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


@router.get("")
def list_canvases() -> dict[str, Any]:
    """List every saved canvas across the global store and all projects."""
    canvases: list[dict[str, Any]] = []

    global_dir = _global_dir()
    for path in sorted(global_dir.glob(f"*{_CANVAS_EXT}")):
        canvases.append(_summary(path, "global", None))

    workspace = _workspace_root()
    for project in sorted(p for p in workspace.iterdir() if p.is_dir()):
        if project.name == "files" or not _SLUG_RE.match(project.name):
            continue
        for path in sorted(project.glob(f"*{_CANVAS_EXT}")):
            canvases.append(_summary(path, "project", project.name))

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
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Canvas not found: {canvas_id!r}")
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to read canvas: {exc}")


def _write_canvas(scope: str, slug: str | None, canvas_id: str, doc: CanvasDoc) -> dict[str, Any]:
    path = _canvas_path(scope, slug, canvas_id)
    payload = doc.model_dump()
    payload["id"] = canvas_id
    payload["scope"] = scope
    payload["slug"] = slug
    payload["updatedAt"] = datetime.now(tz=UTC).isoformat()
    tmp = path.with_suffix(f".tmp-{int(time.time() * 1000)}")
    try:
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception as exc:  # noqa: BLE001
        tmp.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Failed to write canvas: {exc}")
    return {"ok": True, "id": canvas_id, "scope": scope, "slug": slug, "updatedAt": payload["updatedAt"]}


def _delete_canvas(scope: str, slug: str | None, canvas_id: str) -> dict[str, Any]:
    path = _canvas_path(scope, slug, canvas_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Canvas not found: {canvas_id!r}")
    try:
        path.unlink()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to delete canvas: {exc}")
    return {"ok": True, "deleted": canvas_id}


def register_canvas_routes(app) -> None:
    app.include_router(router)
