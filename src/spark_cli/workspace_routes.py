"""FastAPI routes for Workspace file management API."""

from __future__ import annotations

import asyncio
import atexit
import fcntl
import json
import logging
import mimetypes
import os
import pty
import queue
import re
import shutil
import signal
import socket
import struct
import subprocess
import termios
import threading
import time
import uuid
import urllib.parse
import urllib.request
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
_PREVIEW_LOG_LIMIT = 500
_PREVIEW_PORT_START = 4173
_PREVIEW_PORT_END = 6173
_PREVIEW_WATCH_INTERVAL_SECONDS = 0.75
_PREVIEW_REFRESH_DEBOUNCE_SECONDS = 0.8
_PREVIEW_FETCH_MAX_BYTES = 512 * 1024
_AGENT_BROWSER_MAX_OUTPUT = 12000
_PREVIEW_IGNORED_DIRS = {
    ".git", ".next", ".vite", "__pycache__", "build", "dist", "node_modules", ".cache"
}
_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|authorization|bearer|password|secret|token)([\"'\s:=]+)([^\s\"']+)"
)

_terminal_runs: dict[str, dict[str, Any]] = {}
_terminal_run_queues: dict[str, queue.Queue[dict[str, Any] | None]] = {}
_terminal_lock = threading.Lock()
_preview_sessions: dict[str, dict[str, Any]] = {}
_preview_queues: dict[str, list[queue.Queue[dict[str, Any] | None]]] = {}
_preview_lock = threading.Lock()


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


def _tree_node(path: Path, project_dir: Path, depth: int, show_hidden: bool = False) -> dict[str, Any]:
    rel = str(path.relative_to(project_dir))
    if path.is_dir():
        children: list[dict[str, Any]] = []
        if depth < _MAX_TREE_DEPTH:
            try:
                entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
                for child in entries:
                    if not show_hidden and child.name.startswith("."):
                        continue
                    children.append(_tree_node(child, project_dir, depth + 1, show_hidden))
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
    command: str = ""


class TerminalInput(BaseModel):
    input: str


class TerminalResize(BaseModel):
    rows: int
    cols: int


class PreviewStart(BaseModel):
    command: str | None = None
    url: str | None = None


class PreviewNavigate(BaseModel):
    url: str


class PreviewBrowserAction(BaseModel):
    selector: str | None = None
    text: str | None = None
    expression: str | None = None


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
def get_project_tree(slug: str, show_hidden: bool = Query(default=False)):
    project_dir = _project_dir(slug)
    children: list[dict[str, Any]] = []
    try:
        entries = sorted(
            project_dir.iterdir(), key=lambda p: (p.is_file(), p.name.lower())
        )
        for entry in entries:
            if not show_hidden and entry.name.startswith("."):
                continue
            children.append(_tree_node(entry, project_dir, depth=1, show_hidden=show_hidden))
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


@router.get("/projects/{slug}/list")
def list_project_dir(slug: str, path: str = Query(default=""), show_hidden: bool = Query(default=False)):
    """List one level of a directory in a workspace project for @ autocomplete."""
    project_dir = _project_dir(slug)
    target = _safe_path(project_dir, path) if path else project_dir
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail=f"Not found: {path!r}")
    entries = []
    try:
        for entry in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            if not show_hidden and entry.name.startswith("."):
                continue
            rel = str(entry.relative_to(project_dir))
            entries.append({"name": entry.name, "path": rel, "type": "dir" if entry.is_dir() else "file"})
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return {"path": path, "entries": entries}


@router.get("/files/list")
def list_chat_files(path: str = Query(default=""), show_hidden: bool = Query(default=False)):
    """List chat-uploaded files for @ autocomplete. path='' returns the files/ dir entry."""
    workspace = _workspace_root()
    if not path:
        files_dir = workspace / "files"
        entries = [{"name": "files", "path": "files", "type": "dir"}] if files_dir.exists() else []
        return {"path": "", "entries": entries}

    rel = path.lstrip("/")
    target = (workspace / rel).resolve()
    try:
        target.relative_to(workspace.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Path traversal detected")
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail=f"Not found: {path!r}")

    entries = []
    try:
        for entry in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            if not show_hidden and entry.name.startswith("."):
                continue
            entry_rel = str(entry.relative_to(workspace))
            entries.append({"name": entry.name, "path": entry_rel, "type": "dir" if entry.is_dir() else "file"})
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return {"path": path, "entries": entries}


class WriteFileBody(BaseModel):
    content: str


@router.put("/files")
def write_chat_file(path: str = Query(...), body: WriteFileBody = ...):
    """Write text content to a file in the workspace files directory."""
    workspace = _workspace_root()
    rel = path.lstrip("/")
    target = (workspace / rel).resolve()
    try:
        target.relative_to(workspace.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Path traversal detected")
    if target.is_dir():
        raise HTTPException(status_code=400, detail="Path is a directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.write_text(body.content, encoding="utf-8")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"ok": True, "path": path}


@router.delete("/files")
def delete_workspace_chat_file(path: str = Query(...)):
    """Delete a file or directory from the workspace files directory."""
    workspace = _workspace_root()
    rel = path.lstrip("/")
    target = (workspace / rel).resolve()
    try:
        target.relative_to(workspace.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Path traversal detected")
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


@router.delete("/projects/{slug}")
def delete_project(slug: str):
    project_dir = _project_dir(slug)
    if slug in _preview_sessions:
        _stop_preview_session(slug)
    try:
        shutil.rmtree(project_dir)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"ok": True, "deleted": slug}


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
def start_terminal_run(slug: str, body: TerminalRunCreate | None = None):
    project_dir = _project_dir(slug)
    command = body.command.strip() if body and body.command.strip() else os.environ.get("SHELL") or "/bin/bash"

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
    if body and body.command.strip():
        threading.Thread(target=_run_terminal_command, args=(run_id,), daemon=True).start()
    else:
        threading.Thread(target=_run_terminal_shell, args=(run_id,), daemon=True).start()
    return {"run_id": run_id, "status": "queued", "cwd": str(project_dir)}


def _run_terminal_shell(run_id: str) -> None:
    run = _terminal_runs[run_id]
    cwd = str(run["cwd"])
    shell = os.environ.get("SHELL") or "/bin/bash"
    master_fd: int | None = None

    try:
        master_fd, slave_fd = pty.openpty()
        try:
            fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        except OSError:
            pass
        proc = subprocess.Popen(
            [shell, "-i"],
            cwd=cwd,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            start_new_session=True,
            close_fds=True,
            env={**os.environ, "TERM": "xterm-256color", "COLORTERM": "truecolor", "LINES": "24", "COLUMNS": "80"},
        )
        os.close(slave_fd)
        with _terminal_lock:
            run["status"] = "running"
            run["pid"] = proc.pid
            run["process"] = proc
            run["pty_fd"] = master_fd
            run["updated_at"] = time.time()
        _queue_terminal_event(run_id, {"type": "state", "status": "running"})

        while True:
            try:
                chunk = os.read(master_fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="replace")
            with _terminal_lock:
                run["output"].append(text)
                run["updated_at"] = time.time()
            _queue_terminal_event(run_id, {"type": "output", "stream": "pty", "text": text})
            if proc.poll() is not None:
                break

        exit_code = proc.poll()
        if exit_code is None:
            exit_code = proc.wait(timeout=1)
        with _terminal_lock:
            if run.get("status") != "stopped":
                run["status"] = "done" if exit_code == 0 else "failed"
            run["exit_code"] = exit_code
            run["process"] = None
            run["pty_fd"] = None
            run["updated_at"] = time.time()
        _queue_terminal_event(run_id, {"type": "done", "status": run["status"], "exit_code": exit_code})
    except Exception as exc:
        with _terminal_lock:
            run["status"] = "failed"
            run["exit_code"] = None
            run["process"] = None
            run["pty_fd"] = None
            run["updated_at"] = time.time()
            run["output"].append(f"{exc}\n")
        _queue_terminal_event(run_id, {"type": "output", "stream": "stderr", "text": f"{exc}\n"})
        _queue_terminal_event(run_id, {"type": "done", "status": "failed", "exit_code": None})
    finally:
        if master_fd is not None:
            try:
                os.close(master_fd)
            except OSError:
                pass
        q = _terminal_run_queues.get(run_id)
        if q is not None:
            q.put_nowait(None)


@router.post("/projects/{slug}/terminal/runs/{run_id}/input")
def send_terminal_input(slug: str, run_id: str, body: TerminalInput):
    run = _terminal_runs.get(run_id)
    if not run or run.get("slug") != slug:
        raise HTTPException(status_code=404, detail="Run not found")
    fd = run.get("pty_fd")
    if fd is None or run.get("status") != "running":
        raise HTTPException(status_code=400, detail="Terminal is not running")
    try:
        os.write(fd, body.input.encode("utf-8"))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"ok": True, "run_id": run_id}


@router.post("/projects/{slug}/terminal/runs/{run_id}/resize")
def resize_terminal(slug: str, run_id: str, body: TerminalResize):
    run = _terminal_runs.get(run_id)
    if not run or run.get("slug") != slug:
        raise HTTPException(status_code=404, detail="Run not found")
    fd = run.get("pty_fd")
    if fd is None or run.get("status") != "running":
        raise HTTPException(status_code=400, detail="Terminal is not running")
    rows = max(2, min(200, int(body.rows)))
    cols = max(10, min(400, int(body.cols)))
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"ok": True, "run_id": run_id, "rows": rows, "cols": cols}


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
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except Exception:
            proc.terminate()
        _queue_terminal_event(run_id, {"type": "state", "status": "stopped"})
    return {"ok": True, "run_id": run_id, "status": run.get("status")}


# ── Project preview ──────────────────────────────────────────────────────────


def _find_free_loopback_port() -> int:
    span = _PREVIEW_PORT_END - _PREVIEW_PORT_START + 1
    start = _PREVIEW_PORT_START + (uuid.uuid4().int % span)
    ports = list(range(start, _PREVIEW_PORT_END + 1)) + list(range(_PREVIEW_PORT_START, start))
    for port in ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise HTTPException(status_code=503, detail="No free preview ports available")


def _preview_emit(slug: str, event: dict[str, Any]) -> None:
    for q in list(_preview_queues.get(slug, [])):
        try:
            q.put_nowait(event)
        except queue.Full:
            pass


def _publish_workspace_event(topic: str, data: dict[str, Any]) -> None:
    try:
        from spark_cli.web_server import _publish_event

        _publish_event(topic, data)
    except Exception:
        pass


def _append_preview_log(slug: str, session: dict[str, Any], text: str, stream: str = "server") -> None:
    redacted = _SECRET_RE.sub(r"\1\2[redacted]", text)
    entry = {"ts": time.time(), "type": "log", "stream": stream, "text": redacted}
    with _preview_lock:
        logs = session.setdefault("logs", [])
        logs.append(entry)
        if len(logs) > _PREVIEW_LOG_LIMIT:
            del logs[: len(logs) - _PREVIEW_LOG_LIMIT]
        session["updated_at"] = time.time()
    _preview_emit(slug, entry)


def _preview_status_payload(slug: str, session: dict[str, Any] | None = None) -> dict[str, Any]:
    session = session or _preview_sessions.get(slug)
    if not session:
        return {
            "slug": slug,
            "status": "stopped",
            "url": None,
            "command": None,
            "port": None,
            "kind": None,
            "error": None,
            "started_at": None,
            "updated_at": None,
        }
    proc = session.get("process")
    if proc is not None and proc.poll() is not None and session.get("status") == "running":
        session["status"] = "failed"
        session["error"] = f"Preview process exited with code {proc.returncode}"
    return {
        "slug": slug,
        "status": session.get("status", "stopped"),
        "url": session.get("url"),
        "command": session.get("command"),
        "port": session.get("port"),
        "kind": session.get("kind"),
        "error": session.get("error"),
        "started_at": session.get("started_at"),
        "updated_at": session.get("updated_at"),
    }


def _normalize_browser_url(url: str) -> str:
    candidate = url.strip()
    if not candidate:
        raise HTTPException(status_code=400, detail="URL is required")
    initial = urllib.parse.urlparse(candidate)
    if initial.scheme and initial.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="Browser navigation supports http and https URLs")
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", candidate):
        candidate = f"https://{candidate}"
    parsed = urllib.parse.urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Browser navigation supports http and https URLs")
    return urllib.parse.urlunparse(parsed)


def _agent_browser_session_name(slug: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "-", slug)
    return f"spark-preview-{safe}"


def _agent_browser_bin() -> str | None:
    try:
        from spark_cli.browser_runtime import agent_browser_path

        return agent_browser_path()
    except Exception:
        return shutil.which("agent-browser")


def _run_agent_browser(slug: str, args: list[str], timeout: float = 12.0) -> dict[str, Any] | None:
    binary = _agent_browser_bin()
    if not binary:
        return None
    command = [
        binary,
        "--session",
        _agent_browser_session_name(slug),
        "--json",
        "--max-output",
        str(_AGENT_BROWSER_MAX_OUTPUT),
        *args,
    ]
    try:
        proc = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:
        return {"success": False, "error": str(exc), "stdout": "", "stderr": ""}

    output = (proc.stdout or "").strip()
    parsed: Any = None
    if output:
        try:
            parsed = json.loads(output)
        except Exception:
            parsed = output
    success = proc.returncode == 0
    if isinstance(parsed, dict) and "success" in parsed:
        success = bool(parsed.get("success"))
    return {
        "success": success,
        "returncode": proc.returncode,
        "data": parsed,
        "stdout": output,
        "stderr": (proc.stderr or "").strip(),
        "error": None if success else (parsed.get("error") if isinstance(parsed, dict) else proc.stderr or output),
    }


def _agent_browser_text(result: dict[str, Any] | None) -> str:
    if not result:
        return ""
    data = result.get("data")
    if isinstance(data, dict):
        for key in ("data", "text", "content", "result", "value"):
            value = data.get(key)
            if isinstance(value, str):
                return value
        return json.dumps(data, default=str)
    if isinstance(data, str):
        return data
    return result.get("stdout") or ""


def _is_loopback_url(url: str) -> bool:
    return urllib.parse.urlparse(url).hostname in {"127.0.0.1", "localhost", "::1"}


def _probe_preview_url(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=0.8) as resp:
            return 200 <= int(resp.status) < 500
    except Exception:
        return False


def _process_cwd(pid: int) -> Path | None:
    proc_cwd = Path("/proc") / str(pid) / "cwd"
    try:
        if proc_cwd.exists():
            return proc_cwd.resolve()
    except Exception:
        pass
    try:
        result = subprocess.run(
            ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
            capture_output=True,
            text=True,
            timeout=1.5,
            check=False,
        )
    except Exception:
        return None
    for line in result.stdout.splitlines():
        if line.startswith("n"):
            try:
                return Path(line[1:]).resolve()
            except Exception:
                return None
    return None


def _path_is_inside(path: Path | None, parent: Path) -> bool:
    if path is None:
        return False
    try:
        path.relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _list_loopback_listeners() -> list[tuple[int, int]]:
    listeners: list[tuple[int, int]] = []
    try:
        result = subprocess.run(
            ["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-FnPi"],
            capture_output=True,
            text=True,
            timeout=2.5,
            check=False,
        )
    except Exception:
        return listeners

    pid: int | None = None
    for line in result.stdout.splitlines():
        if line.startswith("p"):
            try:
                pid = int(line[1:])
            except ValueError:
                pid = None
        elif pid is not None and line.startswith("n"):
            endpoint = line[1:]
            if "->" in endpoint:
                continue
            match = re.search(r"(?:127\.0\.0\.1|localhost|\*)[:.](\d+)$", endpoint)
            if match:
                listeners.append((pid, int(match.group(1))))
    return listeners


def _find_running_project_preview(project_dir: Path) -> dict[str, Any] | None:
    seen_ports: set[int] = set()
    for pid, port in _list_loopback_listeners():
        if port in seen_ports:
            continue
        cwd = _process_cwd(pid)
        if not _path_is_inside(cwd, project_dir):
            continue
        url = f"http://127.0.0.1:{port}"
        if not _probe_preview_url(url):
            continue
        seen_ports.add(port)
        return {
            "kind": "existing",
            "command": None,
            "url": url,
            "port": port,
            "process": None,
            "auto_refresh": False,
            "auto_verify": True,
        }
    return None


def _detect_preview(project_dir: Path, requested_command: str | None = None, requested_url: str | None = None) -> dict[str, Any]:
    port = _find_free_loopback_port()
    config_path = project_dir / "spark.preview.json"
    config: dict[str, Any] = {}
    if config_path.exists():
        try:
            loaded = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                config = loaded
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid spark.preview.json: {exc}")
    requested_command = requested_command or config.get("command")
    requested_url = requested_url or config.get("url")
    requested_url = _normalize_browser_url(requested_url) if requested_url else None
    if requested_url and _is_loopback_url(requested_url) and _probe_preview_url(requested_url):
        parsed = urllib.parse.urlparse(requested_url)
        return {
            "kind": "existing",
            "command": None,
            "url": requested_url,
            "port": int(parsed.port or 80),
            "process": None,
            "auto_refresh": False,
            "auto_verify": bool(config.get("autoVerify", True)),
        }
    existing = _find_running_project_preview(project_dir)
    if existing and not requested_command:
        return existing
    if requested_command:
        return {
            "kind": "custom",
            "command": requested_command,
            "url": requested_url or f"http://127.0.0.1:{port}",
            "port": port,
            "auto_refresh": bool(config.get("autoRefresh", True)),
            "auto_verify": bool(config.get("autoVerify", True)),
        }

    package_json = project_dir / "package.json"
    if package_json.exists():
        try:
            package = json.loads(package_json.read_text(encoding="utf-8"))
        except Exception:
            package = {}
        scripts = package.get("scripts") if isinstance(package, dict) else {}
        if isinstance(scripts, dict):
            for script in ("dev", "start", "serve", "preview"):
                if script in scripts:
                    return {
                        "kind": "node",
                        "command": f"npm run {script} -- --host 127.0.0.1 --port {port}",
                        "url": requested_url or f"http://127.0.0.1:{port}",
                        "port": port,
                        "auto_refresh": False,
                        "auto_verify": bool(config.get("autoVerify", True)),
                    }

    if (project_dir / "index.html").exists() or (project_dir / "public" / "index.html").exists():
        serve_dir = project_dir if (project_dir / "index.html").exists() else project_dir / "public"
        return {
            "kind": "static",
            "command": f"{shutil.which('python3') or shutil.which('python') or 'python3'} -m http.server {port} --bind 127.0.0.1",
            "url": requested_url or f"http://127.0.0.1:{port}",
            "port": port,
            "cwd": serve_dir,
            "auto_refresh": bool(config.get("autoRefresh", True)),
            "auto_verify": bool(config.get("autoVerify", True)),
        }

    raise HTTPException(status_code=404, detail="No previewable webapp detected")


def _stop_preview_session(slug: str) -> dict[str, Any]:
    session = _preview_sessions.get(slug)
    if not session:
        return _preview_status_payload(slug)
    proc = session.get("process")
    if proc is not None and proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except Exception:
            proc.terminate()
    session["status"] = "stopped"
    session["updated_at"] = time.time()
    _preview_emit(slug, {"type": "state", **_preview_status_payload(slug, session)})
    return _preview_status_payload(slug, session)


def _cleanup_preview_sessions() -> None:
    for slug in list(_preview_sessions):
        try:
            _stop_preview_session(slug)
        except Exception:
            pass


def _run_preview_process(slug: str, session: dict[str, Any]) -> None:
    proc: subprocess.Popen | None = session.get("process")
    try:
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            _append_preview_log(slug, session, line)
        exit_code = proc.wait()
        with _preview_lock:
            if session.get("status") == "running":
                session["status"] = "failed" if exit_code else "stopped"
                session["error"] = None if exit_code == 0 else f"Preview process exited with code {exit_code}"
            session["updated_at"] = time.time()
        _preview_emit(slug, {"type": "state", **_preview_status_payload(slug, session)})
    except Exception as exc:
        with _preview_lock:
            session["status"] = "failed"
            session["error"] = str(exc)
            session["updated_at"] = time.time()
        _append_preview_log(slug, session, f"{exc}\n", "error")
        _preview_emit(slug, {"type": "state", **_preview_status_payload(slug, session)})


def _snapshot_project_files(project_dir: Path) -> dict[str, float]:
    snapshot: dict[str, float] = {}
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in _PREVIEW_IGNORED_DIRS and not d.startswith(".pytest")]
        root_path = Path(root)
        for name in files:
            path = root_path / name
            try:
                rel = str(path.relative_to(project_dir))
                snapshot[rel] = path.stat().st_mtime
            except OSError:
                continue
    return snapshot


def _watch_preview_files(slug: str, session: dict[str, Any]) -> None:
    project_dir = Path(session["project_dir"])
    previous = _snapshot_project_files(project_dir)
    last_refresh = 0.0
    while session.get("status") == "running":
        time.sleep(_PREVIEW_WATCH_INTERVAL_SECONDS)
        current = _snapshot_project_files(project_dir)
        if current != previous:
            previous = current
            now = time.time()
            if session.get("auto_refresh") and now - last_refresh >= _PREVIEW_REFRESH_DEBOUNCE_SECONDS:
                last_refresh = now
                event = {"type": "refresh", "ts": now, "reason": "file_change"}
                _preview_emit(slug, event)
                _publish_workspace_event("workspace.preview.refresh", {"slug": slug, **event})


@router.get("/projects/{slug}/preview/status")
def get_preview_status(slug: str):
    _project_dir(slug)
    return _preview_status_payload(slug)


@router.post("/projects/{slug}/preview/start")
def start_preview(slug: str, body: PreviewStart | None = None):
    project_dir = _project_dir(slug)
    existing = _preview_sessions.get(slug)
    if existing and existing.get("status") == "running":
        return _preview_status_payload(slug, existing)

    detected = _detect_preview(project_dir, body.command if body else None, body.url if body else None)
    cwd = Path(detected.get("cwd") or project_dir)
    command = str(detected["command"]) if detected.get("command") else None
    env = {**os.environ, "HOST": "127.0.0.1", "PORT": str(detected["port"])}
    session = {
        "slug": slug,
        "status": "starting",
        "url": detected["url"],
        "command": command,
        "port": detected["port"],
        "kind": detected["kind"],
        "error": None,
        "process": detected.get("process"),
        "logs": [],
        "project_dir": str(project_dir),
        "auto_refresh": detected.get("auto_refresh", True),
        "auto_verify": detected.get("auto_verify", True),
        "started_at": time.time(),
        "updated_at": time.time(),
    }
    _preview_sessions[slug] = session
    _preview_emit(slug, {"type": "state", **_preview_status_payload(slug, session)})

    if command is None:
        session["status"] = "running"
        session["updated_at"] = time.time()
        _append_preview_log(slug, session, f"Using existing app at {session['url']}\n", "server")
        browser_result = _run_agent_browser(slug, ["open", str(session["url"])])
        if browser_result and browser_result.get("success"):
            _append_preview_log(slug, session, f"agent-browser opened {session['url']}", "browser")
        elif browser_result:
            _append_preview_log(slug, session, f"agent-browser unavailable: {browser_result.get('error')}", "error")
        ready_payload = {"type": "state", **_preview_status_payload(slug, session)}
        _preview_emit(slug, ready_payload)
        _publish_workspace_event("workspace.preview.ready", ready_payload)
        return _preview_status_payload(slug, session)

    try:
        proc = subprocess.Popen(
            [os.environ.get("SHELL") or "/bin/bash", "-lc", command],
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            errors="replace",
            env=env,
            start_new_session=True,
        )
        session["process"] = proc
        session["status"] = "running"
        session["updated_at"] = time.time()
        _append_preview_log(slug, session, f"$ {command}\n")
        browser_result = _run_agent_browser(slug, ["open", str(session["url"])])
        if browser_result and browser_result.get("success"):
            _append_preview_log(slug, session, f"agent-browser opened {session['url']}", "browser")
        elif browser_result:
            _append_preview_log(slug, session, f"agent-browser unavailable: {browser_result.get('error')}", "error")
        ready_payload = {"type": "state", **_preview_status_payload(slug, session)}
        _preview_emit(slug, ready_payload)
        _publish_workspace_event("workspace.preview.ready", ready_payload)
        threading.Thread(target=_run_preview_process, args=(slug, session), daemon=True).start()
        threading.Thread(target=_watch_preview_files, args=(slug, session), daemon=True).start()
    except Exception as exc:
        session["status"] = "failed"
        session["error"] = str(exc)
        session["updated_at"] = time.time()
        _append_preview_log(slug, session, f"{exc}\n", "error")
        _preview_emit(slug, {"type": "state", **_preview_status_payload(slug, session)})
        raise HTTPException(status_code=500, detail=str(exc))

    return _preview_status_payload(slug, session)


@router.post("/projects/{slug}/preview/stop")
def stop_preview(slug: str):
    _project_dir(slug)
    return _stop_preview_session(slug)


@router.post("/projects/{slug}/preview/restart")
def restart_preview(slug: str, body: PreviewStart | None = None):
    _project_dir(slug)
    _stop_preview_session(slug)
    return start_preview(slug, body)


@router.post("/projects/{slug}/preview/navigate")
def navigate_preview(slug: str, body: PreviewNavigate):
    _project_dir(slug)
    url = _normalize_browser_url(body.url)
    session = _preview_sessions.get(slug)
    if not session:
        session = {
            "slug": slug,
            "status": "running",
            "url": url,
            "command": None,
            "port": None,
            "kind": "browser",
            "error": None,
            "process": None,
            "logs": [],
            "project_dir": str(_project_dir(slug)),
            "auto_refresh": False,
            "auto_verify": True,
            "started_at": None,
            "updated_at": time.time(),
        }
        _preview_sessions[slug] = session
    else:
        session["url"] = url
        if not _is_loopback_url(url) or session.get("kind") in {None, "manual"}:
            session["kind"] = "browser"
        if session.get("process") is None:
            session["status"] = "running"
        session["updated_at"] = time.time()
    browser_result = _run_agent_browser(slug, ["open", url])
    if browser_result and browser_result.get("success"):
        _append_preview_log(slug, session, f"agent-browser opened {url}", "browser")
    elif browser_result:
        _append_preview_log(slug, session, f"agent-browser unavailable: {browser_result.get('error')}", "error")
    _preview_emit(slug, {"type": "state", **_preview_status_payload(slug, session)})
    return _preview_status_payload(slug, session)


@router.post("/projects/{slug}/preview/refresh")
def refresh_preview(slug: str):
    _project_dir(slug)
    event = {"type": "refresh", "ts": time.time()}
    _preview_emit(slug, event)
    return {"ok": True, "slug": slug}


@router.get("/projects/{slug}/preview/logs")
def get_preview_logs(slug: str):
    _project_dir(slug)
    session = _preview_sessions.get(slug)
    return {"slug": slug, "logs": list(session.get("logs", [])) if session else []}


def _get_preview_session_or_404(slug: str) -> dict[str, Any]:
    _project_dir(slug)
    session = _preview_sessions.get(slug)
    if not session or not session.get("url"):
        raise HTTPException(status_code=404, detail="Preview session not found")
    return session


def _fetch_preview_html(session: dict[str, Any]) -> str:
    url = _normalize_browser_url(str(session["url"]))
    last_error: Exception | None = None
    attempts = 20 if urllib.parse.urlparse(url).hostname in {"127.0.0.1", "localhost"} else 1
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                return resp.read(_PREVIEW_FETCH_MAX_BYTES).decode("utf-8", errors="replace")
        except Exception as exc:
            last_error = exc
            time.sleep(0.05)
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            return resp.read(_PREVIEW_FETCH_MAX_BYTES).decode("utf-8", errors="replace")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Preview fetch failed: {last_error or exc}")


@router.get("/projects/{slug}/preview/snapshot")
def get_preview_snapshot(slug: str):
    session = _get_preview_session_or_404(slug)
    agent_result = _run_agent_browser(slug, ["snapshot", "--compact", "--depth", "6"])
    if agent_result and agent_result.get("success"):
        text = _agent_browser_text(agent_result)
        if text and "(empty page)" not in text:
            return {
                "slug": slug,
                "url": session.get("url"),
                "title": "",
                "text": text[:12000],
                "html_length": None,
                "source": "agent-browser",
            }
    elif agent_result:
        _append_preview_log(slug, session, f"agent-browser snapshot unavailable: {agent_result.get('error')}", "error")
    html = _fetch_preview_html(session)
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return {
        "slug": slug,
        "url": session.get("url"),
        "title": title_match.group(1).strip() if title_match else "",
        "text": text[:12000],
        "html_length": len(html),
        "source": "fetch",
    }


@router.get("/projects/{slug}/preview/console")
def get_preview_console(slug: str):
    session = _get_preview_session_or_404(slug)
    agent_result = _run_agent_browser(slug, ["console"])
    if agent_result and agent_result.get("success"):
        text = _agent_browser_text(agent_result)
        if text:
            _append_preview_log(slug, session, text[:12000], "console")
    logs = [
        item for item in session.get("logs", [])
        if item.get("stream") in {"browser", "console", "network", "error", "server"}
    ]
    return {"slug": slug, "messages": logs[-200:]}


@router.get("/projects/{slug}/preview/screenshot")
def get_preview_screenshot(slug: str):
    session = _get_preview_session_or_404(slug)
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError:
        raise HTTPException(status_code=501, detail="Playwright is not installed")
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto(str(session["url"]), wait_until="networkidle", timeout=8000)
            png = page.screenshot(full_page=True)
            browser.close()
        return StreamingResponse(iter([png]), media_type="image/png")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Screenshot failed: {exc}")


def _run_playwright_action(slug: str, action: str, body: PreviewBrowserAction | None = None) -> dict[str, Any]:
    session = _get_preview_session_or_404(slug)
    body = body or PreviewBrowserAction()
    agent_args: list[str] | None = None
    if action == "click":
        if not body.selector:
            raise HTTPException(status_code=400, detail="selector is required")
        agent_args = ["click", body.selector]
    elif action == "type":
        if not body.selector:
            raise HTTPException(status_code=400, detail="selector is required")
        agent_args = ["fill", body.selector, body.text or ""]
    elif action == "evaluate":
        if not body.expression:
            raise HTTPException(status_code=400, detail="expression is required")
        agent_args = ["eval", body.expression]
    elif action == "snapshot":
        agent_args = ["snapshot", "--compact", "--depth", "6"]

    if agent_args:
        agent_result = _run_agent_browser(slug, agent_args)
        if agent_result and agent_result.get("success"):
            text = _agent_browser_text(agent_result)
            if text:
                _append_preview_log(slug, session, text[:12000], "browser")
            return {
                "slug": slug,
                "action": action,
                "result": agent_result.get("data"),
                "messages": [],
                "source": "agent-browser",
            }
        if agent_result:
            _append_preview_log(slug, session, f"agent-browser {action} unavailable: {agent_result.get('error')}", "error")
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError:
        raise HTTPException(status_code=501, detail="Playwright is not installed")
    messages: list[dict[str, Any]] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.on("console", lambda msg: messages.append({"stream": "console", "text": msg.text, "ts": time.time(), "type": "log"}))
            page.on("pageerror", lambda err: messages.append({"stream": "error", "text": str(err), "ts": time.time(), "type": "log"}))
            page.on("requestfailed", lambda req: messages.append({"stream": "network", "text": req.url, "ts": time.time(), "type": "log"}))
            page.goto(str(session["url"]), wait_until="domcontentloaded", timeout=8000)
            result: Any = None
            if action == "click":
                if not body.selector:
                    raise HTTPException(status_code=400, detail="selector is required")
                page.locator(body.selector).first.click(timeout=5000)
            elif action == "type":
                if not body.selector:
                    raise HTTPException(status_code=400, detail="selector is required")
                page.locator(body.selector).first.fill(body.text or "", timeout=5000)
            elif action == "evaluate":
                if not body.expression:
                    raise HTTPException(status_code=400, detail="expression is required")
                result = page.evaluate(body.expression)
            elif action == "snapshot":
                result = {
                    "title": page.title(),
                    "url": page.url,
                    "text": page.locator("body").inner_text(timeout=5000)[:12000],
                }
            for msg in messages:
                _append_preview_log(slug, session, msg["text"], msg["stream"])
            browser.close()
        return {"slug": slug, "action": action, "result": result, "messages": messages[-100:]}
    except HTTPException:
        raise
    except Exception as exc:
        _append_preview_log(slug, session, str(exc), "error")
        raise HTTPException(status_code=502, detail=f"Browser action failed: {exc}")


@router.post("/projects/{slug}/preview/click")
def preview_click(slug: str, body: PreviewBrowserAction):
    return _run_playwright_action(slug, "click", body)


@router.post("/projects/{slug}/preview/type")
def preview_type(slug: str, body: PreviewBrowserAction):
    return _run_playwright_action(slug, "type", body)


@router.post("/projects/{slug}/preview/evaluate")
def preview_evaluate(slug: str, body: PreviewBrowserAction):
    return _run_playwright_action(slug, "evaluate", body)


@router.get("/projects/{slug}/preview/events")
async def stream_preview_events(request: Request, slug: str):
    _project_dir(slug)
    q: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=512)
    _preview_queues.setdefault(slug, []).append(q)

    async def event_generator():
        try:
            yield f"data: {json.dumps({'type': 'state', **_preview_status_payload(slug)}, default=str)}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.to_thread(q.get, True, 20)
                except queue.Empty:
                    yield "event: ping\ndata: {}\n\n"
                    continue
                if event is None:
                    break
                yield f"data: {json.dumps(event, default=str)}\n\n"
        finally:
            queues = _preview_queues.get(slug)
            if queues and q in queues:
                queues.remove(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def register_workspace_routes(app) -> None:
    app.include_router(router)


atexit.register(_cleanup_preview_sessions)
