"""FastAPI routes for the Artifacts page (/api/artifacts).

Aggregates artifacts produced by sessions (generated images, file outputs,
links) derived purely from workspace files — no dedicated index (per the
PLAN.md Phase 6 locked decision).

Each artifact:

    {
        "id": "<slug>:<relative-path>",
        "name": "logo.png",
        "type": "image" | "file" | "link",
        "project_slug": "myproj",
        "project_name": "myproj",
        "path": "assets/logo.png",
        "url": "/api/workspace/projects/myproj/raw-file?path=assets%2Flogo.png",
        "size": 1234,
        "mtime": 1717000000.0,
        "mime": "image/png"
    }

``url`` points at the existing workspace raw-file endpoint so the frontend
can preview/download directly (links instead carry the resolved external
href so they can be opened directly).
"""

from __future__ import annotations

import logging
import mimetypes
import plistlib
import re
import urllib.parse
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, Query

from spark_cli.config import get_spark_home

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}
_LINK_EXTS = {".url", ".webloc"}
_SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".next",
    ".vite",
    ".cache",
    "dist",
    "build",
}
_MAX_DEPTH = 6  # directory levels below a project root
_MAX_ENTRIES = 5000  # hard cap on total scanned artifacts
_DEFAULT_LIMIT = 200
_MAX_LIMIT = 1000

_URL_FILE_RE = re.compile(r"(?im)^\s*URL\s*=\s*(\S+)")


def _workspace_root() -> Path:
    return get_spark_home() / "workspace"


def _extract_link_target(path: Path) -> str | None:
    """Best-effort extraction of the href from a ``.url`` / ``.webloc`` file."""
    try:
        if path.suffix.lower() == ".webloc":
            data = plistlib.loads(path.read_bytes())
            url = data.get("URL") if isinstance(data, dict) else None
            return url if isinstance(url, str) and url.strip() else None
        text = path.read_text(encoding="utf-8", errors="replace")[:8192]
        match = _URL_FILE_RE.search(text)
        return match.group(1) if match else None
    except Exception:
        return None


def _raw_file_url(slug: str, rel_path: str) -> str:
    qs = urllib.parse.urlencode({"path": rel_path})
    return f"/api/workspace/projects/{urllib.parse.quote(slug)}/raw-file?{qs}"


def _classify(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in _IMAGE_EXTS:
        return "image"
    if ext in _LINK_EXTS:
        return "link"
    return "file"


def _scan_project(slug: str, project_dir: Path, budget: int) -> list[dict[str, Any]]:
    """Collect artifacts from one project directory, depth- and budget-capped."""
    artifacts: list[dict[str, Any]] = []
    stack: list[tuple[Path, int]] = [(project_dir, 0)]
    while stack and len(artifacts) < budget:
        directory, depth = stack.pop()
        try:
            entries = sorted(directory.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            continue
        for entry in entries:
            if len(artifacts) >= budget:
                break
            name = entry.name
            if name.startswith("."):
                continue
            try:
                if entry.is_dir():
                    if name in _SKIP_DIRS or depth + 1 > _MAX_DEPTH:
                        continue
                    stack.append((entry, depth + 1))
                    continue
                if not entry.is_file():
                    continue
                stat = entry.stat()
            except OSError:
                continue
            rel = entry.relative_to(project_dir).as_posix()
            kind = _classify(entry)
            mime, _ = mimetypes.guess_type(name)
            if kind == "link":
                url = _extract_link_target(entry) or _raw_file_url(slug, rel)
            else:
                url = _raw_file_url(slug, rel)
            artifacts.append(
                {
                    "id": f"{slug}:{rel}",
                    "name": name,
                    "type": kind,
                    "project_slug": slug,
                    "project_name": slug,
                    "path": rel,
                    "url": url,
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                    "mime": mime or "application/octet-stream",
                }
            )
    return artifacts


def _collect_artifacts() -> list[dict[str, Any]]:
    root = _workspace_root()
    artifacts: list[dict[str, Any]] = []
    if not root.is_dir():
        return artifacts
    try:
        projects = sorted(
            (p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")),
            key=lambda p: p.name.lower(),
        )
    except OSError:
        return artifacts
    for project in projects:
        remaining = _MAX_ENTRIES - len(artifacts)
        if remaining <= 0:
            break
        artifacts.extend(_scan_project(project.name, project, remaining))
    artifacts.sort(key=lambda a: float(a["mtime"]), reverse=True)
    return artifacts


_TYPE_TO_KIND = {"images": "image", "files": "file", "links": "link"}


@router.get("")
def list_artifacts(
    type: str = Query(default="all"),
    limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """List workspace-derived artifacts with type filtering and paging."""
    artifacts = _collect_artifacts()
    counts = {
        "all": len(artifacts),
        "images": sum(1 for a in artifacts if a["type"] == "image"),
        "files": sum(1 for a in artifacts if a["type"] == "file"),
        "links": sum(1 for a in artifacts if a["type"] == "link"),
    }
    kind = _TYPE_TO_KIND.get(type)
    if kind is not None:
        artifacts = [a for a in artifacts if a["type"] == kind]
    return {"artifacts": artifacts[offset : offset + limit], "counts": counts}


def register_artifacts_routes(app: FastAPI) -> None:
    app.include_router(router)
