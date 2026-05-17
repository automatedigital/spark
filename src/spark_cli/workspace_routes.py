"""FastAPI routes for Workspace file management API."""

from __future__ import annotations

import logging
import mimetypes
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from spark_cli.config import get_spark_home

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workspace", tags=["workspace"])

_MAX_FILE_READ_BYTES = 512 * 1024  # 512 KB
_MAX_TREE_DEPTH = 4
_SLUG_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")


def _workspace_root() -> Path:
    root = get_spark_home() / "workspace"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _project_dir(slug: str) -> Path:
    if not _SLUG_RE.match(slug):
        raise HTTPException(status_code=400, detail=f"Invalid project name: {slug!r}")
    p = _workspace_root() / slug
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"Project not found: {slug!r}")
    return p


def _safe_path(project_dir: Path, rel: str) -> Path:
    """Resolve rel inside project_dir, rejecting traversals."""
    rel = rel.lstrip("/")
    resolved = (project_dir / rel).resolve()
    try:
        resolved.relative_to(project_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Path traversal detected")
    return resolved


def _tree_node(path: Path, project_dir: Path, depth: int) -> Dict[str, Any]:
    rel = str(path.relative_to(project_dir))
    if path.is_dir():
        children: List[Dict[str, Any]] = []
        if depth < _MAX_TREE_DEPTH:
            try:
                entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
                for child in entries:
                    if child.name.startswith("."):
                        continue
                    children.append(_tree_node(child, project_dir, depth + 1))
            except PermissionError:
                pass
        return {"name": path.name, "path": rel, "type": "dir", "children": children}
    stat = path.stat()
    mime, _ = mimetypes.guess_type(path.name)
    return {
        "name": path.name,
        "path": rel,
        "type": "file",
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "mime": mime or "application/octet-stream",
    }


# ── Models ──────────────────────────────────────────────────────────────────


class ProjectCreate(BaseModel):
    name: str


# ── Routes ──────────────────────────────────────────────────────────────────


@router.get("/projects")
def list_projects():
    root = _workspace_root()
    projects = []
    for p in sorted(root.iterdir(), key=lambda x: x.name.lower()):
        if not p.is_dir() or p.name.startswith("."):
            continue
        file_count = sum(1 for _ in p.rglob("*") if _.is_file())
        stat = p.stat()
        projects.append(
            {
                "slug": p.name,
                "name": p.name,
                "path": str(p),
                "mtime": stat.st_mtime,
                "file_count": file_count,
            }
        )
    return {"projects": projects}


@router.post("/projects")
def create_project(body: ProjectCreate):
    name = body.name.strip()
    slug = re.sub(r"[^a-zA-Z0-9_\-]", "-", name).strip("-") or "project"
    slug = re.sub(r"-{2,}", "-", slug)
    if not _SLUG_RE.match(slug):
        raise HTTPException(status_code=400, detail=f"Invalid project name: {name!r}")
    root = _workspace_root()
    project_path = root / slug
    if project_path.exists():
        raise HTTPException(status_code=409, detail=f"Project already exists: {slug!r}")
    project_path.mkdir(parents=True)
    return {"ok": True, "slug": slug, "name": slug, "path": str(project_path)}


@router.get("/projects/{slug}/tree")
def get_project_tree(slug: str):
    project_dir = _project_dir(slug)
    children: List[Dict[str, Any]] = []
    try:
        entries = sorted(
            project_dir.iterdir(), key=lambda p: (p.is_file(), p.name.lower())
        )
        for entry in entries:
            if entry.name.startswith("."):
                continue
            children.append(_tree_node(entry, project_dir, depth=1))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return {"slug": slug, "path": str(project_dir), "tree": children}


@router.get("/projects/{slug}/file")
def read_project_file(slug: str, path: str = Query(...)):
    project_dir = _project_dir(slug)
    file_path = _safe_path(project_dir, path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Not found: {path!r}")
    if file_path.is_dir():
        raise HTTPException(status_code=400, detail="Path is a directory")
    size = file_path.stat().st_size
    if size > _MAX_FILE_READ_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large to read ({size} bytes); max {_MAX_FILE_READ_BYTES}",
        )
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    mime, _ = mimetypes.guess_type(file_path.name)
    return {"path": path, "content": content, "mime": mime or "text/plain", "size": size}


@router.get("/projects/{slug}/raw-file")
def read_project_file_raw(slug: str, path: str = Query(...)):
    """Serve a project file with its native MIME type (binary-safe)."""
    project_dir = _project_dir(slug)
    file_path = _safe_path(project_dir, path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Not found: {path!r}")
    if file_path.is_dir():
        raise HTTPException(status_code=400, detail="Path is a directory")
    mime, _ = mimetypes.guess_type(file_path.name)
    return FileResponse(str(file_path), media_type=mime or "application/octet-stream")


@router.post("/projects/{slug}/upload")
async def upload_files(
    slug: str,
    files: List[UploadFile] = File(...),
    path: str = Query(default=""),
):
    project_dir = _project_dir(slug)
    dest_dir = _safe_path(project_dir, path) if path else project_dir
    if not dest_dir.exists():
        dest_dir.mkdir(parents=True, exist_ok=True)
    if not dest_dir.is_dir():
        raise HTTPException(status_code=400, detail="Upload path is not a directory")

    saved = []
    for upload in files:
        filename = Path(upload.filename or "upload").name
        dest = dest_dir / filename
        try:
            content = await upload.read()
            dest.write_bytes(content)
            saved.append({"filename": filename, "size": len(content)})
        except Exception as exc:
            _log.warning("Upload failed for %s: %s", filename, exc)
            raise HTTPException(status_code=500, detail=f"Failed to save {filename}: {exc}")
    return {"ok": True, "saved": saved}


@router.post("/files/upload")
async def upload_workspace_files(files: List[UploadFile] = File(...)):
    dest_dir = _workspace_root() / "files"
    dest_dir.mkdir(parents=True, exist_ok=True)

    saved = []
    for upload in files:
        filename = Path(upload.filename or "upload").name
        dest = dest_dir / filename
        try:
            content = await upload.read()
            dest.write_bytes(content)
            saved.append(
                {
                    "filename": filename,
                    "path": f"files/{filename}",
                    "absolute_path": str(dest),
                    "size": len(content),
                }
            )
        except Exception as exc:
            _log.warning("Upload failed for %s: %s", filename, exc)
            raise HTTPException(status_code=500, detail=f"Failed to save {filename}: {exc}")
    return {"ok": True, "saved": saved}


@router.delete("/projects/{slug}/file")
def delete_file(slug: str, path: str = Query(...)):
    project_dir = _project_dir(slug)
    target = _safe_path(project_dir, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Not found: {path!r}")
    try:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"ok": True, "deleted": path}


def register_workspace_routes(app) -> None:
    app.include_router(router)
