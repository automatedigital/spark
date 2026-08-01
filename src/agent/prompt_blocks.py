"""Immutable, typed system-prompt blocks and cache-segment adapters."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from agent.model_metadata import estimate_tokens_rough


class StabilityScope(StrEnum):
    RELEASE = "release"
    PROFILE = "profile"
    PROJECT = "project"
    SESSION = "session"
    TURN = "turn"


_SCOPE_ORDER = {
    StabilityScope.RELEASE: 0,
    StabilityScope.PROFILE: 1,
    StabilityScope.PROJECT: 1,
    StabilityScope.SESSION: 2,
    StabilityScope.TURN: 3,
}


def content_fingerprint(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", errors="surrogatepass")).hexdigest()


@dataclass(frozen=True, slots=True)
class PromptBlock:
    kind: str
    content: str
    scope: StabilityScope
    source: str
    order: int
    content_hash: str
    token_estimate: int

    @classmethod
    def create(
        cls,
        *,
        kind: str,
        content: str,
        scope: StabilityScope | str,
        source: str,
        order: int,
    ) -> PromptBlock:
        normalized = content.strip()
        stable_scope = StabilityScope(scope)
        return cls(
            kind=kind,
            content=normalized,
            scope=stable_scope,
            source=source,
            order=order,
            content_hash=content_fingerprint(normalized),
            token_estimate=estimate_tokens_rough(normalized),
        )


@dataclass(frozen=True, slots=True)
class PromptSegment:
    name: str
    blocks: tuple[PromptBlock, ...]
    content: str
    fingerprint: str
    token_estimate: int


@dataclass(frozen=True, slots=True)
class PromptBundle:
    blocks: tuple[PromptBlock, ...]
    segments: tuple[PromptSegment, ...]
    fingerprint: str
    reusable_fingerprint: str

    @classmethod
    def build(cls, blocks: Iterable[PromptBlock]) -> PromptBundle:
        ordered = tuple(sorted(blocks, key=lambda b: (_SCOPE_ORDER[b.scope], b.order)))
        segment_specs = (
            ("release", {StabilityScope.RELEASE}),
            ("profile_project", {StabilityScope.PROFILE, StabilityScope.PROJECT}),
            ("session", {StabilityScope.SESSION, StabilityScope.TURN}),
        )
        segments: list[PromptSegment] = []
        for name, scopes in segment_specs:
            selected = tuple(block for block in ordered if block.scope in scopes)
            content = "\n\n".join(block.content for block in selected if block.content)
            manifest = [(b.kind, b.source, b.content_hash) for b in selected]
            fingerprint = content_fingerprint(json.dumps(manifest, separators=(",", ":")))
            segments.append(PromptSegment(
                name=name,
                blocks=selected,
                content=content,
                fingerprint=fingerprint,
                token_estimate=sum(block.token_estimate for block in selected),
            ))
        full_manifest = [(segment.name, segment.fingerprint) for segment in segments]
        reusable_manifest = full_manifest[:2]
        return cls(
            blocks=ordered,
            segments=tuple(segments),
            fingerprint=content_fingerprint(json.dumps(full_manifest, separators=(",", ":"))),
            reusable_fingerprint=content_fingerprint(
                json.dumps(reusable_manifest, separators=(",", ":"))
            ),
        )

    def render(self) -> str:
        return "\n\n".join(segment.content for segment in self.segments if segment.content)

    def metadata(self) -> dict:
        return {
            "fingerprint": self.fingerprint,
            "reusable_fingerprint": self.reusable_fingerprint,
            "segments": [
                {
                    "name": segment.name,
                    "fingerprint": segment.fingerprint,
                    "tokens": segment.token_estimate,
                    "sources": [block.source for block in segment.blocks],
                }
                for segment in self.segments
            ],
        }


@dataclass(frozen=True, slots=True)
class PromptLintIssue:
    code: str
    message: str
    sources: tuple[str, ...] = ()


_TIMESTAMP_RE = re.compile(
    r"\b(?:conversation started|current (?:date|time)|timestamp)\b",
    re.IGNORECASE,
)


def lint_prompt_blocks(
    blocks: Sequence[PromptBlock],
    tool_definitions: Sequence[dict] | None = None,
) -> tuple[PromptLintIssue, ...]:
    """Report cache hazards without changing user-authored instructions."""

    issues: list[PromptLintIssue] = []
    by_hash: dict[str, list[PromptBlock]] = {}
    by_source: dict[str, list[PromptBlock]] = {}
    for block in blocks:
        by_hash.setdefault(block.content_hash, []).append(block)
        by_source.setdefault(block.source, []).append(block)
        if block.scope not in {StabilityScope.SESSION, StabilityScope.TURN} and _TIMESTAMP_RE.search(block.content):
            issues.append(PromptLintIssue(
                "unstable-in-stable-segment",
                f"Timestamp-like content appears in {block.scope.value} block {block.kind!r}.",
                (block.source,),
            ))
    for duplicates in by_hash.values():
        if len(duplicates) > 1 and duplicates[0].content:
            issues.append(PromptLintIssue(
                "duplicate-guidance",
                "Identical prompt guidance is included more than once.",
                tuple(block.source for block in duplicates),
            ))
    for source, repeated in by_source.items():
        if len(repeated) > 1 and source.startswith("context:"):
            issues.append(PromptLintIssue(
                "duplicate-context-source",
                f"Context source {source!r} is included more than once.",
                (source,),
            ))
    if tool_definitions:
        names = [d.get("function", {}).get("name", "") for d in tool_definitions]
        if names != sorted(names):
            issues.append(PromptLintIssue(
                "unordered-tool-schemas",
                "Tool schemas are not ordered by name; preserve the frozen session order.",
                tuple(names),
            ))
    return tuple(issues)


def anthropic_system_segments(
    bundle: PromptBundle,
    *,
    cache_ttl: str = "5m",
    ephemeral_suffix: str = "",
) -> list[dict]:
    """Map typed segments to Anthropic content breakpoints."""

    marker: dict[str, str] = {"type": "ephemeral"}
    if cache_ttl == "1h":
        marker["ttl"] = "1h"
    content: list[dict] = []
    for segment in bundle.segments:
        if not segment.content:
            continue
        block: dict[str, Any] = {"type": "text", "text": segment.content}
        if segment.name != "session":
            block["cache_control"] = dict(marker)
        content.append(block)
    suffix = ephemeral_suffix.strip()
    if suffix:
        content.append({"type": "text", "text": suffix})
    return content
