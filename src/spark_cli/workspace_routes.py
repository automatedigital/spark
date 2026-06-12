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
import ipaddress
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
# How long to wait for a freshly launched dev server to answer an HTTP probe
# before we surface it as ready. Dev servers (Vite, Next, etc.) can take a few
# seconds to compile on first boot, so keep this generous.
_PREVIEW_READY_TIMEOUT_SECONDS = 45.0
_PREVIEW_READY_POLL_INTERVAL_SECONDS = 0.5
_PREVIEW_FETCH_MAX_BYTES = 512 * 1024
_AGENT_BROWSER_MAX_OUTPUT = 12000
_PREVIEW_IGNORED_DIRS = {
    ".git", ".next", ".vite", "__pycache__", "build", "dist", "node_modules", ".cache"
}
_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|authorization|bearer|password|secret|token)([\"'\s:=]+)([^\s\"']+)"
)
_PREVIEW_URL_RE = re.compile(r"https?://[^\s<>()\"']+")

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
    port: int | None = None


class PreviewNavigate(BaseModel):
    url: str


class PreviewBrowserAction(BaseModel):
    selector: str | None = None
    text: str | None = None
    expression: str | None = None


class StreamNavigate(BaseModel):
    url: str
    persistent: bool = True


class StreamInput(BaseModel):
    type: str  # click | scroll | type | key | back | forward
    x: float | None = None
    y: float | None = None
    dx: float | None = None
    dy: float | None = None
    text: str | None = None
    key: str | None = None


class StreamLog(BaseModel):
    text: str
    stream: str = "console"  # console | network | error


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
    _publish_workspace_event("workspace.files.changed", {"slug": slug})
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


class RenameBody(BaseModel):
    src: str
    dst: str


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
    _publish_workspace_event("workspace.files.changed", {"slug": slug})
    return {"ok": True, "deleted": path}


@router.put("/projects/{slug}/file")
def write_project_file(slug: str, path: str = Query(...), body: WriteFileBody = ...):
    """Create or overwrite a text file inside a project workspace."""
    project_dir = _project_dir(slug)
    target = _safe_path(project_dir, path)
    if target.is_dir():
        raise HTTPException(status_code=400, detail="Path is a directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.write_text(body.content, encoding="utf-8")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    _publish_workspace_event("workspace.files.changed", {"slug": slug})
    return {"ok": True, "path": path}


@router.post("/projects/{slug}/mkdir")
def make_project_dir(slug: str, path: str = Query(...)):
    """Create a directory (and parents) inside a project workspace."""
    project_dir = _project_dir(slug)
    target = _safe_path(project_dir, path)
    if target.exists():
        raise HTTPException(status_code=409, detail=f"Already exists: {path!r}")
    try:
        target.mkdir(parents=True)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    _publish_workspace_event("workspace.files.changed", {"slug": slug})
    return {"ok": True, "path": path}


@router.post("/projects/{slug}/rename")
def rename_project_path(slug: str, body: RenameBody):
    """Rename or move a file/directory inside a project workspace."""
    project_dir = _project_dir(slug)
    src = _safe_path(project_dir, body.src)
    dst = _safe_path(project_dir, body.dst)
    if not src.exists():
        raise HTTPException(status_code=404, detail=f"Not found: {body.src!r}")
    if dst.exists():
        raise HTTPException(status_code=409, detail=f"Already exists: {body.dst!r}")
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    _publish_workspace_event("workspace.files.changed", {"slug": slug})
    return {"ok": True, "src": body.src, "dst": body.dst}


# ── Project git (Changes tab) ──────────────────────────────────────────────────


class RevertBody(BaseModel):
    path: str


def _run_git(project_dir: Path, args: list[str], timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(project_dir),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _is_git_repo(project_dir: Path) -> bool:
    try:
        res = _run_git(project_dir, ["rev-parse", "--is-inside-work-tree"])
    except (FileNotFoundError, subprocess.SubprocessError):
        return False
    return res.returncode == 0 and res.stdout.strip() == "true"


def _git_category(index: str, work: str) -> str:
    """Map a porcelain XY status pair to added/deleted/modified."""
    if index == "?" or work == "?":
        return "added"
    if index == "A":
        return "added"
    if index == "D" or work == "D":
        return "deleted"
    return "modified"


@router.get("/projects/{slug}/git/status")
def git_status(slug: str):
    """Return branch + per-file change summary for a project that is a git repo.

    Non-git workspaces report `is_repo: false` so the UI can hide the tab.
    """
    project_dir = _project_dir(slug)
    if not _is_git_repo(project_dir):
        return {"is_repo": False, "branch": None, "files": [], "total_adds": 0, "total_dels": 0}

    branch_res = _run_git(project_dir, ["rev-parse", "--abbrev-ref", "HEAD"])
    branch = branch_res.stdout.strip() or None

    # Per-file +adds/-dels for tracked changes vs HEAD.
    numstat: dict[str, tuple[int | None, int | None]] = {}
    num_res = _run_git(project_dir, ["diff", "--numstat", "HEAD"])
    if num_res.returncode == 0:
        for line in num_res.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            adds_s, dels_s, path = parts
            adds = None if adds_s == "-" else int(adds_s)
            dels = None if dels_s == "-" else int(dels_s)
            numstat[path] = (adds, dels)

    files: list[dict[str, Any]] = []
    total_adds = 0
    total_dels = 0
    status_res = _run_git(project_dir, ["status", "--porcelain"])
    for line in status_res.stdout.splitlines():
        if len(line) < 3:
            continue
        index, work, path = line[0], line[1], line[3:]
        # Renames look like "old -> new"; report the new path.
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.strip().strip('"')
        category = _git_category(index, work)
        adds, dels = numstat.get(path, (None, None))
        # Untracked files have no numstat entry: count their lines as additions.
        if adds is None and dels is None and (index == "?" or work == "?"):
            target = project_dir / path
            try:
                if target.is_file():
                    adds = sum(1 for _ in target.open("rb"))
                    dels = 0
            except OSError:
                pass
        total_adds += adds or 0
        total_dels += dels or 0
        files.append({"path": path, "status": category, "adds": adds, "dels": dels})

    files.sort(key=lambda f: f["path"])
    return {
        "is_repo": True,
        "branch": branch,
        "files": files,
        "total_adds": total_adds,
        "total_dels": total_dels,
    }


@router.get("/projects/{slug}/git/diff")
def git_diff(slug: str, path: str = Query(default="")):
    """Unified diff vs HEAD — for one file, or the whole worktree when path is empty."""
    project_dir = _project_dir(slug)
    if not _is_git_repo(project_dir):
        raise HTTPException(status_code=400, detail="Not a git repository")

    if path:
        _safe_path(project_dir, path)  # reject traversal
        # Tracked changes vs HEAD.
        res = _run_git(project_dir, ["diff", "HEAD", "--", path])
        diff = res.stdout
        # Untracked files have no HEAD entry; synthesize an add-diff.
        if not diff.strip():
            untracked = _run_git(project_dir, ["ls-files", "--others", "--exclude-standard", "--", path])
            if untracked.stdout.strip():
                nores = _run_git(project_dir, ["diff", "--no-index", "--", os.devnull, path])
                diff = nores.stdout
        return {"path": path, "diff": diff}

    res = _run_git(project_dir, ["diff", "HEAD"])
    return {"path": None, "diff": res.stdout}


@router.post("/projects/{slug}/git/revert")
def git_revert(slug: str, body: RevertBody):
    """Discard uncommitted changes to one file (checkout for tracked, delete for untracked)."""
    project_dir = _project_dir(slug)
    if not _is_git_repo(project_dir):
        raise HTTPException(status_code=400, detail="Not a git repository")
    target = _safe_path(project_dir, body.path)

    tracked = _run_git(project_dir, ["ls-files", "--error-unmatch", "--", body.path])
    if tracked.returncode == 0:
        res = _run_git(project_dir, ["checkout", "HEAD", "--", body.path])
        if res.returncode != 0:
            raise HTTPException(status_code=500, detail=res.stderr.strip() or "git checkout failed")
    elif target.exists():
        try:
            target.unlink()
        except OSError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
    _publish_workspace_event("workspace.files.changed", {"slug": slug})
    return {"ok": True, "reverted": body.path}


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


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
        return True


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
        "--profile",
        str(get_spark_home() / "browser" / re.sub(r"[^a-zA-Z0-9_.-]", "-", slug) / "persistent"),
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


def _is_local_preview_host(host: str | None) -> bool:
    if not host:
        return False
    normalized = host.strip("[]").lower()
    if normalized in {"localhost", "0.0.0.0"}:
        return True
    if "." not in normalized:
        return True
    try:
        ip = ipaddress.ip_address(normalized)
        return ip.is_loopback or ip.is_private or ip.is_link_local
    except ValueError:
        return normalized.endswith(".local")


_WILDCARD_HOSTS = {"0.0.0.0", "::", "[::]", "localhost", "::1", "[::1]"}


def _canonical_probe_url(url: str) -> str:
    """Rewrite non-routable / wildcard bind hosts to a reachable loopback host.

    Dev servers commonly advertise ``0.0.0.0``, ``::``, ``localhost`` or ``::1``;
    a browser/iframe needs a concrete reachable host, so collapse them all to
    ``127.0.0.1`` while preserving port, path, and query.
    """
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if host in _WILDCARD_HOSTS or f"[{host}]" in _WILDCARD_HOSTS:
        netloc = f"127.0.0.1:{parsed.port}" if parsed.port else "127.0.0.1"
        return urllib.parse.urlunparse(parsed._replace(netloc=netloc))
    return url


def _probe_preview_url(url: str) -> bool:
    try:
        with urllib.request.urlopen(_canonical_probe_url(url), timeout=0.8) as resp:
            return 200 <= int(resp.status) < 500
    except Exception:
        return False


def _loopback_probe_url(url: str) -> str:
    """Force *url*'s host to loopback so the server always probes itself locally,
    regardless of the (possibly public) host advertised to the client."""
    parsed = urllib.parse.urlparse(url)
    if parsed.port is None:
        return _canonical_probe_url(url)
    return urllib.parse.urlunparse(parsed._replace(netloc=f"127.0.0.1:{parsed.port}"))


def _client_facing_preview_url(url: str) -> str:
    """Rewrite a dev-server URL to a host the *WebUI client* can reach.

    The server always probes on loopback (see ``_canonical_probe_url``), but the
    URL we advertise to the browser must be reachable from where that browser
    runs:

    * **Desktop / local** → keep ``127.0.0.1`` (the default); the native webview
      and a same-machine browser both reach loopback fine.
    * **VPS / server** (``dashboard.public_url`` set, or a server environment) →
      swap loopback/wildcard for ``dashboard.public_url``'s host or the machine
      hostname, so a remote browser can actually load the dev server.

    Only the host is rewritten; the dev server's own port/path/query are kept.
    """
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    # Only loopback and wildcard binds are non-routable for a remote client. A
    # concrete LAN/public host (private IP, hostname, .local) is already
    # reachable, so leave it untouched.
    _loopback = {"127.0.0.1", "localhost", "::1"}
    if host not in _loopback and host not in _WILDCARD_HOSTS:
        return url
    port = parsed.port
    if port is None:
        return _canonical_probe_url(url)
    try:
        from core.spark_constants import (
            get_public_base_url,
            get_server_hostname,
            is_server_environment,
        )
    except Exception:
        return _canonical_probe_url(url)

    # In a server environment, derive the externally reachable host. We reuse
    # get_public_base_url for the dashboard's own host then graft the dev
    # server's port onto it (the dashboard URL points at the dashboard port).
    if not is_server_environment():
        return _canonical_probe_url(url)
    try:
        base = get_public_base_url("0.0.0.0", port, parsed.scheme or "http")
        base_host = urllib.parse.urlparse(base).hostname or get_server_hostname()
    except Exception:
        base_host = get_server_hostname()
    netloc = f"{base_host}:{port}"
    return urllib.parse.urlunparse(parsed._replace(netloc=netloc))


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


def _extract_preview_urls(text: str | None) -> list[str]:
    if not text:
        return []
    urls: list[str] = []
    for raw in _PREVIEW_URL_RE.findall(text):
        candidate = raw.rstrip(".,;:)]}'\"")
        try:
            url = _normalize_browser_url(candidate)
        except HTTPException:
            continue
        parsed = urllib.parse.urlparse(url)
        if parsed.port and _is_local_preview_host(parsed.hostname):
            urls.append(url)
    return urls


def _message_text_parts(message: dict[str, Any]) -> list[str]:
    parts: list[str] = []
    for key in ("content", "reasoning"):
        value = message.get(key)
        if isinstance(value, str):
            parts.append(value)
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        for call in tool_calls:
            if isinstance(call, dict):
                parts.append(json.dumps(call, default=str))
    return parts


def _preview_state_file() -> Path:
    return get_spark_home() / "workspace-preview-state.json"


def _remember_last_url(slug: str, url: str) -> None:
    """Persist the last URL visited in a project's preview, keyed by slug."""
    path = _preview_state_file()
    try:
        state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if not isinstance(state, dict):
            state = {}
    except Exception:
        state = {}
    state[slug] = {"url": url, "ts": time.time()}
    try:
        path.write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        _log.debug("failed to persist preview last-url slug=%s", slug, exc_info=True)


def _recall_last_url(slug: str) -> str | None:
    path = _preview_state_file()
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        entry = state.get(slug) if isinstance(state, dict) else None
        if isinstance(entry, dict):
            url = entry.get("url")
            return url if isinstance(url, str) else None
    except Exception:
        return None
    return None


def _find_remembered_preview(project_dir: Path, slug: str) -> dict[str, Any] | None:
    # Prefer an explicitly remembered last-visited URL that still responds.
    last_url = _recall_last_url(slug)
    if last_url and _probe_preview_url(last_url):
        parsed = urllib.parse.urlparse(last_url)
        return {
            "kind": "remembered",
            "command": None,
            "url": last_url,
            "port": int(parsed.port or (443 if parsed.scheme == "https" else 80)),
            "process": None,
            "auto_refresh": False,
            "auto_verify": True,
        }
    return _find_remembered_preview_from_history(project_dir, slug)


def _find_remembered_preview_from_history(project_dir: Path, slug: str) -> dict[str, Any] | None:
    try:
        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            sessions = db.list_sessions_rich(source=f"workspace:{slug}", limit=8, include_children=True)
            seen: set[str] = set()
            for session in sessions:
                leaf_id = db.resolve_latest_descendant(session["id"])
                for message in reversed(db.get_messages(leaf_id)):
                    for part in _message_text_parts(message):
                        for url in _extract_preview_urls(part):
                            if url in seen:
                                continue
                            seen.add(url)
                            if not _probe_preview_url(url):
                                continue
                            parsed = urllib.parse.urlparse(url)
                            return {
                                "kind": "remembered",
                                "command": None,
                                "url": url,
                                "port": int(parsed.port or 80),
                                "process": None,
                                "auto_refresh": False,
                                "auto_verify": True,
                            }
        finally:
            db.close()
    except Exception:
        _log.debug("workspace remembered preview lookup failed slug=%s", slug, exc_info=True)
    return None


_PORT_CONFIG_FILES = (
    "vite.config.js", "vite.config.ts", "vite.config.mjs",
    "next.config.js", "next.config.ts", "next.config.mjs",
    ".env", ".env.local", ".env.development",
    "Procfile",
)
_PORT_RE_PATTERNS = (
    re.compile(r"(?im)^\s*PORT\s*[:=]\s*[\"']?(\d{2,5})"),
    re.compile(r"(?i)\bport\s*[:=]\s*(\d{2,5})"),
    re.compile(r"(?i)--port[=\s]+(\d{2,5})"),
    re.compile(r"(?i)-p\s+(\d{2,5})"),
)


def _valid_port(value: int) -> bool:
    return 1 <= value <= 65535


def _scan_text_for_port(text: str) -> int | None:
    for pattern in _PORT_RE_PATTERNS:
        match = pattern.search(text)
        if match:
            port = int(match.group(1))
            if _valid_port(port):
                return port
    return None


def _declared_project_port(project_dir: Path) -> int | None:
    """Best-effort parse of the project's own config for a declared dev port.

    Checks (in order) vite/next config, .env ``PORT=``, Procfile, the
    ``scripts`` block of package.json, and docker-compose published ports.
    Returns the first plausible port, or None to fall back to the free-port scan.
    """
    for name in _PORT_CONFIG_FILES:
        path = project_dir / name
        if not path.exists() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")[:_MAX_FILE_READ_BYTES]
        except OSError:
            continue
        port = _scan_text_for_port(text)
        if port is not None:
            return port

    package_json = project_dir / "package.json"
    if package_json.exists():
        try:
            package = json.loads(package_json.read_text(encoding="utf-8"))
            scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
            for script in ("dev", "start", "serve", "preview"):
                cmd = scripts.get(script) if isinstance(scripts, dict) else None
                if isinstance(cmd, str):
                    port = _scan_text_for_port(cmd)
                    if port is not None:
                        return port
        except Exception:
            pass

    for compose_name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        compose = project_dir / compose_name
        if not compose.exists():
            continue
        try:
            text = compose.read_text(encoding="utf-8", errors="ignore")[:_MAX_FILE_READ_BYTES]
        except OSError:
            continue
        match = re.search(r"(?m)-\s*[\"']?(\d{2,5}):\d{2,5}", text)
        if match:
            port = int(match.group(1))
            if _valid_port(port):
                return port
    return None


def _detect_preview(
    project_dir: Path,
    requested_command: str | None = None,
    requested_url: str | None = None,
    slug: str | None = None,
) -> dict[str, Any]:
    """Resolve how to preview a project, in strict precedence order:

    1. ``spark.preview.json`` — explicit ``command``/``url`` override (also
       supplies ``autoRefresh``/``autoVerify`` defaults). An explicit/config
       ``url`` that is local and currently reachable short-circuits as
       ``kind="existing"`` (we attach to it, start nothing).
    2. Remembered URL — a local preview URL seen in this workspace's session
       history that still probes OK (``kind="remembered"``). Only consulted
       when no command/url was requested.
    3. Already-running server — a loopback listener whose process cwd is inside
       the project dir and that responds (``kind="existing"``). Skipped if a
       command was requested.
    4. Requested command — caller/config supplied a launch command
       (``kind="custom"``); we start it and assume the chosen free port.
    5. Declared project port — parsed from the project's own config
       (``vite.config``/``next.config``/``.env PORT=``/``package.json`` scripts,
       etc.) so we launch and attach on the port the project actually uses.
    6. ``package.json`` scripts — first of dev/start/serve/preview
       (``kind="node"``).
    7. Static ``index.html`` (root or ``public/``) served via
       ``python -m http.server`` (``kind="static"``).
    8. Otherwise HTTP 404 — nothing previewable detected.
    """
    port = _find_free_loopback_port()
    declared_port = _declared_project_port(project_dir)
    if declared_port is not None and _port_is_free(declared_port):
        port = declared_port
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
    if requested_url and _is_local_preview_host(urllib.parse.urlparse(requested_url).hostname) and _probe_preview_url(requested_url):
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
    remembered = _find_remembered_preview(project_dir, slug) if slug and not requested_command and not requested_url else None
    if remembered:
        return remembered
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


def _capture_bound_url_from_log(slug: str, session: dict[str, Any], line: str) -> None:
    """Adopt the real URL/port a dev server prints, if it differs from ours.

    Vite/Next/CRA print e.g. ``Local: http://127.0.0.1:5173/`` and may pick a
    different port than we requested (collision, fixed port in config). When we
    spot such a local URL, update the session and notify the client.
    """
    if session.get("port_locked"):
        return
    for url in _extract_preview_urls(line):
        parsed = urllib.parse.urlparse(url)
        bound_port = parsed.port
        if not bound_port or bound_port == session.get("port"):
            continue
        normalized = _canonical_probe_url(url)
        with _preview_lock:
            session["url"] = normalized
            session["port"] = bound_port
            session["updated_at"] = time.time()
        _preview_emit(slug, {"type": "state", **_preview_status_payload(slug, session)})
        _preview_emit(slug, {"type": "refresh", "ts": time.time(), "reason": "port_detected"})
        return


def _run_preview_process(slug: str, session: dict[str, Any]) -> None:
    proc: subprocess.Popen | None = session.get("process")
    try:
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            _append_preview_log(slug, session, line)
            _capture_bound_url_from_log(slug, session, line)
        exit_code = proc.wait()
        with _preview_lock:
            if session.get("status") in {"running", "starting"}:
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


def _await_preview_ready(slug: str, session: dict[str, Any]) -> None:
    """Poll the dev server until it answers, then flip status → ``running``.

    The session is created as ``starting``; we only advertise it as ``running``
    and emit ``workspace.preview.ready`` once an HTTP probe succeeds. This stops
    the WebUI/native pane from loading a URL that is still compiling (which shows
    a connection-refused error and never recovers on its own). On timeout the
    session is marked ``failed`` with a clear message.
    """
    deadline = time.time() + _PREVIEW_READY_TIMEOUT_SECONDS
    while time.time() < deadline:
        if session.get("status") != "starting":
            return  # stopped/failed elsewhere (e.g. process exited)
        proc = session.get("process")
        if proc is not None and proc.poll() is not None:
            # Process died before becoming reachable; _run_preview_process
            # will have set the failure state.
            return
        url = session.get("url")
        if url and _probe_preview_url(_loopback_probe_url(url)):
            with _preview_lock:
                if session.get("status") != "starting":
                    return
                session["status"] = "running"
                session["updated_at"] = time.time()
            _append_preview_log(slug, session, f"Preview ready at {url}\n", "server")
            browser_result = _run_agent_browser(slug, ["open", str(url)])
            if browser_result and browser_result.get("success"):
                _append_preview_log(slug, session, f"agent-browser opened {url}", "browser")
            elif browser_result:
                _append_preview_log(slug, session, f"agent-browser unavailable: {browser_result.get('error')}", "error")
            ready_payload = {"type": "state", **_preview_status_payload(slug, session)}
            _preview_emit(slug, ready_payload)
            _publish_workspace_event("workspace.preview.ready", ready_payload)
            threading.Thread(target=_watch_preview_files, args=(slug, session), daemon=True).start()
            return
        time.sleep(_PREVIEW_READY_POLL_INTERVAL_SECONDS)
    # Timed out waiting for the server to answer.
    with _preview_lock:
        if session.get("status") != "starting":
            return
        session["status"] = "failed"
        session["error"] = (
            f"Preview server did not respond at {session.get('url')} "
            f"within {int(_PREVIEW_READY_TIMEOUT_SECONDS)}s"
        )
        session["updated_at"] = time.time()
    _append_preview_log(slug, session, f"{session['error']}\n", "error")
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


def _reprobe_preview_port(slug: str, session: dict[str, Any], project_dir: Path) -> None:
    """If the current preview URL stopped responding, adopt the project's new port.

    Covers dev servers that restart on a different port (collision recovery,
    config change) without re-printing a URL we caught from stdout.
    """
    if session.get("port_locked"):
        return
    url = session.get("url")
    if url and _probe_preview_url(_loopback_probe_url(url)):
        return
    running = _find_running_project_preview(project_dir)
    if not running or running.get("port") == session.get("port"):
        return
    with _preview_lock:
        session["url"] = _client_facing_preview_url(running["url"])
        session["port"] = running["port"]
        session["updated_at"] = time.time()
    _preview_emit(slug, {"type": "state", **_preview_status_payload(slug, session)})
    _preview_emit(slug, {"type": "refresh", "ts": time.time(), "reason": "port_changed"})


def _watch_preview_files(slug: str, session: dict[str, Any]) -> None:
    project_dir = Path(session["project_dir"])
    previous = _snapshot_project_files(project_dir)
    last_refresh = 0.0
    cycles = 0
    while session.get("status") == "running":
        time.sleep(_PREVIEW_WATCH_INTERVAL_SECONDS)
        cycles += 1
        if cycles % 4 == 0:
            _reprobe_preview_port(slug, session, project_dir)
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

    override_port = body.port if body else None
    if override_port is not None and not _valid_port(override_port):
        raise HTTPException(status_code=400, detail=f"Invalid port: {override_port}")
    override_url = body.url if body else None
    if override_port is not None and not override_url:
        override_url = f"http://127.0.0.1:{override_port}"
    detected = _detect_preview(project_dir, body.command if body else None, override_url, slug)
    if override_port is not None:
        detected["url"] = f"http://127.0.0.1:{override_port}"
        detected["port"] = override_port
    cwd = Path(detected.get("cwd") or project_dir)
    command = str(detected["command"]) if detected.get("command") else None
    env = {**os.environ, "HOST": "127.0.0.1", "PORT": str(detected["port"])}
    session = {
        "slug": slug,
        "status": "starting",
        "url": _client_facing_preview_url(detected["url"]),
        "command": command,
        "port": detected["port"],
        "kind": detected["kind"],
        "error": None,
        "process": detected.get("process"),
        "logs": [],
        "project_dir": str(project_dir),
        "auto_refresh": detected.get("auto_refresh", True),
        "auto_verify": detected.get("auto_verify", True),
        "port_locked": override_port is not None,
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
        # Stay "starting" until an HTTP probe succeeds — see _await_preview_ready.
        session["status"] = "starting"
        session["updated_at"] = time.time()
        _append_preview_log(slug, session, f"$ {command}\n")
        _preview_emit(slug, {"type": "state", **_preview_status_payload(slug, session)})
        threading.Thread(target=_run_preview_process, args=(slug, session), daemon=True).start()
        # The file watcher is started by _await_preview_ready once the server
        # answers, so it never polls a server that isn't up yet.
        threading.Thread(target=_await_preview_ready, args=(slug, session), daemon=True).start()
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
    _remember_last_url(slug, url)
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


# ── Streamed server-side browser (WebUI path) ────────────────────────────────


def _emit_stream_log(slug: str, text: str, stream: str = "console") -> None:
    """Push a browser console/network line into the preview log SSE channel."""
    redacted = _SECRET_RE.sub(r"\1\2[redacted]", text)
    entry = {"ts": time.time(), "type": "log", "stream": stream, "text": redacted[:4000]}
    session = _preview_sessions.get(slug)
    if session is not None:
        with _preview_lock:
            logs = session.setdefault("logs", [])
            logs.append(entry)
            if len(logs) > _PREVIEW_LOG_LIMIT:
                del logs[: len(logs) - _PREVIEW_LOG_LIMIT]
    _preview_emit(slug, entry)


def _resolve_preview_backend() -> str:
    """Resolve the configured WebUI preview browser backend.

    Returns one of ``"agent-browser"`` or ``"playwright"`` after applying the
    ``display.preview_browser_backend`` flag and availability fallback:

      auto          -> agent-browser when available, else playwright
      agent-browser -> agent-browser (no fallback)
      playwright    -> playwright
    """
    try:
        from spark_cli.config import load_config

        flag = str(
            (load_config().get("display") or {}).get("preview_browser_backend", "auto")
        ).strip().lower()
    except Exception:
        flag = "auto"
    if flag == "playwright":
        return "playwright"
    if flag == "agent-browser":
        return "agent-browser"
    # auto (or any unknown value): prefer agent-browser when present.
    try:
        from spark_cli.preview_agent_browser import is_available

        if is_available():
            return "agent-browser"
    except Exception:
        pass
    return "playwright"


def _streamed_session(slug: str, *, persistent: bool = True):
    """Resolve the per-workspace streamed browser session, mapping errors to HTTP.

    Selects the agent-browser-backed session (shared with the agent's browser
    tools) or the Playwright ``StreamedBrowserSession`` based on
    ``display.preview_browser_backend`` + availability. Both satisfy the same
    session interface the streamed endpoints call.
    """
    _project_dir(slug)
    backend = _resolve_preview_backend()
    session: Any
    if backend == "agent-browser":
        try:
            from spark_cli.preview_agent_browser import (
                AgentBrowserUnavailable,
                get_agent_browser_session,
            )

            session = get_agent_browser_session(slug)
            return session, AgentBrowserUnavailable
        except HTTPException:
            raise
        except Exception as exc:
            # Missing agent-browser/Chromium -> surface the friendly install/error
            # state (501) to the pane rather than a hard 502.
            raise HTTPException(status_code=501, detail=str(exc)) from exc
    try:
        from spark_cli.preview_browser import BrowserUnavailable, get_streamed_session
    except Exception as exc:  # pragma: no cover - import guard
        raise HTTPException(status_code=501, detail=f"Streamed browser unavailable: {exc}")
    try:
        session = get_streamed_session(
            slug,
            persistent=persistent,
            on_log=lambda text, stream: _emit_stream_log(slug, text, stream),
        )
        return session, BrowserUnavailable
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Browser session failed: {exc}")


@router.post("/projects/{slug}/preview/stream/navigate")
async def stream_browser_navigate(slug: str, body: StreamNavigate):
    url = _normalize_browser_url(body.url)
    _remember_last_url(slug, url)
    session, browser_unavailable = _streamed_session(slug, persistent=body.persistent)
    try:
        result = await asyncio.to_thread(session.navigate, url)
    except browser_unavailable as exc:
        raise HTTPException(status_code=501, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Navigation failed: {exc}")
    return {"slug": slug, **result}


@router.get("/projects/{slug}/preview/stream/frame")
async def stream_browser_frame(slug: str):
    session, browser_unavailable = _streamed_session(slug)
    try:
        png = await asyncio.to_thread(session.screenshot)
    except browser_unavailable as exc:
        raise HTTPException(status_code=501, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Frame capture failed: {exc}")
    width, height = session.viewport
    return StreamingResponse(
        iter([png]),
        media_type="image/png",
        headers={
            "Cache-Control": "no-store",
            "X-Preview-Viewport": f"{width}x{height}",
        },
    )


@router.post("/projects/{slug}/preview/stream/input")
async def stream_browser_input(slug: str, body: StreamInput):
    session, browser_unavailable = _streamed_session(slug)

    def _apply() -> None:
        kind = body.type
        if kind == "click":
            session.click(body.x or 0, body.y or 0)
        elif kind == "scroll":
            session.scroll(body.dx or 0, body.dy or 0)
        elif kind == "type":
            session.type_text(body.text or "")
        elif kind == "key":
            session.press_key(body.key or "")
        elif kind == "back":
            session.go_back()
        elif kind == "forward":
            session.go_forward()
        else:
            raise HTTPException(status_code=400, detail=f"Unknown input type: {kind}")

    try:
        await asyncio.to_thread(_apply)
    except HTTPException:
        raise
    except browser_unavailable as exc:
        raise HTTPException(status_code=501, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Input failed: {exc}")
    return {"slug": slug, "ok": True, "url": session.current_url, "title": session.title}


@router.post("/projects/{slug}/preview/stream/stop")
def stream_browser_stop(slug: str):
    _project_dir(slug)
    from spark_cli.preview_agent_browser import close_agent_browser_session
    from spark_cli.preview_browser import close_streamed_session

    # Stop whichever backend(s) hold a live session for this workspace.
    stopped = close_streamed_session(slug)
    stopped = close_agent_browser_session(slug) or stopped
    return {"slug": slug, "stopped": stopped}


@router.get("/projects/{slug}/preview/stream/cookies")
async def stream_browser_cookies(slug: str):
    session, browser_unavailable = _streamed_session(slug)
    try:
        cookies = await asyncio.to_thread(session.cookies)
    except browser_unavailable as exc:
        raise HTTPException(status_code=501, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Cookie read failed: {exc}")
    return {"slug": slug, "cookies": cookies}


@router.post("/projects/{slug}/preview/stream/clear")
def stream_browser_clear(slug: str):
    _project_dir(slug)
    from spark_cli.preview_agent_browser import (
        clear_browsing_data as clear_agent_browser_data,
    )
    from spark_cli.preview_browser import clear_browsing_data

    # Both backends share the SPARK_HOME/browser/<slug> layout; clear both so a
    # backend switch can't leave a stale profile behind.
    cleared = clear_browsing_data(slug)
    cleared = clear_agent_browser_data(slug) or cleared
    return {"slug": slug, "cleared": cleared}


@router.get("/projects/{slug}/preview/stream/backend")
def stream_browser_backend(slug: str):
    """Report the resolved streamed-browser backend + its availability.

    The frontend uses this to render a friendly install/error state instead of a
    broken ``<img>`` when agent-browser/Chromium (or Playwright) is missing.
    """
    _project_dir(slug)
    backend = _resolve_preview_backend()
    available = True
    detail = "ready"
    if backend == "agent-browser":
        try:
            from spark_cli.browser_runtime import agent_browser_ready

            available, detail = agent_browser_ready()
        except Exception as exc:  # pragma: no cover - import guard
            available, detail = False, str(exc)
    else:
        try:
            import importlib.util

            if importlib.util.find_spec("playwright") is None:
                available, detail = False, "Playwright is not installed"
        except Exception as exc:  # pragma: no cover
            available, detail = False, str(exc)
    return {"slug": slug, "backend": backend, "available": available, "detail": detail}


@router.post("/projects/{slug}/preview/stream/install")
async def stream_browser_install(slug: str):
    """Install the agent-browser runtime + Chromium for the preview pane."""
    _project_dir(slug)

    def _install() -> dict[str, Any]:
        from spark_cli.browser_runtime import install_agent_browser

        return install_agent_browser(quiet=True)

    try:
        result = await asyncio.to_thread(_install)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Install failed: {exc}")
    return {"slug": slug, **result}


@router.post("/projects/{slug}/preview/stream/log")
def stream_browser_log(slug: str, body: StreamLog):
    """Ingest a console/network line forwarded by the native webview's injected script."""
    _project_dir(slug)
    stream = body.stream if body.stream in {"console", "network", "error"} else "console"
    _emit_stream_log(slug, body.text, stream)
    return {"ok": True}


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
