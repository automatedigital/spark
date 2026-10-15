"""Sidebar routes. Include `router` on the dashboard app to reuse its auth.

Integration: override get_sidebar_settle_guard with a dependency returning a
sync callable(session_id) -> blocking reason | None, backed by the authoritative
live-run registry (including compression family and owned children). This fails
closed until wired. Durable decisions and projections are also checked in the
metadata transaction. The guard runs inside SessionDB's write lock, after CAS;
it must not reenter that same connection. Callbacks must not mutate metadata or execution state.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError, model_validator

from core.spark_state import SessionDB
from spark_cli.sidebar_metadata import MetadataConflict, SettleBlocked, SidebarMetadata

router = APIRouter(prefix="/api/sidebar", tags=["sidebar"])
SettleGuard = Callable[[str], str | None]


def get_sidebar_db() -> Iterator[SessionDB]:
    db = SessionDB()
    try:
        yield db
    finally:
        db.close()


def get_sidebar_publisher() -> Callable[[str], None]:
    # Publish on the existing subscribed session topic, only after DB commit.
    from spark_cli.web_server import _emit_sessions_changed

    return lambda sid: _emit_sessions_changed("sidebar_metadata", sid)


def get_sidebar_settle_guard() -> SettleGuard:
    return lambda _sid: "Live-work validation is unavailable; reconnect before settling"


class SidebarPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    expected_revision: int = Field(ge=0)
    pinned: StrictBool | None = None
    settled: StrictBool | None = None
    position: float | None = None

    @model_validator(mode="after")
    def explicit_changes(self):
        changes = self.model_fields_set - {"expected_revision"}
        if not changes or any(getattr(self, key) is None for key in changes - {"position"}):
            raise ValueError("Provide at least one metadata field; only position may be null")
        return self


def parse_sidebar_patch(payload: Annotated[Any, Body()]) -> SidebarPatch:
    try:
        return SidebarPatch.model_validate(payload)
    except ValidationError as exc:
        # Do not echo untrusted input: NaN/Infinity in validation errors cannot
        # themselves be JSON encoded by Starlette's response implementation.
        raise HTTPException(
            422, detail=exc.errors(include_input=False, include_context=False)
        ) from exc


@router.get("/threads")
def get_sidebar_threads(db: Annotated[SessionDB, Depends(get_sidebar_db)]):
    metadata = SidebarMetadata(db)
    return {
        "schema_version": 1,
        "entries": metadata.snapshot(),
        "attention": metadata.attention(),
        "preference_scope": hashlib.sha256(str(db.db_path.resolve()).encode()).hexdigest()[:24],
    }


@router.patch("/threads/{session_id}")
def patch_sidebar_thread(
    session_id: str,
    body: Annotated[SidebarPatch, Depends(parse_sidebar_patch)],
    db: Annotated[SessionDB, Depends(get_sidebar_db)],
    guard: Annotated[SettleGuard, Depends(get_sidebar_settle_guard)],
    publish: Annotated[Callable[[str], None], Depends(get_sidebar_publisher)],
):
    # Exact IDs only: never let a prefix mutate another thread's metadata.
    if not db.get_session(session_id):
        raise HTTPException(404, "Session not found")
    family = db.resolve_compression_chain(session_id)
    changes = body.model_dump(exclude_unset=True, exclude={"expected_revision"})
    try:
        current = SidebarMetadata(db).patch(
            session_id, body.expected_revision, changes, family=family, settle_guard=guard
        )
    except MetadataConflict as exc:
        return JSONResponse(
            status_code=409,
            content={
                "detail": "Metadata changed; review the current values",
                "current": exc.current,
            },
        )
    except SettleBlocked as exc:
        raise HTTPException(409, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "Session not found") from exc
    try:
        publish(session_id)
    except Exception:
        # A transport failure cannot roll back or misreport a committed write.
        logging.getLogger(__name__).exception("Sidebar metadata committed; live publish failed")
    return {"schema_version": 1, "session_id": session_id, "metadata": current}
