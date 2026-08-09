"""FastAPI routes for the log viewer.

Extracted from web_server.py. The handlers import from spark_cli.logs lazily,
so importing this module does not read any log file.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from core.spark_constants import get_spark_home

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("")
async def get_logs(
    file: str = "agent",
    lines: int = 100,
    level: str | None = None,
    component: str | None = None,
    search: str | None = None,
):
    from spark_cli.logs import LOG_FILES, _read_tail

    log_name = LOG_FILES.get(file)
    if not log_name:
        raise HTTPException(status_code=400, detail=f"Unknown log file: {file}")
    log_path = get_spark_home() / "logs" / log_name
    if not log_path.exists():
        return {"file": file, "lines": []}

    try:
        from core.spark_logging import COMPONENT_PREFIXES
    except ImportError:
        COMPONENT_PREFIXES = {}

    # Normalize "ALL" / "all" / empty → no filter. _matches_filters treats an
    # empty tuple as "must match a prefix" (startswith(()) is always False),
    # so passing () instead of None silently drops every line.
    min_level = level if level and level.upper() != "ALL" else None
    if component and component.lower() != "all":
        comp_prefixes = COMPONENT_PREFIXES.get(component)
        if comp_prefixes is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown component: {component}. "
                f"Available: {', '.join(sorted(COMPONENT_PREFIXES))}",
            )
    else:
        comp_prefixes = None

    has_filters = bool(min_level or comp_prefixes or search)
    result = _read_tail(
        log_path,
        min(lines, 500) if not search else 2000,
        has_filters=has_filters,
        min_level=min_level,
        component_prefixes=comp_prefixes,
    )
    # Post-filter by search term (case-insensitive substring match).
    # _read_tail doesn't support free-text search, so we filter here and
    # trim to the requested line count afterward.
    if search:
        needle = search.lower()
        result = [line for line in result if needle in line.lower()][-min(lines, 500):]
    return {"file": file, "lines": result}


@router.get("/download")
async def download_log(file: str = "agent"):
    from spark_cli.logs import LOG_FILES

    log_name = LOG_FILES.get(file)
    if not log_name:
        raise HTTPException(status_code=400, detail=f"Unknown log file: {file}")
    log_path = get_spark_home() / "logs" / log_name
    if not log_path.exists():
        raise HTTPException(status_code=404, detail=f"Log file not found: {file}")
    return FileResponse(log_path, media_type="text/plain", filename=log_name)


def register_logs_routes(app) -> None:
    app.include_router(router)
