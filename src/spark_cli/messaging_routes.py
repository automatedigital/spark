"""FastAPI routes for the Messaging page (/api/messaging).

Reads and writes per-platform gateway credentials + enabled state so that
messaging platforms (Telegram, Discord, Slack, ...) can be configured from
the web UI. Implemented in Phase 5 of PLAN.md.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/messaging", tags=["messaging"])


@router.get("/platforms")
def list_platforms() -> dict:
    """Placeholder until Phase 5 lands the full implementation."""
    return {"platforms": []}


def register_messaging_routes(app) -> None:
    app.include_router(router)
