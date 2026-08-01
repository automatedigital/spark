"""Bounded read/search access to opaque large-result artifacts."""

from __future__ import annotations

import json

from tools.artifact_store import get_artifact, page_content, search_content
from tools.registry import registry

ARTIFACT_SCHEMA = {
    "name": "artifact_read",
    "description": "Read or search a persisted large tool result by opaque artifact handle. Pages use character offsets and never re-persist.",
    "parameters": {
        "type": "object",
        "properties": {
            "handle": {"type": "string", "description": "artifact:// handle from a tool result"},
            "offset": {"type": "integer", "minimum": 0, "default": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 32000, "default": 8000},
            "query": {"type": "string", "description": "Optional case-insensitive search query"},
        },
        "required": ["handle"],
    },
}


def _handle_artifact(args, **kwargs) -> str:
    task_id = kwargs.get("task_id") or "default"
    handle = str(args.get("handle") or "")
    record = get_artifact(handle, task_id=task_id)
    if record is None:
        return json.dumps({"error": "Artifact handle is missing, expired, or belongs to another task."})

    from tools.file_tools import _get_file_ops

    result = _get_file_ops(task_id).read_file_raw(record.backend_locator)
    if result.error:
        return json.dumps({"error": result.error, "handle": handle})
    content = result.content or ""
    query = args.get("query")
    payload = (
        search_content(content, str(query), limit=args.get("limit", 20))
        if query
        else page_content(content, offset=args.get("offset", 0), limit=args.get("limit", 8000))
    )
    payload.update(record.public_metadata())
    return json.dumps(payload, ensure_ascii=False)


registry.register(
    name="artifact_read",
    toolset="file",
    schema=ARTIFACT_SCHEMA,
    handler=_handle_artifact,
    max_result_size_chars=float("inf"),
    normalize=False,
    emoji="📦",
)
