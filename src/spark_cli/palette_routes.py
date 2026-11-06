"""Bounded, read-only palette projections; no startup discovery or shared cache."""

from typing import Literal

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/palette", tags=["palette"])
Category = Literal["recent", "threads", "messages", "projects", "jobs", "skills"]


def _item(kind: str, identifier: str, label: str, description: str = "") -> dict:
    return {"kind": kind, "id": str(identifier), "label": label[:160], "description": description[:240]}


def lookup(category: Category, q: str, limit: int, offset: int) -> dict:
    """Own/close DB handles in this worker. Only explicit queries discover domains."""
    query = q.strip()
    if category != "recent" and not query:
        return {"items": [], "next": None}
    size = limit + 1
    if category in {"recent", "threads", "messages"}:
        import re

        from core.spark_state import SessionDB

        db = SessionDB()
        try:
            if category == "recent":
                rows = db.list_sessions_rich(limit=size, offset=offset, include_children=False)
                items = [_item("thread", s["id"], s.get("title") or s.get("preview") or "New thread", s.get("preview") or s.get("model") or "") for s in rows]
            elif category == "threads":
                # Same root-session visibility and newest-first ordering as list_sessions_rich.
                # Escape LIKE metacharacters so a palette query is a literal substring.
                pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                with db._lock:
                    rows = db._conn.execute(
                        "SELECT id, title, model FROM sessions WHERE parent_session_id IS NULL "
                        "AND (title LIKE ? ESCAPE '\\' OR id LIKE ? ESCAPE '\\') "
                        "ORDER BY started_at DESC, id LIMIT ? OFFSET ?",
                        (pattern, pattern, size, offset),
                    ).fetchall()
                items = [_item("thread", s["id"], s["title"] or "New thread", s["model"] or "") for s in rows]
            else:
                # Preserve the existing search endpoint's prefix/FTS semantics.
                terms = [token if token.startswith('"') or token.endswith("*") else token + "*" for token in re.findall(r'"[^"]*"|\S+', query)]
                rows = db.search_messages(" ".join(terms), limit=size, offset=offset)
                items = [_item("message", str(s["id"]), s.get("title") or "Conversation match", s.get("snippet", "").replace(">>>", "").replace("<<<", "")) | {"destination": s["session_id"]} for s in rows]
        finally:
            db.close()
    else:
        needle = query.casefold()
        aliases = {"projects": {"projects", "project"}, "jobs": {"jobs", "schedule", "scheduled tasks"}, "skills": {"skills", "skill"}}
        if needle in aliases.get(category, set()):
            needle = ""
        if category == "projects":
            from spark_cli.workspace_routes import _workspace_root

            root = _workspace_root()
            items = [_item("project", p.name, p.name, str(p)) for p in sorted(root.iterdir()) if not p.name.startswith(".") and needle in p.name.casefold() and p.is_dir()]
        elif category == "jobs":
            from cron.jobs import list_jobs

            items = [_item("scheduled-task", j["id"], j.get("name") or j.get("prompt", "")[:80], j.get("schedule_display") or "") for j in list_jobs(include_disabled=True) if needle in (str(j.get("name", "")) + " " + str(j.get("prompt", ""))).casefold()]
        else:
            from tools.skills_metadata import iter_skill_records

            items = [_item("skill", s["name"], s["name"], s.get("description") or "") for s in iter_skill_records(include_duplicates=False) if needle in (s["name"] + " " + (s.get("description") or "")).casefold()]
        items = items[offset:offset + size]
    return {"items": items[:limit], "next": offset + limit if len(items) > limit else None}


@router.get("/{category}")
def search_palette(category: Category, q: str = Query(default="", max_length=200), limit: int = Query(default=12, ge=1, le=20), offset: int = Query(default=0, ge=0, le=100000)):
    # A synchronous route uses FastAPI's worker pool instead of blocking the event loop.
    return lookup(category, q, limit, offset)


def register_palette_routes(app) -> None:
    app.include_router(router)
