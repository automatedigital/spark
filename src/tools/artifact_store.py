"""Opaque, pageable records for large tool results.

The model receives an ``artifact://`` handle rather than a backend-specific
temporary path.  Locators stay process-local and are scoped to the task that
created them; the active environment remains responsible for the bytes.
"""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import asdict, dataclass

DEFAULT_ARTIFACT_TTL_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class ArtifactRecord:
    handle: str
    content_hash: str
    mime_type: str
    origin_tool: str
    expires_at: int
    size_bytes: int
    total_size: int
    backend_locator: str
    task_id: str

    def public_metadata(self) -> dict:
        data = asdict(self)
        data.pop("backend_locator", None)
        data.pop("task_id", None)
        return data


_records: dict[tuple[str, str], ArtifactRecord] = {}
_lock = threading.RLock()


def content_hash(content: str) -> str:
    encoded = content.encode("utf-8", errors="surrogatepass")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def register_artifact(
    *,
    content: str,
    locator: str,
    origin_tool: str,
    task_id: str = "default",
    mime_type: str = "text/plain; charset=utf-8",
    ttl_seconds: int = DEFAULT_ARTIFACT_TTL_SECONDS,
) -> ArtifactRecord:
    digest = content_hash(content)
    handle = f"artifact://{digest.removeprefix('sha256:')}"
    record = ArtifactRecord(
        handle=handle,
        content_hash=digest,
        mime_type=mime_type,
        origin_tool=origin_tool,
        expires_at=int(time.time()) + max(1, ttl_seconds),
        size_bytes=len(content.encode("utf-8", errors="surrogatepass")),
        total_size=len(content),
        backend_locator=locator,
        task_id=task_id,
    )
    with _lock:
        _records[(task_id, handle)] = record
    return record


def get_artifact(handle: str, task_id: str = "default") -> ArtifactRecord | None:
    with _lock:
        record = _records.get((task_id, handle))
        if record is None:
            return None
        if record.expires_at <= int(time.time()):
            _records.pop((task_id, handle), None)
            return None
        return record


def clear_artifacts(task_id: str | None = None) -> None:
    with _lock:
        if task_id is None:
            _records.clear()
            return
        for key in [key for key in _records if key[0] == task_id]:
            _records.pop(key, None)


def page_content(content: str, offset: int = 0, limit: int = 8_000) -> dict:
    offset = max(0, int(offset))
    limit = min(max(1, int(limit)), 32_000)
    end = min(len(content), offset + limit)
    chunk = content[offset:end]
    return {
        "content": chunk,
        "offset": offset,
        "limit": limit,
        "next_cursor": end if end < len(content) else None,
        "total_size": len(content),
        "content_hash": content_hash(content),
        "truncated": end < len(content),
    }


def search_content(content: str, query: str, limit: int = 20, context: int = 120) -> dict:
    if not query:
        return {"matches": [], "total_matches": 0, "content_hash": content_hash(content)}
    lower_content = content.casefold()
    needle = query.casefold()
    matches = []
    cursor = 0
    max_matches = min(max(1, int(limit)), 100)
    radius = min(max(0, int(context)), 1_000)
    while len(matches) < max_matches:
        index = lower_content.find(needle, cursor)
        if index < 0:
            break
        matches.append(
            {
                "offset": index,
                "preview": content[max(0, index - radius): min(len(content), index + len(query) + radius)],
            }
        )
        cursor = index + max(1, len(query))
    return {
        "matches": matches,
        "total_matches": lower_content.count(needle),
        "content_hash": content_hash(content),
    }


def semantic_preview(content: str, max_chars: int = 1_500) -> tuple[str, bool]:
    """Prefer headings, errors, and a tail when a result needs compaction."""
    if len(content) <= max_chars:
        return content, False
    lines = content.splitlines(keepends=True)
    important = []
    for line in lines:
        stripped = line.lstrip()
        lowered = stripped.casefold()
        if (
            stripped.startswith(("#", "ERROR", "WARN", "FAIL", "Traceback"))
            or " error" in lowered
            or " failed" in lowered
            or "exit code" in lowered
        ):
            important.append(line)
    head_budget = max_chars // 2
    tail_budget = max_chars // 4
    important_budget = max_chars - head_budget - tail_budget
    head = content[:head_budget]
    tail = content[-tail_budget:]
    middle = "".join(important)[:important_budget]
    sections = [head.rstrip(), middle.strip(), tail.lstrip()]
    preview = "\n...\n".join(section for section in sections if section)
    return preview[:max_chars], True
