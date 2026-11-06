"""Bounded, profile-contained memory browsing; never initializes a provider."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import yaml

from core.spark_constants import get_spark_home


class MemoryReadUnavailable(Exception):
    """A store cannot safely be browsed without changing it."""


def _contained(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(get_spark_home().resolve()):
        raise MemoryReadUnavailable("Store is outside the active profile.")
    return resolved


def _database() -> Path:
    home = get_spark_home()
    config_path = _contained(home / "config.yaml")
    config: dict[str, Any] = {}
    if config_path.exists():
        with config_path.open() as stream:
            content = stream.read(262145)
        if len(content) > 262144:
            raise MemoryReadUnavailable("Configuration exceeds browsing limit.")
        config = yaml.safe_load(content) or {}
    raw = config.get("plugins", {}).get("spark-memory-store", {}).get("db_path", str(home / "memory_store.db"))
    raw = str(raw).replace("${SPARK_HOME}", str(home)).replace("$SPARK_HOME", str(home))
    path = Path(raw).expanduser()
    return _contained(path if path.is_absolute() else home / path)


def browse_facts(query: str = "", after: int = 0, limit: int = 20, fact_id: int | None = None) -> dict[str, Any]:
    """Literal substring search, ID pagination, bounded SQL work and payloads.

    No SDK imports, vectors, ranking, retrieval counters, migrations or recovery.
    Old stores lacking optional metadata remain readable with null metadata.
    """
    try:
        path = _database()
        if not path.is_file():
            return {"status": "missing", "items": [], "next_after": None}
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0.2)) as db:
            db.row_factory = sqlite3.Row
            db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1048576)
            db.execute("PRAGMA query_only=ON")
            # Also bound scans of old stores without usable indexes.
            remaining = 2000

            def budget() -> int:
                nonlocal remaining
                remaining -= 1
                return int(remaining <= 0)

            db.set_progress_handler(budget, 1000)
            columns = {row[1] for row in db.execute("PRAGMA table_info(facts)")}
            if not {"fact_id", "content"}.issubset(columns):
                raise MemoryReadUnavailable("Older or unsupported facts schema.")
            fields = ["fact_id", "substr(content,1,16384) AS content", "length(content) > 16384 AS content_truncated"]
            for name in ("source", "category", "created_at", "updated_at"):
                fields.append(f'substr("{name}",1,512) AS "{name}"' if name in columns else f'NULL AS "{name}"')
            where = "fact_id = ?" if fact_id is not None else "fact_id > ? AND instr(lower(content), lower(?)) > 0"
            params = (fact_id,) if fact_id is not None else (after, query)
            rows = db.execute(f"SELECT {', '.join(fields)} FROM facts WHERE {where} ORDER BY fact_id LIMIT ?", (*params, limit + 1)).fetchall()
            return {"status": "available", "items": [dict(row) for row in rows[:limit]],
                    "next_after": rows[limit - 1]["fact_id"] if len(rows) > limit else None}
    except (OSError, sqlite3.Error, ValueError, TypeError, AttributeError, yaml.YAMLError, MemoryReadUnavailable):
        return {"status": "unavailable", "items": [], "next_after": None,
                "message": "Local facts unavailable: unsupported, busy, outside profile or unreadable store. No repair was attempted."}


def dream_reviews(after: str = "", limit: int = 20) -> dict[str, Any]:
    """Only actual review files, in bounded directory order (no inferred provenance)."""
    try:
        root = _contained(get_spark_home() / "workspace/wiki/dreams")
        if not root.exists():
            return {"status": "missing", "items": []}
        # Bound directory enumeration as well as response size.
        import itertools

        candidates = list(itertools.islice(root.iterdir(), 1001))
        if len(candidates) > 1000:
            raise MemoryReadUnavailable("Too many review files.")
        items = []
        for path in sorted(candidates, key=lambda p: p.name):
            if path.name <= after or path.name == "index.md" or path.suffix != ".md":
                continue
            safe = _contained(path)
            if safe.is_file():
                items.append({"name": path.name})
            if len(items) > limit:
                break
        return {"status": "available", "items": items[:limit],
                "next_after": items[limit - 1]["name"] if len(items) > limit else None}
    except (OSError, MemoryReadUnavailable):
        return {"status": "unavailable", "items": []}


def read_dream(name: str) -> str:
    if Path(name).name != name or not name.endswith(".md") or name == "index.md":
        raise MemoryReadUnavailable("Invalid review name.")
    path = _contained(get_spark_home() / "workspace/wiki/dreams" / name)
    with path.open("r", encoding="utf-8") as stream:
        content = stream.read(65537)
    if len(content) > 65536:
        raise MemoryReadUnavailable("Review exceeds the browsing limit.")
    return content
