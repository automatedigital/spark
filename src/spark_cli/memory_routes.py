"""FastAPI routes for the Memory page — browse/edit/delete agent memory entries.

Backed by the same `MemoryStore` the agent's `memory` tool uses (Markdown files
under ``SPARK_HOME/memories/``). Each request loads a fresh store from disk so it
reflects writes from the agent and the CLI. Writes emit `memory.updated` (via the
store) so the Web toast + any open page refresh.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
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
    from tools.memory_tool import MemoryStore

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


def register_memory_routes(app) -> None:
    app.include_router(router)
