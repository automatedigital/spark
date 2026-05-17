"""FastAPI routes for Workspace file management API."""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from spark_cli.config import get_spark_home

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workspace", tags=["workspace"])

_MAX_FILE_READ_BYTES = 512 * 1024  # 512 KB
_MAX_TREE_DEPTH = 4
_SLUG_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")
_TERMINAL_RUN_TTL_SECONDS = 1800

_terminal_runs: dict[str, dict[str, Any]] = {}
_terminal_run_queues: dict[str, queue.Queue[dict[str, Any] | None]] = {}
_terminal_lock = threading.Lock()


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


def _tree_node(path: Path, project_dir: Path, depth: int) -> dict[str, Any]:
    rel = str(path.relative_to(project_dir))
    if path.is_dir():
        children: list[dict[str, Any]] = []
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


class TerminalRunCreate(BaseModel):
    command: str


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
    children: list[dict[str, Any]] = []
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
    files: list[UploadFile] = File(...),
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
async def upload_workspace_files(files: list[UploadFile] = File(...)):
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


# ── Project terminal ──────────────────────────────────────────────────────────


def _prune_terminal_runs() -> None:
    cutoff = time.time() - _TERMINAL_RUN_TTL_SECONDS
    with _terminal_lock:
        for run_id, run in list(_terminal_runs.items()):
            if run.get("status") in {"done", "failed", "stopped"} and run.get("updated_at", 0) < cutoff:
                _terminal_runs.pop(run_id, None)
                _terminal_run_queues.pop(run_id, None)


def _queue_terminal_event(run_id: str, event: dict[str, Any]) -> None:
    q = _terminal_run_queues.get(run_id)
    if q is not None:
        try:
            q.put_nowait(event)
        except queue.Full:
            pass


def _run_terminal_command(run_id: str) -> None:
    run = _terminal_runs[run_id]
    command = str(run["command"])
    cwd = str(run["cwd"])
    proc: subprocess.Popen | None = None

    try:
        shell = os.environ.get("SHELL") or "/bin/bash"
        with _terminal_lock:
            run["status"] = "running"
            run["updated_at"] = time.time()
        _queue_terminal_event(run_id, {"type": "state", "status": "running"})

        proc = subprocess.Popen(
            [shell, "-lc", command],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            errors="replace",
        )
        with _terminal_lock:
            run["pid"] = proc.pid
            run["process"] = proc

        assert proc.stdout is not None
        for line in proc.stdout:
            with _terminal_lock:
                run["output"].append(line)
                run["updated_at"] = time.time()
            _queue_terminal_event(run_id, {"type": "output", "stream": "stdout", "text": line})

        exit_code = proc.wait()
        with _terminal_lock:
            if run.get("status") == "stopped":
                status = "stopped"
            else:
                status = "done" if exit_code == 0 else "failed"
                run["status"] = status
            run["exit_code"] = exit_code
            run["process"] = None
            run["updated_at"] = time.time()
        _queue_terminal_event(run_id, {"type": "done", "status": status, "exit_code": exit_code})
    except Exception as exc:
        with _terminal_lock:
            run["status"] = "failed"
            run["exit_code"] = None
            run["process"] = None
            run["updated_at"] = time.time()
            run["output"].append(f"{exc}\n")
        _queue_terminal_event(run_id, {"type": "output", "stream": "stderr", "text": f"{exc}\n"})
        _queue_terminal_event(run_id, {"type": "done", "status": "failed", "exit_code": None})
    finally:
        q = _terminal_run_queues.get(run_id)
        if q is not None:
            q.put_nowait(None)


@router.post("/projects/{slug}/terminal/runs")
def start_terminal_run(slug: str, body: TerminalRunCreate):
    project_dir = _project_dir(slug)
    command = body.command.strip()
    if not command:
        raise HTTPException(status_code=400, detail="Command is required")

    _prune_terminal_runs()
    run_id = f"wterm_{uuid.uuid4().hex[:16]}"
    q: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=512)
    _terminal_runs[run_id] = {
        "run_id": run_id,
        "slug": slug,
        "command": command,
        "cwd": str(project_dir),
        "status": "queued",
        "exit_code": None,
        "pid": None,
        "process": None,
        "output": [],
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    _terminal_run_queues[run_id] = q
    threading.Thread(target=_run_terminal_command, args=(run_id,), daemon=True).start()
    return {"run_id": run_id, "status": "queued", "cwd": str(project_dir)}


@router.get("/projects/{slug}/terminal/runs/{run_id}/stream")
async def stream_terminal_run(request: Request, slug: str, run_id: str):
    run = _terminal_runs.get(run_id)
    if not run or run.get("slug") != slug:
        raise HTTPException(status_code=404, detail="Run not found")
    q = _terminal_run_queues.get(run_id)
    replay_output = q is None
    if q is None:
        q = queue.Queue(maxsize=512)
        _terminal_run_queues[run_id] = q

    async def event_generator():
        yield f"data: {json.dumps({'type': 'state', 'status': run.get('status'), 'cwd': run.get('cwd')})}\n\n"
        output = "".join(run.get("output", []))
        if replay_output and output:
            yield f"data: {json.dumps({'type': 'output', 'stream': 'stdout', 'text': output})}\n\n"
        if run.get("status") in ("done", "failed", "stopped") and q.empty():
            yield f"data: {json.dumps({'type': 'done', 'status': run.get('status'), 'exit_code': run.get('exit_code')})}\n\n"
            return
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.to_thread(q.get, True, 20)
                except queue.Empty:
                    yield "event: ping\ndata: {}\n\n"
                    if run.get("status") in ("done", "failed", "stopped"):
                        break
                    continue
                if event is None:
                    break
                yield f"data: {json.dumps(event, default=str)}\n\n"
                if event.get("type") == "done":
                    break
        finally:
            if run.get("status") in ("done", "failed", "stopped"):
                _terminal_run_queues.pop(run_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/projects/{slug}/terminal/runs/{run_id}/stop")
def stop_terminal_run(slug: str, run_id: str):
    run = _terminal_runs.get(run_id)
    if not run or run.get("slug") != slug:
        raise HTTPException(status_code=404, detail="Run not found")
    proc = run.get("process")
    if proc is not None and proc.poll() is None:
        run["status"] = "stopped"
        run["updated_at"] = time.time()
        proc.terminate()
        _queue_terminal_event(run_id, {"type": "state", "status": "stopped"})
    return {"ok": True, "run_id": run_id, "status": run.get("status")}


def register_workspace_routes(app) -> None:
    app.include_router(router)
