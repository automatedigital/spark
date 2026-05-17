"""Prompt-injection screener for tool outputs.

Ported from OpenHuman (`src/openhuman/prompt_injection/detector.rs`). Pure
regex + heuristic classifier — no model call. Returns an
``InjectionDecision`` (allow/review/block) with a 0.0–1.0 score and a
structured reason list.

Entry point: ``screen_tool_output(result, tool_name) -> (text, decision)``.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Normalization helpers (mirror detector.rs:218-283)
# --------------------------------------------------------------------------

_ZERO_WIDTH = re.compile(r"[​-‏‪-‮⁠-⁯﻿]")
_WHITESPACE = re.compile(r"\s+")
_CHAR_MAP = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t"})
_BASE64_BLOB = re.compile(r"[A-Za-z0-9+/]{80,}={0,2}")


@dataclass
class _NormalizedViews:
    lower: str          # lowercase, whitespace-collapsed, char-mapped
    compact: str        # whitespace-stripped lower
    had_zero_width: bool
    had_char_map: bool
    had_base64_blob: bool


def _normalize(text: str) -> _NormalizedViews:
    stripped = _ZERO_WIDTH.sub("", text)
    had_zero_width = stripped != text
    had_base64_blob = bool(_BASE64_BLOB.search(stripped))

    lower_raw = _WHITESPACE.sub(" ", stripped.lower().strip())
    mapped = lower_raw.translate(_CHAR_MAP)
    had_char_map = mapped != lower_raw
    compact = re.sub(r"\s+", "", mapped)
    return _NormalizedViews(
        lower=mapped,
        compact=compact,
        had_zero_width=had_zero_width,
        had_char_map=had_char_map,
        had_base64_blob=had_base64_blob,
    )


# --------------------------------------------------------------------------
# Rules (mirror detector.rs:127-195)
# --------------------------------------------------------------------------


@dataclass
class _Rule:
    code: str
    weight: float
    pattern: re.Pattern
    description: str
    family: str  # "override" | "exfiltration" | "tool_abuse"


_RULES: list[_Rule] = [
    _Rule(
        code="override.ignore_previous",
        weight=0.44,
        pattern=re.compile(
            r"\b(ignore|disregard|forget)\b[^.]{0,40}\b(previous|prior|above|all)\b[^.]{0,20}\b(instruction|prompt|message|rule)s?\b"
        ),
        description="Instructs the model to discard prior instructions.",
        family="override",
    ),
    _Rule(
        code="override.role_hijack",
        weight=0.30,
        pattern=re.compile(
            r"\b(act\s+as|pretend\s+to\s+be|you\s+are\s+now|developer\s+mode|jailbreak|unrestricted|dan\b)\b"
        ),
        description="Attempts to switch the model into a different persona / mode.",
        family="override",
    ),
    _Rule(
        code="exfiltrate.system_prompt",
        weight=0.42,
        pattern=re.compile(
            r"\b(reveal|dump|print|show|leak|repeat)\b[^.]{0,40}\b(system\s+prompt|hidden\s+instruction|developer\s+message|initial\s+prompt)s?\b"
        ),
        description="Asks the model to disclose its system prompt or hidden instructions.",
        family="exfiltration",
    ),
    _Rule(
        code="exfiltrate.secrets",
        weight=0.18,
        pattern=re.compile(
            r"\b(api[\s_-]*key|secret\s+key|access\s+token|bearer\s+token|password|jwt|private\s+key)\b"
        ),
        description="Mentions a credential noun.",
        family="exfiltration",
    ),
    _Rule(
        code="exfiltrate.credentials_with_intent",
        weight=0.46,
        pattern=re.compile(
            r"\b(show|send|email|leak|reveal|give|tell|email\s+me|print)\b[^.]{0,15}\b(me|us|the|your)?\b[^.]{0,15}\b(api[\s_-]*key|secret|token|password|jwt|credential|private\s+key)s?\b"
        ),
        description="Verb-with-intent paired with a credential noun.",
        family="exfiltration",
    ),
    _Rule(
        code="tool.abuse",
        weight=0.30,
        pattern=re.compile(
            r"\b(call\s+tools|run\s+commands|execute)\b[^.]{0,40}\b(without\s+approval|without\s+permission|even\s+if\s+forbidden|regardless)\b"
        ),
        description="Instructs the model to invoke tools bypassing the approval flow.",
        family="tool_abuse",
    ),
    _Rule(
        code="prompt.embedded_instruction",
        weight=0.25,
        pattern=re.compile(
            r"\b(new\s+instructions?:|system:|<\|im_start\|>|<system>|###\s*system)\b"
        ),
        description="Embeds explicit instruction markers inside a payload.",
        family="override",
    ),
]


# --------------------------------------------------------------------------
# Public types
# --------------------------------------------------------------------------


@dataclass
class InjectionReason:
    code: str
    weight: float
    message: str


Verdict = Literal["allow", "review", "block"]


@dataclass
class InjectionDecision:
    verdict: Verdict
    score: float
    reasons: list[InjectionReason] = field(default_factory=list)
    prompt_sha256: str = ""
    char_count: int = 0
    block_threshold: float = 0.70
    review_threshold: float = 0.45


def _classify(
    text: str,
    block_threshold: float,
    review_threshold: float,
) -> InjectionDecision:
    norm = _normalize(text)
    reasons: list[InjectionReason] = []
    score = 0.0
    families_hit: set[str] = set()

    haystacks = (norm.lower, norm.compact)
    for rule in _RULES:
        if any(rule.pattern.search(h) for h in haystacks):
            reasons.append(
                InjectionReason(
                    code=rule.code, weight=rule.weight, message=rule.description
                )
            )
            score += rule.weight
            families_hit.add(rule.family)

    # Heuristic obfuscation bonus (mirrors detector.rs:332).
    obfuscation_signals = sum(
        [norm.had_zero_width, norm.had_char_map, norm.had_base64_blob]
    )
    if obfuscation_signals and (
        "override" in families_hit or "exfiltration" in families_hit
    ):
        bonus = min(0.25, 0.08 * obfuscation_signals + 0.10)
        score += bonus
        reasons.append(
            InjectionReason(
                code="heuristic.obfuscation",
                weight=bonus,
                message="Obfuscation signals (zero-width / char-map / base64) co-occurred with an override or exfiltration hit.",
            )
        )

    score = min(score, 1.0)
    if score >= block_threshold:
        verdict: Verdict = "block"
    elif score >= review_threshold:
        verdict = "review"
    else:
        verdict = "allow"

    return InjectionDecision(
        verdict=verdict,
        score=round(score, 4),
        reasons=reasons,
        prompt_sha256=hashlib.sha256(text.encode("utf-8", "replace")).hexdigest(),
        char_count=len(text),
        block_threshold=block_threshold,
        review_threshold=review_threshold,
    )


def screen_tool_output(
    result: str,
    tool_name: str,
    block_threshold: float = 0.70,
    review_threshold: float = 0.45,
) -> tuple[str, InjectionDecision]:
    """Classify a tool result. Caller decides what to do based on the verdict."""
    if not isinstance(result, str) or not result:
        return result, InjectionDecision(
            verdict="allow", score=0.0, char_count=0,
            block_threshold=block_threshold, review_threshold=review_threshold,
        )
    decision = _classify(result, block_threshold, review_threshold)
    return result, decision


def blocked_stub(decision: InjectionDecision, tool_name: str = "") -> str:
    """Stub returned by callers in enforce mode for a blocked result."""
    codes = ",".join(r.code for r in decision.reasons[:4])
    return (
        f"[BLOCKED: tool output suspected of prompt injection "
        f"(tool={tool_name or '?'}, score={decision.score:.2f}, "
        f"sha256={decision.prompt_sha256[:12]}, hits={codes}). "
        f"See logs for full decision.]"
    )
