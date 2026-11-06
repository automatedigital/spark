"""FastAPI routes for the Memory page — browse/edit/delete agent memory entries.

Backed by the same `MemoryStore` the agent's `memory` tool uses (Markdown files
under ``SPARK_HOME/memories/``). Each request loads a fresh store from disk so it
reflects writes from the agent and the CLI. Writes emit `memory.updated` (via the
store) so the Web toast + any open page refresh.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi import Path as ApiPath
from pydantic import BaseModel

router = APIRouter(prefix="/api/memory", tags=["memory"])

_TARGETS = ("memory", "user")


class EntryBody(BaseModel):
    content: str


class ReplaceBody(BaseModel):
    old_text: str
    new_content: str


class RemoveBody(BaseModel):
    old_text: str


def _store():
    from core.spark_constants import get_spark_home
    from tools.memory_tool import MemoryStore

    home = get_spark_home().resolve()
    for name in ("MEMORY.md", "USER.md"):
        if not (home / "memories" / name).resolve().is_relative_to(home):
            raise HTTPException(status_code=403, detail="Memory file outside active profile")
    s = MemoryStore()
    s.load_from_disk()
    return s


def _target_payload(store: Any, target: str) -> dict[str, Any]:
    entries = store._entries_for(target)
    current = store._char_count(target)
    limit = store._char_limit(target)
    return {
        "target": target,
        "entries": entries,
        "entry_count": len(entries),
        "chars": current,
        "limit": limit,
        "percent": min(100, int((current / limit) * 100)) if limit > 0 else 0,
    }


def _check_target(target: str) -> None:
    if target not in _TARGETS:
        raise HTTPException(status_code=400, detail=f"Invalid target '{target}'. Use 'memory' or 'user'.")


@router.get("")
def list_memory() -> dict[str, Any]:
    store = _store()
    return {"targets": {t: _target_payload(store, t) for t in _TARGETS}}


@router.post("/{target}/entry")
def add_entry(target: str, body: EntryBody) -> dict[str, Any]:
    _check_target(target)
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="content is required")
    result = _store().add(target, body.content.strip())
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "add failed"))
    return _target_payload(_store(), target)


@router.post("/{target}/replace")
def replace_entry(target: str, body: ReplaceBody) -> dict[str, Any]:
    _check_target(target)
    result = _store().replace(target, body.old_text, body.new_content)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "replace failed"))
    return _target_payload(_store(), target)


@router.delete("/{target}/entry")
def remove_entry(target: str, body: RemoveBody) -> dict[str, Any]:
    _check_target(target)
    result = _store().remove(target, body.old_text)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", "remove failed"))
    return _target_payload(_store(), target)


@router.get("/facts")
def list_facts(q: str = Query("", max_length=200), after: int = Query(0, ge=0, le=9223372036854775807), limit: int = Query(20, ge=1, le=50)) -> dict[str, Any]:
    from spark_cli.memory_read import browse_facts

    return browse_facts(q, after, limit)


@router.get("/facts/{fact_id}")
def fact_detail(fact_id: int = ApiPath(ge=1, le=9223372036854775807)) -> dict[str, Any]:
    from spark_cli.memory_read import browse_facts

    result = browse_facts(fact_id=fact_id)
    if result["status"] == "available" and not result["items"]:
        raise HTTPException(status_code=404, detail="Fact not found")
    return result


@router.get("/reviews")
def list_reviews(after: str = Query("", max_length=255)) -> dict[str, Any]:
    from spark_cli.memory_read import dream_reviews

    return dream_reviews(after)


@router.get("/reviews/{name}")
def review_detail(name: str) -> dict[str, str]:
    from spark_cli.memory_read import MemoryReadUnavailable, read_dream

    try:
        return {"name": name, "content": read_dream(name)}
    except (OSError, UnicodeError, MemoryReadUnavailable):
        raise HTTPException(status_code=404, detail="Review unavailable in active profile") from None


def register_memory_routes(app) -> None:
    app.include_router(router)
