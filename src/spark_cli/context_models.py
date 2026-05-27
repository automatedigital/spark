from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class ContextScope(StrEnum):
    one_turn = "one_turn"
    pinned = "pinned"


class InclusionMode(StrEnum):
    path_only = "path_only"
    excerpt = "excerpt"
    summary = "summary"
    full = "full"
    search = "search"


class ContextItemType(StrEnum):
    file = "file"
    excerpt = "excerpt"
    note = "note"
    tool_output = "tool_output"
    url = "url"


class ContextItem(BaseModel):
    id: str
    type: ContextItemType
    source_path: str | None = None
    inclusion_mode: InclusionMode = InclusionMode.full
    content: str | None = None
    content_ref: str | None = None
    scope: ContextScope = ContextScope.one_turn
    size_bytes: int = 0
    excerpt_range: list[int] | None = None  # [start_line, end_line]
    search_query: str | None = None
    label: str | None = None


class ContextBucket(BaseModel):
    label: str
    tokens: int
    items: list[str] = []


class ContextEstimate(BaseModel):
    prompt_tokens: int
    attached_tokens: int
    pinned_tokens: int
    history_tokens: int
    total_tokens: int
    context_window: int
    utilization: float
    warning: str | None = None  # "compression_likely" | "limit_exceeded" | None
    buckets: list[ContextBucket] = []
