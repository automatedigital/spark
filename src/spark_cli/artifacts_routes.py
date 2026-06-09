"""FastAPI routes for the Artifacts page (/api/artifacts).

Aggregates artifacts produced by sessions (generated images, file outputs,
links) derived from workspace files + session outputs. Implemented in
Phase 6 of PLAN.md.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])


@router.get("")
def list_artifacts() -> dict:
    """Placeholder until Phase 6 lands the full implementation."""
    return {"artifacts": [], "counts": {"all": 0, "images": 0, "files": 0, "links": 0}}


def register_artifacts_routes(app) -> None:
    app.include_router(router)
